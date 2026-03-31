from __future__ import annotations
from datasette_enrichments import Enrichment
from datasette import hookimpl
from datasette.database import Database
import httpx
from llm import Attachment
from typing import List, Optional
from wtforms import (
    Form,
    StringField,
    TextAreaField,
    SelectField,
    BooleanField,
)
from wtforms.validators import DataRequired
import sqlite_utils

PURPOSE = "enrichments"


@hookimpl
def register_enrichments():
    return [LlmEnrichment()]


@hookimpl
def register_llm_purposes(datasette):
    from datasette_llm import Purpose

    return [
        Purpose(
            name=PURPOSE,
            description="Enrich data by prompting LLMs",
        )
    ]


class LlmEnrichment(Enrichment):
    name = "AI analysis with LLM"
    slug = "llm"
    description = "Analyze data using Large Language Models"
    runs_in_process = True
    batch_size = 1

    async def get_config_form(self, datasette, db, table):
        from datasette_llm import LLM

        llm = LLM(datasette)
        columns = await db.table_columns(table)

        # Default template uses all string columns
        default = " ".join("{{ COL }}".replace("COL", col) for col in columns)

        url_columns = [col for col in columns if "url" in col.lower()]
        media_url_suggestion = ""
        if url_columns:
            media_url_suggestion = "{{ %s }}" % url_columns[0]

        all_models = await llm.models(purpose=PURPOSE)
        models = [(model.model_id, model.model_id) for model in all_models]

        class ConfigForm(Form):
            model = SelectField(
                "Model",
                choices=models,
                default="gpt-4o-mini",
            )
            prompt = TextAreaField(
                "Prompt",
                description="A template to run against each row to generate a prompt. Use {{ COL }} for columns.",
                default=default,
                validators=[DataRequired(message="Prompt is required.")],
                render_kw={"style": "height: 8em"},
            )
            use_media = BooleanField(
                "Use media",
                description="Use multi-modal model to fetch and analyze media",
                default=False,
            )
            media_url = StringField(
                "Media URL",
                description="Media URL template. Only used with multi-modal models.",
                default=media_url_suggestion,
            )
            system_prompt = TextAreaField(
                "System prompt",
                description="Instructions to apply to the main prompt. Can only be a static string, no {{ columns }}",
                default="",
            )
            output_column = StringField(
                "Output column name",
                description="The column to store the output in - will be created if it does not exist.",
                validators=[DataRequired(message="Column is required.")],
                default="prompt_output",
            )

        return ConfigForm

    async def initialize(self, datasette, db, table, config):
        # Ensure column exists
        output_column = config["output_column"]

        def add_column_if_not_exists(conn):
            db = sqlite_utils.Database(conn)
            if output_column not in db[table].columns_dict:
                db[table].add_column(output_column, str)

        await db.execute_write_fn(add_column_if_not_exists)

    async def enrich_batch(
        self,
        datasette,
        db: Database,
        table: str,
        rows: List[dict],
        pks: List[str],
        config: dict,
        job_id: int,
    ) -> List[Optional[str]]:
        if rows:
            row = rows[0]
        else:
            return

        from datasette_llm import LLM

        llm = LLM(datasette)
        prompt = config["prompt"] or ""
        system = config["system_prompt"] or None
        output_column = config["output_column"]
        use_media = config["use_media"]
        media_url = config["media_url"]
        attachments = []
        for key, value in row.items():
            prompt = prompt.replace("{{ %s }}" % key, str(value or "")).replace(
                "{{%s}}" % key, str(value or "")
            )
            if media_url:
                media_url = media_url.replace(
                    "{{ %s }}" % key, str(value or "")
                ).replace("{{%s}}" % key, str(value or ""))

        if use_media:
            # Fetch media_url and use as binary content
            try:
                async with httpx.AsyncClient() as client:
                    print("getting ", media_url)
                    response = await client.get(media_url)
                    response.raise_for_status()
                    attachments.append(Attachment(content=response.content))
            except httpx.HTTPError:
                await self.log_error(
                    db,
                    job_id,
                    pks,
                    "Failed to fetch media from {}".format(media_url),
                )
                return

        model_id = config["model"]
        model = await llm.model(model_id, purpose=PURPOSE)
        response = await model.prompt(prompt, system=system, attachments=attachments)
        output = await response.text()
        await db.execute_write(
            "update [{table}] set [{output_column}] = ? where {wheres}".format(
                table=table,
                output_column=output_column,
                wheres=" and ".join('"{}" = ?'.format(pk) for pk in pks),
            ),
            [output] + list(row[pk] for pk in pks),
        )

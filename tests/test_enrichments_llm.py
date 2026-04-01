import asyncio
from contextlib import asynccontextmanager
from datasette.app import Datasette
from datasette import hookimpl
from datasette.plugins import pm
import json
import pytest
import sqlite_utils

CONFIG = {
    "permissions": {"enrichments": {"id": "root"}},
}


async def _cookies(datasette, path="/-/enrich/data/items/llm"):
    cookies = {"ds_actor": datasette.sign({"a": {"id": "root"}}, "actor")}
    csrftoken = (await datasette.client.get(path, cookies=cookies)).cookies[
        "ds_csrftoken"
    ]
    cookies["ds_csrftoken"] = csrftoken
    return cookies


@pytest.mark.asyncio
async def test_plugin_is_installed():
    datasette = Datasette(memory=True)
    response = await datasette.client.get("/-/plugins.json")
    assert response.status_code == 200
    installed_plugins = {p["name"] for p in response.json()}
    assert "datasette-enrichments-llm" in installed_plugins


@pytest.mark.asyncio
async def test_enrichment(tmpdir):
    data = str(tmpdir / "data.db")
    datasette = Datasette([data], memory=True, config=CONFIG)
    db = sqlite_utils.Database(data)
    db["items"].insert_all(
        [
            {"id": 1, "name": "One", "description": "First item"},
            {"id": 2, "name": "Two", "description": "Second item"},
        ],
        pk="id",
    )

    cookies = await _cookies(datasette)
    post = {
        "model": "echo",
        "prompt": "Summarize: {{ description }}",
        "system_prompt": "",
        "output_column": "summary",
        "use_media": "",
        "media_url": "",
        "csrftoken": cookies["ds_csrftoken"],
    }
    response = await datasette.client.post(
        "/-/enrich/data/items/llm",
        data=post,
        cookies=cookies,
    )
    assert response.status_code == 302
    await asyncio.sleep(0.5)
    db = datasette.get_database("data")
    jobs = await db.execute("select * from _enrichment_jobs")
    job = dict(jobs.first())
    assert job["status"] == "finished"
    assert job["enrichment"] == "llm"
    assert job["done_count"] == 2
    assert job["actor_id"] == "root"

    # Check that echo model output was written to the summary column
    results = await db.execute("select id, summary from items order by id")
    rows = [dict(r) for r in results.rows]
    for row in rows:
        output = json.loads(row["summary"])
        assert "Summarize:" in output["prompt"]
        assert not output["system"]


@pytest.mark.asyncio
async def test_enrichment_with_system_prompt(tmpdir):
    data = str(tmpdir / "data.db")
    datasette = Datasette([data], memory=True, config=CONFIG)
    db = sqlite_utils.Database(data)
    db["items"].insert_all(
        [{"id": 1, "name": "One", "description": "First item"}],
        pk="id",
    )

    cookies = await _cookies(datasette)
    post = {
        "model": "echo",
        "prompt": "{{ description }}",
        "system_prompt": "You are a helpful assistant",
        "output_column": "result",
        "use_media": "",
        "media_url": "",
        "csrftoken": cookies["ds_csrftoken"],
    }
    response = await datasette.client.post(
        "/-/enrich/data/items/llm",
        data=post,
        cookies=cookies,
    )
    assert response.status_code == 302
    await asyncio.sleep(0.5)
    db = datasette.get_database("data")
    results = await db.execute("select result from items")
    output = json.loads(dict(results.first())["result"])
    assert output["prompt"] == "First item"
    assert output["system"] == "You are a helpful assistant"


@pytest.mark.asyncio
async def test_enrichment_passes_actor(tmpdir):
    """Test that the actor is resolved from actor_id and passed to llm.model()."""
    hook_calls = []

    class ActorTracker:
        __name__ = "actor_tracker_plugin"

        @hookimpl
        def llm_prompt_context(self, datasette, model_id, prompt, purpose, actor):
            @asynccontextmanager
            async def tracker(result):
                hook_calls.append(
                    {
                        "model_id": model_id,
                        "purpose": purpose,
                        "actor": actor,
                    }
                )
                yield

            return tracker

    plugin = ActorTracker()
    pm.register(plugin)
    try:
        data = str(tmpdir / "data.db")
        datasette = Datasette([data], memory=True, config=CONFIG)
        db = sqlite_utils.Database(data)
        db["items"].insert_all(
            [{"id": 1, "name": "One", "description": "First item"}],
            pk="id",
        )

        cookies = await _cookies(datasette)
        post = {
            "model": "echo",
            "prompt": "{{ description }}",
            "system_prompt": "",
            "output_column": "result",
            "use_media": "",
            "media_url": "",
            "csrftoken": cookies["ds_csrftoken"],
        }
        response = await datasette.client.post(
            "/-/enrich/data/items/llm",
            data=post,
            cookies=cookies,
        )
        assert response.status_code == 302
        await asyncio.sleep(0.5)

        # Verify the job completed
        db = datasette.get_database("data")
        jobs = await db.execute("select * from _enrichment_jobs")
        job = dict(jobs.first())
        assert job["status"] == "finished"
        assert job["actor_id"] == "root"

        # Verify the hook saw the correct actor and purpose
        assert len(hook_calls) == 1
        assert hook_calls[0]["model_id"] == "echo"
        assert hook_calls[0]["purpose"] == "enrichments"
        assert hook_calls[0]["actor"] == {"id": "root"}
    finally:
        pm.unregister(plugin)

# datasette-enrichments-llm

[![PyPI](https://img.shields.io/pypi/v/datasette-enrichments-llm.svg)](https://pypi.org/project/datasette-enrichments-llm/)
[![Changelog](https://img.shields.io/github/v/release/datasette/datasette-enrichments-llm?include_prereleases&label=changelog)](https://github.com/datasette/datasette-enrichments-llm/releases)
[![Tests](https://github.com/datasette/datasette-enrichments-llm/actions/workflows/test.yml/badge.svg)](https://github.com/datasette/datasette-enrichments-llm/actions/workflows/test.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/datasette/datasette-enrichments-llm/blob/main/LICENSE)

Enrich data by prompting LLMs

This is an **early alpha**.

## Installation

Install this plugin in the same environment as Datasette.
```bash
datasette install datasette-enrichments-llm
```
## Usage

The plugin will enable enrichments to be run against any [LLM](https://llm.datasette.io/) model that has an LLM plugin providing [asynchronous support](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#async-models) for that model.

Multi-modal models are supported via the `media_url` parameter.

API keys currently use the default LLM mechanism, probably best set using environment variables.

## Development

To set up this plugin locally, first checkout the code. Then create a new virtual environment:
```bash
cd datasette-enrichments-llm
python -m venv venv
source venv/bin/activate
```
Now install the dependencies and test dependencies:
```bash
pip install -e '.[test]'
```
To run the tests:
```bash
python -m pytest
```

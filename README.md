# TG services aggregator

TG services aggregator is a greenfield pipeline for turning noisy Telegram posts about services in Serbia into structured data.

It is designed for mostly Russian-language Telegram publics and groups. The system fetches posts, extracts provider and offer facts, removes obvious non-services, optionally uses an LLM for hard filtering and cleanup, and publishes clean outputs to Google Sheets, PostgreSQL, and DB-backed dashboard views.

## How It Works

- `n8n/` contains the repo-owned n8n workflow export and small workflow fixtures.
- `scripts/fetch/` fetches Telegram history with Telethon.
- `scripts/extract/` extracts contacts, prices, cities, service hints, providers, and offers.
- `scripts/llm/` runs the bounded post-merge LLM layer for product-row quality.
- `scripts/db/` contains PostgreSQL migrations and the DB publication helper.
- `tests/` contains targeted regression tests for the helper code and workflow JSON contracts.

Google Sheets is an operator-facing projection. PostgreSQL is the intended durable business store. The dashboard layer should read from PostgreSQL, not from Sheets or n8n internal state.

## Current Status

The core repo-owned pipeline exists: Telegram fetch, deterministic extraction and merge, LLM-assisted post-merge shaping, Sheets publication, PostgreSQL publication, provenance tables, and dashboard read views.

The project is not fully accepted yet. The public `Services` sheet still has quality blockers, and the next live LLM replay is blocked by OpenAI quota plus explicit cost approval. No paid OpenAI run should be started without an approved model, credential/project, maximum call or dollar budget, and stop condition.

## Setup

Use Python `>=3.12,<3.13` and Poetry:

```powershell
poetry install
```

Local Telegram helper runs need these environment variables:

- `TG_API_ID`
- `TG_API_HASH`
- `TG_SESSION_STRING`

Create a local Telegram session string with:

```powershell
poetry run python scripts\fetch\create_telethon_string_session.py
```

Run targeted tests with:

```powershell
poetry run pytest
```

Validate the n8n workflow export with the n8n import validator you use in your own environment.

## What Still Needs Work

- Fix the remaining public `Services` quality issues: wrong categories, unreadable details, and product-sale leakage.
- Add a stronger pre-LLM cost gate so duplicate or low-value rows do not reach paid LLM calls.
- Remove the hardcoded default LLM model and require an explicitly approved model before paid runs.
- Rerun the live public proof only after quota and cost approval are both clear.
- Keep runtime dumps, local evidence, secrets, and generated files out of git.

## Future Additions

- Scheduled runs after the manual proof path is stable.
- Better source management and source quality scoring.
- Operator dashboard screens on top of the PostgreSQL read views.
- Safer retry and continuation tooling for large Telegram source sets.
- More automated audits for visible public rows before publication.

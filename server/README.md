# Squirrel Service

Python/FastAPI service for 松鼠筑巢.

## Responsibilities

- SQLite as the source of truth for inventory, spaces, preferences, and chat history.
- Auto-generate `storage/inventory.md` after inventory mutations.
- Provide AI-facing service boundaries for natural-language ingestion, chat, recipe planning, and future image/STT flows.
- Maintain an embedded Chroma vector-store adapter for semantic search. If Chroma is not installed, the service keeps running with keyword fallback.

## Run With uv

```bash
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Important environment variables:

- `SQUIRREL_DATA_DIR`: default `../data`
- `SQUIRREL_STORAGE_DIR`: default `../storage`
- `AI_PROVIDER`: `openai`, `ollama`, `local`, or `mock`
- `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`

## Compatibility

`requirements.txt` is kept as a plain pip fallback, but `pyproject.toml` is the source of truth for uv.

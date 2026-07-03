# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

Squirrel / squirrel is a local-first smart home inventory manager. The repository is a small monorepo with three active parts:

- `server/`: Python 3.12 FastAPI backend. SQLite is the source of truth, inventory is mirrored to Markdown, and semantic search uses embedded Chroma when available with keyword fallback.
- `squirrel/`: React 19 + Vite + Tailwind web app. It talks to the backend through `/api/*` endpoints and falls back to local demo data when the backend is unreachable.
- `cli/`: Go 1.22 Cobra CLI that calls the FastAPI service for quick terminal inventory operations.

`docs/project-design.md` describes the intended product direction. Note that it mentions Next.js, but the current web implementation is Vite React.

## Common Commands

Run commands from the repository root unless noted.

### Monorepo convenience scripts

```bash
npm run server   # FastAPI dev server on :8000 via uv
npm run web      # Vite web dev server in squirrel/
npm run cli      # go run ./cli
npm run lint     # frontend TypeScript check
```

### Backend (`server/`)

```bash
cd server
uv sync                         # install Python deps from pyproject/uv.lock
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
uv run pytest                   # all backend tests
uv run pytest tests/test_parser.py
uv run pytest tests/test_parser.py::test_parse_single_item_with_location_and_quantity
uv run ruff check .
```

`requirements.txt` exists as a pip fallback, but `pyproject.toml` is the dependency source of truth for uv.

### Frontend (`squirrel/`)

```bash
cd squirrel
npm install
npm run dev
npm run build
npm run preview
npm run lint                    # tsc --noEmit
```

There is no frontend test script currently defined in `squirrel/package.json`.

### CLI (`cli/`)

```bash
go run ./cli --help
go run ./cli add "3袋螺蛳粉，放客厅箱子里"
go run ./cli list --status=danger
go run ./cli clear --expired
go run ./cli export
go test ./cli/...
go test -race ./cli/...
go test -cover ./cli/...
go build ./cli
```

The CLI defaults to `http://localhost:8000`. Override with `--api <url>` or `SQUIRREL_API_URL`.

### Docker

```bash
docker compose up
```

The compose file runs only the backend service and mounts `./data` and `./storage` for persistence.

## Backend Architecture

- `server/app/main.py` creates the FastAPI app, initializes the database, installs permissive CORS, and includes the API router.
- `server/app/api/routes.py` is the main API boundary under `/api`. It handles app state, CRUD for items, CLI ingestion, chat/recipe endpoints, Markdown export, and search. Mutating routes usually call `sync_inventory_markdown(...)` and update the vector store.
- `server/app/models/schemas.py` defines the Pydantic models shared by routes, persistence, and services. Field names intentionally mirror frontend TypeScript names such as `spaceId`, `remainingPct`, and `expireDate`.
- `server/app/db/sqlite.py` owns SQLite schema creation, seed data, row/model conversion, and state replacement. It stores inventory, spaces, chat messages, preferences, and onboarding metadata.
- `server/app/services/parser.py` contains the current rule-based natural-language inventory parser for Chinese lightning entry.
- `server/app/services/graph.py` builds a LangGraph intent router for ingest, expiry query, location query, recipe, and general chat flows.
- `server/app/services/ai.py` is a thin service facade over the graph.
- `server/app/services/markdown.py` renders and writes `storage/inventory.md` after inventory changes.
- `server/app/services/vector_store.py` wraps Chroma. Import or runtime failures disable Chroma and leave keyword search active.
- `server/app/core/config.py` reads `SQUIRREL_*` settings from `.env` plus `AI_PROVIDER`, `AI_BASE_URL`, `AI_API_KEY`, and `AI_MODEL` from the process environment.

Default persistence paths are `../data/squirrel.sqlite3`, `../data/chroma`, and `../storage/inventory.md` relative to `server/` execution.

## Frontend Architecture

- `squirrel/src/App.tsx` is the stateful shell. It loads `/api/state`, manages tab navigation, performs optimistic item updates, persists preferences/messages/state, and renders the four main views.
- `squirrel/src/api.ts` centralizes fetch wrappers for backend state and item operations. Frontend requests use relative `/api/*` paths, so dev/proxy or same-origin backend serving is expected.
- `squirrel/src/types.ts` mirrors backend Pydantic schemas and should stay aligned with `server/app/models/schemas.py`.
- `squirrel/src/data.ts` supplies demo fallback data used when the backend is unavailable.
- `squirrel/src/components/` contains feature views for onboarding, dashboard, assistant chat, inventory management, and settings.

When changing shared data shapes, update both `server/app/models/schemas.py` and `squirrel/src/types.ts`, then verify backend tests and frontend `npm run lint`.

## CLI Architecture

`cli/main.go` defines all Cobra commands in one file. Commands call the backend JSON API through a shared `request` helper and render inventory summaries to stdout. Supported commands currently include `add`, `list`, `clear --expired`, and `export`.

## Environment

Backend environment variables:

- `SQUIRREL_DATA_DIR` (default `../data`)
- `SQUIRREL_STORAGE_DIR` (default `../storage`)
- `AI_PROVIDER` (`openai`, `ollama`, `local`, or `mock` per README; current service behavior is graph/rule based)
- `AI_BASE_URL`
- `AI_API_KEY`
- `AI_MODEL`

Example files exist at `server/.env.example` and `squirrel/.env.example`.

## Repository Notes

- No existing `AGENTS.md`, Cursor rules, `.cursorrules`, or GitHub Copilot instructions were found when this file was created.
- `squirrel/node_modules/` is present locally; avoid treating files under it as source.
- Several generated design artifacts live under `stitch_logo/`; they are not part of the active app/runtime path.
# 🐿️ Squirrel — Smart Home Inventory Manager

> Be as meticulous as a squirrel about stocking up, but never forget where your "nuts" are again.

**English** | [中文](./README.zh-CN.md)

## Overview

Squirrel is a local-first, AI-powered home inventory manager. It helps you track what you have, where it's stored, and when it expires — so nothing goes to waste.

### Key Features

- **Natural Language Entry** — Just tell it what you bought: `"3 bags of螺蛳粉, put them in the living room box"`. AI parses and logs everything.
- **Smart Expiry Tracking** — Color-coded alerts: 🔴 expired, 🟡 expiring soon, ⚪ long-idle items.
- **Location Memory** — Never forget where you stored something again.
- **AI Chat Assistant** — Ask questions like "what vegetables do I have?" or "what can I cook with what's in the fridge?"
- **Markdown Sync** — Inventory auto-generates `inventory.md` for easy reading in Obsidian, Notion, or any text editor.
- **Multi-Interface** — Web UI, CLI, and API — use whatever fits your workflow.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12 + FastAPI |
| Database | SQLite (with Chroma vector DB for semantic search) |
| Frontend | React 19 + Vite + Tailwind CSS |
| CLI | Go 1.22 + Cobra |
| Deployment | Docker + Nginx reverse proxy |

## Quick Start

### Docker Compose (Recommended)

```bash
docker compose up --build
```

Open `http://localhost:5685` in your browser.

The compose file runs the backend, builds the frontend, and serves everything through Nginx on a single port.

### Development

#### Backend

```bash
cd server
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### Frontend

```bash
cd squirrel
npm install
npm run dev
```

#### CLI

```bash
go run ./cli --help
go run ./cli add "3 bags of chips, in the kitchen cabinet"
go run ./cli list --status=danger
```

## Configuration

### Environment Variables

Backend environment variables (set in `server/.env` or Docker):

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUIRREL_DATA_DIR` | `../data` | SQLite database directory |
| `SQUIRREL_STORAGE_DIR` | `../storage` | Markdown export directory |
| `AI_PROVIDER` | `mock` | AI provider: `openai`, `ollama`, `local`, `mock` |
| `AI_BASE_URL` | — | OpenAI-compatible API base URL |
| `AI_API_KEY` | — | API key |
| `AI_MODEL` | — | Model name (e.g. `gpt-4o-mini`) |

### AI Providers

Squirrel works with any OpenAI-compatible API:

- **OpenAI / Claude** — Set provider to `openai`, configure base URL and key.
- **Ollama (Local)** — Set provider to `ollama`, run a local model like Qwen or Llama3.
- **Mock** — Rule-based parser for testing without an AI service.

## Project Structure

```
Squirrel/
├── server/          # Python FastAPI backend
│   ├── app/
│   │   ├── api/     # API routes
│   │   ├── core/    # Configuration
│   │   ├── db/      # SQLite database
│   │   ├── models/  # Pydantic schemas
│   │   └── services/# AI, parser, markdown, vector store
│   └── tests/
├── squirrel/        # React frontend
│   ├── src/
│   │   ├── components/
│   │   ├── api.ts
│   │   └── types.ts
│   └── nginx.conf
├── cli/             # Go CLI
│   └── main.go
├── data/            # Runtime data (SQLite, Chroma)
├── storage/         # Markdown exports
└── docker-compose.yml
```

## API Endpoints

All endpoints are under `/api`:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/state` | Get full app state |
| `POST` | `/api/items` | Add inventory item |
| `PUT` | `/api/items/:id` | Update item |
| `DELETE` | `/api/items/:id` | Delete item |
| `POST` | `/api/chat` | Chat with AI assistant |
| `POST` | `/api/chat/confirm` | Confirm pending action |
| `GET` | `/api/search` | Search inventory |
| `GET` | `/api/export/markdown` | Export inventory as Markdown |

## License

MIT

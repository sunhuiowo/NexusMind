# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Personal AI Memory System** - A cross-platform personal knowledge memory that transforms bookmarks from multiple platforms into a conversational private knowledge base.

- **Frontend**: React 18 + TypeScript + Vite + Tailwind CSS + Zustand + React Query
- **Backend**: FastAPI + Python 3.10+
- **Storage**: FAISS (vector search) + SQLite (metadata)
- **LLM Integration**: OpenAI, Anthropic, or Ollama

## Common Commands

```bash
# Quick start (recommended)
./start.sh

# Or use Makefile
make dev              # Start both frontend and backend
make install          # Install all dependencies
make test             # Run backend tests
make sync-all         # Trigger full platform sync
make docker-up        # Start with Docker Compose
make docker-down      # Stop Docker services

# Manual start
cd backend && python main.py serve      # Backend on port 8000
cd frontend && npm run dev              # Frontend on port 5173

# CLI commands
python main.py query "your question"    # Query memories
python main.py sync --full              # Full sync
python main.py stats                    # Show statistics
python main.py interactive              # Interactive mode
```

## Architecture

```
Frontend (React) → FastAPI Backend → Agents → Storage/Platforms
     │                 │              │
     │                 ├── Knowledge Agent (intent recognition + Q&A)
     │                 ├── Collector Agent (data fetch + parse + store)
     │                 └── Memory Agent (relationships + importance)
     │
     └── Vite proxy: /api → localhost:8000
```

### Backend Modules

- **agents/** - Three AI agents (knowledge, collector, memory)
- **platforms/** - 8 platform connectors (YouTube, Twitter, GitHub, Pocket, Bilibili, WeChat, Douyin, Xiaohongshu)
- **parsers/** - Content parsers (text, audio/Whisper, vision/Qwen2-VL, video, PDF)
- **memory/** - FAISS + SQLite dual storage layer
- **tools/** - MCP tools, embedder, memory builder
- **auth/** - OAuth 2.0 + AES-256 token encryption
- **config.py** - Runtime config with hot-reload support

### Frontend Structure

- **src/pages/** - Chat, Library, Platforms, Sync, Settings
- **src/components/** - Reusable UI components
- **src/store/** - Zustand state management
- **src/api/** - API client and TypeScript types

## Key API Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /query` | Query memories with natural language |
| `GET /memories` | List memories with pagination/filters |
| `GET /memories/stats` | Get memory statistics |
| `POST /sync` | Trigger platform sync |
| `GET /auth/status` | Check platform connection status |
| `GET/POST /config` | Get/update runtime configuration |

## Development Principles

1. **Memory fields are append-only** - maintain backward compatibility in `memory_schema.py`
2. **Embeddings use summary only** - never use raw_content for embeddings
3. **Agents communicate via MCP tools** - not direct function calls
4. **QueryResult must return 5 required fields** - platform, title, summary, bookmarked_at, url
5. **Cookie-based platforms** - return `needs_reauth` instead of throwing exceptions
6. **Config hot-reloads at runtime** - use `POST /config` for runtime changes

## Required Environment Variables

```bash
# LLM (required)
LLM_API_KEY=sk-...

# Encryption (required)
TOKEN_MASTER_PASSWORD=your-secure-password

# Platform credentials (at least one)
GITHUB_PAT=ghp_...
YOUTUBE_CLIENT_ID=...
POCKET_CONSUMER_KEY=...
```

## Testing

```bash
cd backend && pytest tests/test_phase1.py -v
```

## Performance Optimization Features

The system includes several performance optimizations for sync operations:

1. **Batch LLM calls** - `_generate_all_in_one()` in `memory_builder.py` combines summary, tags, and importance generation into a single LLM call (3x speedup)
2. **Pre-filtering** - collector checks for existing memories before LLM processing to avoid wasted API calls
3. **Parallel processing** - uses ThreadPoolExecutor for parallel content parsing
4. **Batch embedding** - `embed_batch()` generates vectors in batches
5. **Batch storage** - `add_batch()` commits SQLite and FAISS in bulk

## Scripts

```bash
./start.sh    # Start frontend + backend
./stop.sh     # Stop all services (vite, python, uvicorn)
```

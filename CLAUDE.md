# Git strategy - must follow

Every commit should always have descriptions of what changes are being made, why we are making those changes, core decisions etc.

# M3 Build Instructions

Read `docs/PRODUCT_SPEC.md` for full product context. This file tells you how to build Phase 1.

## What We're Building (Phase 1)

A self-hosted personal knowledge OS. User shares things via API/Telegram. Claude API processes and organizes them into a wiki. User browses wiki, searches, and chats with it via web UI.

## Tech Stack

- **Server**: Python 3.12+ / FastAPI / async everywhere
- **DB**: PostgreSQL 16 + pgvector (via SQLAlchemy async + Alembic)
- **Files**: MinIO (S3-compatible)
- **Queue**: Redis + ARQ (async task queue, NOT Celery)
- **LLM**: Anthropic Claude API (claude-sonnet-4-20250514) - we should realistically allow user to use their existing pro or max subscription
- **Client**: React 19 + Vite + Tailwind
- **Deploy**: Docker Compose

## Project Structure

Already scaffolded. Key locations:
- `server/m3/core/engines/base.py` — CompilationEngine interface (already written)
- `server/m3/core/engines/basic.py` — BasicEngine (to build)
- `server/m3/core/engines/loader.py` — Engine loader from config
- `server/m3/core/compiler.py` — Processing pipeline orchestrator
- `server/m3/core/llm.py` — LLM provider abstraction
- `server/m3/core/search.py` — Semantic + keyword search
- `server/m3/api/` — FastAPI route modules
- `server/m3/storage/` — Database, files, cache
- `server/m3/capture/telegram.py` — Telegram bot
- `server/m3/workers/tasks.py` — ARQ background tasks
- `client/` — React web app

## Build Order

### Step 1: Infrastructure
- docker-compose.yml (PostgreSQL pgvector, Redis, MinIO, Caddy)
- Dockerfile (Python server)
- pyproject.toml (fastapi, sqlalchemy[asyncio], asyncpg, anthropic, arq, minio, python-telegram-bot, trafilatura, pdfplumber, pydantic-settings)
- config.py (Pydantic Settings loading from config.yml + env vars)
- storage/database.py (async SQLAlchemy engine + session)
- storage/models.py (ORM models for raw_items, wiki_pages, wiki_links, wiki_schema, changelog)
- storage/files.py (MinIO wrapper)
- storage/cache.py (Redis wrapper)
- Alembic setup + initial migration
- main.py (FastAPI app with lifespan, CORS, auth middleware)
- Verify: docker compose up, GET /api/v1/status returns 200

### Step 2: Ingest API
- schemas/api.py (Pydantic models for requests/responses)
- api/ingest.py: POST /api/v1/ingest (text, file upload, URL, with optional tags/project)
- Store original in MinIO, create raw_items record, queue processing task
- GET /api/v1/ingest (list items, filter by status)
- Verify: can upload text and files, items appear as 'pending'

### Step 3: LLM Provider
- core/llm.py: Abstract LLMProvider + AnthropicProvider
- Methods: complete(), complete_stream(), embed()
- Support text, image, and audio input (Claude handles all)
- Load from config
- Verify: can send prompt, get response

### Step 4: Compilation Engine
- core/engines/basic.py: BasicEngine implementing CompilationEngine
  - classify(): send content + wiki context to LLM, get tags/project/type
  - compile(): send classified content + related pages, get wiki page updates
  - synthesize(): send wiki overview, get cross-links and insights
- core/engines/loader.py: load engine by name or path from config
- Verify: can classify a text snippet

### Step 5: Processing Pipeline
- core/compiler.py: Orchestrates full pipeline
  - Load raw item → extract content → classify → find related pages → compile → write wiki → update links → log changelog
- workers/tasks.py: ARQ tasks (process_item, compile_pass, deep_compile)
- Wire ARQ worker as separate Docker service
- Scheduled compile via ARQ cron
- Verify: upload text → processed → wiki page created

### Step 6: Wiki API
- api/wiki.py: GET pages, GET page by id, GET search, GET projects, GET tags, GET graph, GET changelog
- core/search.py: hybrid semantic + keyword search
- Graph endpoint returns {nodes, edges} for D3
- Verify: can browse pages, search works

### Step 7: Chat API
- api/chat.py: POST /api/v1/chat (streaming SSE)
- Flow: embed question → semantic search wiki → build context → stream LLM response
- Include citations to wiki pages
- Verify: can ask questions, get wiki-grounded answers

### Step 8: Telegram Bot
- capture/telegram.py: using python-telegram-bot (async)
- Handle text, photo, document, audio, voice, video messages
- On message: call ingest internally, reply with confirmation
- Commands: /status, /search, /ask
- Verify: forward message to bot, it appears in M3

### Step 9: Web Client
- React + Vite + Tailwind setup
- Views: Inbox (raw items list + quick capture), Wiki (sidebar + page view), Chat (streaming), Settings
- API client with typed fetch wrappers
- SSE handling for chat streaming
- PWA manifest
- Verify: full flow through web UI

### Step 10: Deployment
- Final docker-compose with all services
- Multi-stage Dockerfile (build client, serve from FastAPI static)
- Caddyfile for TLS
- scripts/setup.sh (first-time wizard)
- Verify: git clone + docker compose up works from scratch

## Database Schema

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE raw_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_text TEXT,
    content_type VARCHAR(50),
    source_channel VARCHAR(50),
    source_metadata JSONB DEFAULT '{}',
    file_path VARCHAR(500),
    user_tags TEXT[] DEFAULT '{}',
    user_project VARCHAR(200),
    status VARCHAR(20) DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

CREATE TABLE wiki_pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(500) NOT NULL,
    content TEXT NOT NULL,
    category VARCHAR(200),
    page_type VARCHAR(100),
    tags TEXT[] DEFAULT '{}',
    confidence FLOAT DEFAULT 0.5,
    embedding VECTOR(1024),
    source_items UUID[] DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE wiki_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_page_id UUID REFERENCES wiki_pages(id) ON DELETE CASCADE,
    target_page_id UUID REFERENCES wiki_pages(id) ON DELETE CASCADE,
    link_type VARCHAR(50) DEFAULT 'references',
    weight FLOAT DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_page_id, target_page_id, link_type)
);

CREATE TABLE wiki_schema (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE changelog (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action VARCHAR(50),
    page_id UUID REFERENCES wiki_pages(id) ON DELETE SET NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_wiki_pages_fts ON wiki_pages USING gin(to_tsvector('english', title || ' ' || content));
CREATE INDEX idx_wiki_pages_embedding ON wiki_pages USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_raw_items_status ON raw_items(status);
CREATE INDEX idx_wiki_pages_category ON wiki_pages(category);
CREATE INDEX idx_wiki_pages_tags ON wiki_pages USING gin(tags);
```

## Key Notes

- Embedding dimension: check Anthropic's current embedding model dimensions. If Anthropic doesn't offer embeddings, use voyage-3 or OpenAI text-embedding-3-small (1536 dim) and adjust VECTOR() accordingly.
- Streaming chat: use FastAPI StreamingResponse with SSE. Each chunk: `data: {"text": "..."}\n\n`. Done: `data: [DONE]\n\n`.
- Wiki index: a special wiki page the LLM maintains as a summary of all pages. Read first during classify/compile.
- Auth: simple API key in Authorization header. Single user, no complexity.
- MinIO bucket: auto-create on startup if not exists.
- Run alembic migrations on server startup.

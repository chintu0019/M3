# M3 — Me, Myself, Mine
## Personal Knowledge Operating System
### Product Specification — Open Core, Bring-Your-Own-Agent

---

## What M3 Is

An open-source, self-hosted personal knowledge OS. You forward things from
anywhere in your life — meeting notes, voice memos, articles, receipts — and
an LLM organizes them into an entity-centric knowledge graph. No prescribed
structure. The system learns how you think and organizes accordingly.

You view the result as an interactive force-directed graph, click any node
for the rendered wiki page for that entity, and chat with your knowledge
base. Responses cite the underlying entities and raw documents.

**Open-source. Self-hosted. Single-user. Bring-your-own-agent.**

---

## Philosophy

### No Prescribed Structure

M3 does not ship with a predefined wiki layout. Categories, entity types,
fact types, and relationship types all emerge from what you capture. Early
on, the graph might be a flat collection of people and projects. Over time,
the LLM notices clusters and the entity-link graph thickens around the
topics that actually matter to you.

The user can guide ("treat these items as part of project X") but guidance
is optional. The default is: forward things, the LLM figures it out.

### Bring Your Own Agent

M3 ships zero inference. The user picks how the LLM runs:

- **Local agent (default).** M3 shells out to a CLI you already have logged
  in (`claude`, `codex`, `gemini`). No API key, no extra subscription —
  M3 reuses the user's existing login.
- **API provider.** Anthropic, OpenRouter, Groq, Together, MiniMax, Ollama,
  or anything OpenAI-compatible. Paste a key, switch in one click.

If nothing is configured, the server still boots; the UI shows a "pick one"
prompt and disables chat until the user picks. This is the BYO contract:
M3 never auto-provisions inference for you.

### What Flows In

Anything you might want to remember, reference, or reason about: meeting
notes, decisions, articles, receipts, voice memos, screenshots, URLs,
contacts, half-formed ideas. The only rule: if you might want to find it
later or connect it to something else, share it with M3.

---

## Open-Core Model

M3 is MIT-licensed with an optional proprietary intelligence layer.

### What's Open (MIT, public repo)

Everything needed to run a fully functional M3 instance:

- FastAPI server, database schema, storage layer, task queue
- Direct-upload + Telegram capture
- React client (Documents + Workspace) with the entity graph + chat
- LLM provider abstraction (local agent, Anthropic, OpenAI-compatible)
- A **basic compilation engine** that ingests, extracts entities + facts,
  renders entity wiki pages, surfaces insights, and consolidates types.
  Functional, not exceptional.

The basic engine is the Honda Civic. It gets you there.

### What's Private (never in the repo)

The intelligence that makes M3 genuinely good:

- **Premium prompt chains** for extraction, rendering, type consolidation,
  and insight detection.
- **Pipeline orchestration** — the specific call structure, what context
  threads between steps, how the engine decides when to merge entities or
  split a topic.
- **Schema evolution strategy** — how the engine reorganizes the wiki as
  it grows.

These live in a private repo and load at runtime via
`processing.engine_path` in `config.yml`.

### How the Abstraction Works

```python
# server/m3/core/engines/base.py — public
class CompilationEngine(ABC):
    capabilities: EngineCapabilities = EngineCapabilities()

    @abstractmethod
    async def extract(self, content, content_type, user_notes=None) -> ExtractionResult: ...
    async def render_entity(self, entity, facts, related=None) -> RenderedPage: ...
    async def find_insights(self, touched_entities, neighborhood, recent_facts) -> list[Insight]: ...
    async def consolidate_types(self, entity_types, fact_types, fact_roles) -> dict: ...

# server/m3/core/engines/basic.py — public, ships with M3
class BasicEngine(CompilationEngine): ...

# m3-engine-pro/engine.py — private, never published
class ProEngine(CompilationEngine): ...
```

```yaml
# config.yml
processing:
  engine: basic                     # ships with M3
  # engine_path: /opt/m3-engine-pro/engine.py   # for ProEngine or custom
```

The interface is documented; users can build their own engine. The ProEngine
is never distributed.

---

## Core Architecture

```
[Capture]                  [M3 Server]                     [Web Client]

Direct upload ──┐          ┌──────────────────────┐       ┌───────────────┐
Telegram bot ───┤──HTTPS──▶│  FastAPI             │       │ Documents     │
                │          │                      │◀─────▶│   raw items   │
                │          │  ┌────────────────┐  │       │               │
                │          │  │ LLM provider   │  │       │ Workspace     │
                │          │  │ • local_agent  │  │       │   • graph     │
                │          │  │ • anthropic    │  │       │   • chat      │
                │          │  │ • openai-compat│  │       │   • detail    │
                │          │  └────────────────┘  │       │                │
                │          │                      │       │ Settings      │
                │          │  ┌────────────────┐  │       │   • agents    │
                │          │  │ Compilation    │  │       │   • providers │
                │          │  │ engine         │  │       │   • theme     │
                │          │  └────────────────┘  │       └───────────────┘
                │          │                      │
                │          │  ┌────────────────┐  │
                │          │  │ ARQ workers    │  │
                │          │  │ (background)   │  │
                │          │  └────────────────┘  │
                │          └─────────┬────────────┘
                │                    │
                │       ┌────────────┼────────────┐
                │       ▼            ▼            ▼
                │ ┌──────────┐ ┌──────────┐ ┌──────────┐
                │ │PostgreSQL│ │  MinIO   │ │  Redis   │
                │ │+pgvector │ │ (files,  │ │ (queue,  │
                │ │+pg_trgm  │ │  audio)  │ │  cache)  │
                │ └──────────┘ └──────────┘ └──────────┘
```

The deployment is a single `docker compose up -d`. `scripts/setup.sh`
probes for free host-side ports and writes them to `.env` so the stack
runs cleanly even on a machine where `:80`, `:5432`, or `:9000` are taken.

---

## 1. Capture Layer

### What's Built

| Channel              | Mechanism                                    | Status            |
|----------------------|----------------------------------------------|-------------------|
| Direct upload (UI)   | Text input, file upload, URL paste           | Built             |
| Telegram bot         | Forward messages/media to bot                | Built (opt-in)    |

### Aspirational

WhatsApp Business, email forwarding, browser extension, OS share targets,
Slack — none of these are implemented. They're plausible plugins under
the abstraction below, not promises.

### Capture UX

Minimal: drop content, optionally tag/project it, send. The LLM handles
classification.

### Raw Storage

Every captured item is stored verbatim, forever. The original audio, the
original screenshot, the original PDF. Processing creates entities + facts
alongside the raw item, never replacing it. Users can always go back to the
source.

---

## 2. LLM Layer

### Provider Abstraction

`LLMProvider` advertises capability flags so the engine picks the shortest
path:

```python
class LLMProvider(ABC):
    supports_tools: bool = False
    supports_vision: bool = False
    supports_audio: bool = False

    async def complete(...) -> str: ...
    async def complete_stream(...) -> AsyncIterator[str]: ...
    async def complete_tool(...) -> ToolResult: ...      # optional
```

### Implementations

- **`LocalAgentProvider`** — shells out to a CLI (`claude` by default).
  Reuses the user's existing login. `supports_tools=False`, so the engine
  uses the JSON-fallback path. The default provider on a fresh install.
- **`AnthropicProvider`** — full tool use, vision, audio.
- **`OpenAICompatibleProvider`** — OpenRouter, Groq, Together, MiniMax,
  Ollama, OpenAI itself. Tool/vision flags configurable per provider.
- **`UnconfiguredProvider`** — placeholder when nothing is wired up.
  Every call raises `RuntimeError("No LLM is configured ... Open Settings
  and pick an installed agent or add an API key.")`. The server boots
  cleanly with this in place; the UI surfaces it as a "pick an agent" CTA.

### Capability-Aware Engines

`EngineCapabilities` lets engines pick a one-call tool-use path with rich
providers and fall back to two-call JSON-repair with limited ones.
BasicEngine implements both:

- **Capable path** (`supports_tools=True`): one tool call returns entities
  + facts + relationships in a schema-validated payload, no character cap,
  multimodal blocks consumed directly.
- **Fallback path**: short prompt + JSON-repair retry; relationships and
  insights are deliberate no-ops because local models hallucinate them.

The user-visible cost: switching from `local_agent` (or any non-tool
provider) to a capable one materially improves output quality.

### Voice / Image / PDF

- Audio: passed straight to the provider when `supports_audio=True`.
  Otherwise dropped with a clear marker ("\[audio omitted\]") so the
  caller knows.
- Images / receipts / screenshots: same pattern via `supports_vision`.
- PDF / DOCX: text extracted locally before reaching the LLM.
- URLs: Trafilatura content extraction locally, then text path.

---

## 3. Knowledge Layer

### Entity-Centric Wiki

Phase 7 of the wiki redesign (see `docs/WIKI_REDESIGN.md`) collapsed M3 onto
an entity graph. There is no document-mode anymore.

Pipeline per ingest:

```
raw_item
   │
   ▼
extract()  → entities + atomic facts + (optional) semantic relationships
   │
   ▼
entity_resolver  → exact/alias → trigram → embedding → LLM disambiguation
                  type-scoped, auto-merges at ≥0.88 similarity
   │
   ▼
persist          entity_facts, entity_fact_links, entity_links (co-occurrence
                 + engine-proposed), entity.page_dirty=true
   │
   ▼
find_insights()  2-hop neighborhood walk; insights deduped by
                 (insight_type, sorted(related_entity_ids))
   │
   ▼
(background) render_entity()  →  entity.page_content (markdown with
                                  [^<item_id>] citations to raw items)
```

Entity / fact / role types are organic — `entity_types`, `fact_types`,
`fact_roles` are dim tables with `usage_count` and `merged_into`. A daily
`consolidate_types()` pass merges near-duplicates ("individual" → "person").

### Storage

PostgreSQL (with `pgvector` and `pg_trgm`) is the source of truth for
entities, facts, links, and embeddings. MinIO holds raw files and any
generated assets. Redis is the ARQ queue for background work.

There is **no markdown-on-disk dual storage**. Export is a future feature.

### Schema (excerpt)

```sql
entities         (id, canonical_name, entity_type, aliases, description,
                  page_content, page_overview, page_dirty,
                  facts_since_render, embedding, ...)
entity_facts     (id, content, fact_type, fact_time, source_quote, ...)
entity_fact_links(fact_id, entity_id, role)
entity_links     (source_entity_id, target_entity_id, link_type, weight)
insights         (id, insight_type, title, description,
                  related_entity_ids, related_item_ids, status, ...)
raw_items        (id, content_text, content_type, source_channel, file_path, ...)
```

---

## 4. Graph Visualization

The Workspace view uses **react-force-graph-2d**:

- Nodes: entities (color by entity type), insights (yellow), threads (blue).
- Edges: `entity_links`, weighted by co-occurrence + semantic strength.
- Auto-sizes via `ResizeObserver` — fits any viewport from a phone to a
  desktop monitor.
- Drag-to-pin, scroll-zoom, click-to-detail.
- Labels appear above a zoom threshold; hover/click anywhere shows the
  rendered entity page in a side card without leaving the graph.

The earlier hand-rolled D3 + canvas physics engine (700+ lines, 1600×1100
hardcoded dimensions) was retired.

---

## 5. Chat

`ChatRail` lives inside the Workspace as a side panel (or a bottom sheet on
mobile). It posts to `/api/v1/chat`, which:

1. Embeds the question.
2. Hybrid-searches `entities` over `embedding` + FTS on
   `canonical_name | aliases | description | page_overview`.
3. Sends the top-k entity pages + question to the active LLM.
4. Streams the response with `[[Entity Name]]` citations resolved against
   `canonical_name` and aliases. Cited entities surface as chips in the rail
   and focus the corresponding graph node when clicked.

If no agent is configured, the chat input is replaced with a "Pick one in
Settings" CTA. The graph still loads.

---

## 6. Insights

`find_insights()` runs after every entity-mode ingest, scoped to the 2-hop
neighborhood of touched entities. Categories: `stale`, `contradiction`,
`connection`, `orphan`, `suggestion`, `pattern`, `person`.

Insights surface inline in the entity detail card on the Workspace graph.
There is no separate `/insights` route anymore — insights live next to the
entities they reference.

---

## 7. Client

A single React app (Vite + Tailwind), served as static assets by the same
FastAPI process in production.

### Two Sections

- **Documents** — every raw item, with capture form, search, sort, and
  bulk retry / delete. Detail page shows extracted content, processing
  timeline, error state, notes, and download link.
- **Workspace** — entity graph + chat in one screen. Click a node, see the
  rendered entity page in a side card. Cited entities in chat focus the
  corresponding node.

A gear icon in the nav opens **Settings**, which has:

- API connection (M3 API key)
- "Use my installed AI agent" — auto-detected via `GET /api/v1/settings/agents`
- Provider list with presets (MiniMax, OpenRouter, Groq, Together, Ollama,
  Anthropic), add/edit/delete/switch
- Theme picker
- Self-context toggle

### Aspirational

PWA install + share target, Tauri desktop wrapper, iOS Shortcuts ingest —
not implemented. The current client is a single browser SPA.

---

## 8. Configuration

Layered: defaults → `config.yml` → environment variables. Env vars use the
`M3_` prefix with `__` for nesting.

```yaml
# config.yml (excerpt)
server:
  host: 0.0.0.0
  port: 8000

database:
  url: postgresql+asyncpg://m3:m3dev@postgres:5432/m3

storage:
  endpoint: minio:9000
  access_key: minioadmin                  # change for production
  secret_key: minioadmin                  # change for production
  bucket: m3-data

llm:
  default_provider: local_agent
  providers:
    local_agent:
      type: local_agent
      command: claude
      args: ["-p"]
      model: claude-code
    claude:
      type: anthropic
      api_key: ""                         # via ANTHROPIC_API_KEY
      model: claude-sonnet-4-20250514

processing:
  engine: basic
  # engine_path: /opt/m3-engine-pro/engine.py

capture:
  telegram:
    enabled: false
    bot_token: ""                         # via TELEGRAM_BOT_TOKEN

auth:
  api_key: ""                             # via M3_API_KEY
```

```bash
# .env (excerpt — scripts/setup.sh fills these in)
M3_API_KEY=...                            # generated by setup.sh
ANTHROPIC_API_KEY=
TELEGRAM_BOT_TOKEN=

# Host port pinning -- set by setup.sh after probing for free ports.
M3_HTTP_PORT=80
M3_HTTPS_PORT=443
M3_API_PORT=8000
M3_POSTGRES_PORT=5432
M3_REDIS_PORT=6380
M3_MINIO_PORT=9000
M3_MINIO_CONSOLE_PORT=9001
```

Any nested config field is overridable via env:
`M3_LLM__DEFAULT_PROVIDER=anthropic`,
`M3_CAPTURE__TELEGRAM__ENABLED=true`, etc.

### Deployment Options

```bash
# Home server / VPS — recommended
git clone https://github.com/chintu0019/m3.git
cd m3
./scripts/setup.sh

# Without setup.sh (manual)
cp .env.example .env && cp config.example.yml config.yml
docker compose up -d --build
```

Caddy auto-provisions Let's Encrypt for the public domain you set in
`M3_DOMAIN`. For local-only use, the default `localhost` is fine.

### Minimum Server Requirements

Without local inference: 2 CPU cores, 4 GB RAM, 20 GB disk. Costs roughly
$5–10/month on a small VPS plus whatever your LLM provider charges (zero if
you're using a local agent on the same box and the agent's subscription is
already paid).

---

## 9. Security & Privacy

- **Single-user only.** No multi-tenancy.
- **Auth.** API key required on every request; key generated by `setup.sh`.
- **TLS.** Caddy auto-provisions Let's Encrypt for the configured domain.
- **MinIO defaults are insecure** (`minioadmin:minioadmin`). Override
  `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY` in `.env` before exposing the
  console publicly.
- **LLM privacy.** Only the configured provider sees your content. With the
  local agent, content reaches the user's CLI process and the upstream
  service that CLI talks to (e.g. Anthropic for Claude Code) — same as if
  the user ran the CLI by hand.
- **No telemetry.** Zero analytics, zero tracking, zero phone-home. Open
  source means auditable.
- **Storage on disk.** Use encrypted disks; M3 doesn't add disk encryption.
- **Backup / export.** Not built yet. The data is in PostgreSQL and MinIO,
  backed up like any other docker-compose stack.

### Known security debt

- M3 API key is held in `localStorage` on the client; XSS would exfiltrate
  it. A future cookie-based session is the right fix.
- Rate limiting is absent.

---

## 10. Roadmap

### Done

- FastAPI server + PostgreSQL + pgvector + pg_trgm + MinIO + Redis stack
- Universal ingest API
- Direct upload + Telegram capture
- LLM provider abstraction (anthropic, openai_compatible, local_agent)
- Capability-aware compilation pipeline (entities, facts, relationships,
  insights, type consolidation)
- Entity resolver (exact / trigram / embedding / LLM)
- Background renderer + insight engine + type consolidator
- Two-section React client (Documents + Workspace)
- Force-directed graph (react-force-graph-2d)
- Entity-based hybrid retrieval chat with `[[Entity Name]]` citations
- Auto-port discovery in `setup.sh` + docker-compose
- Graceful boot when no LLM is configured (`UnconfiguredProvider` + UI
  empty state)

### Near term

- Better streaming for `LocalAgentProvider` (parse `claude --output-format
  stream-json` instead of buffering CLI stdout)
- Bulk export endpoint (markdown bundle of all entity pages + raw item refs)
- Chat error / reconnect UX
- README-honest capture: drop the WhatsApp/email/screenshots
  promises until they ship

### Aspirational

- WhatsApp Business and email-forward capture
- Browser extension + PWA share target
- Tauri desktop wrapper
- MCP server exposing M3's knowledge base so external agents (Claude Code
  etc.) can search M3 from outside the UI
- Plugin marketplace for capture / processing / view extensions

---

## What M3 Is NOT

- **Not a team tool.** One instance, one person.
- **Not a note-taking app.** You don't write in M3; you forward into M3.
- **Not a project manager.** It's the thinking layer above your PM tools.
- **Not cloud-hosted SaaS.** Your server, your data, your rules.
- **Not locked to any LLM.** Swap providers in one click.
- **Not a rigid schema.** Categories emerge from your content.

---

## Name

**M3** — interpretations:

- **Me, Myself, Mine** — ownership and privacy
- **My Mind Map** — what it visualizes
- **Memory, Meaning, Map** — what it builds

---

## Comparable Projects

| Project          | How M3 Differs                                                              |
|------------------|------------------------------------------------------------------------------|
| Obsidian         | M3 writes the wiki for you; Obsidian is manual.                              |
| Notion           | M3 is self-hosted and single-user. Notion is cloud and team-first.           |
| Mem.ai           | M3 is open-source and self-hosted. Mem is proprietary SaaS.                  |
| Khoj             | Closest: a personal AI assistant. M3 builds an entity graph + insights pass. |
| NotebookLM       | Stateless RAG. M3 builds compounding knowledge.                              |

### Open-Core Precedents

| Project   | Open                                       | Proprietary                              |
|-----------|--------------------------------------------|------------------------------------------|
| GitLab    | Core platform (MIT)                        | Premium features                         |
| Supabase  | Database / auth / storage (Apache 2.0)     | Managed cloud, enterprise                |
| Sentry    | Error tracking platform (BSL)              | Hosted service                           |
| **M3**    | Platform, client, basic engine (MIT)       | ProEngine (private compilation engine)   |

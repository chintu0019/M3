# M3 — Me, Myself, Mine
## Personal Knowledge Operating System
### Product Specification — Tauri + Local-First + BYO Agent

---

## What M3 Is

A local-first personal knowledge OS. You forward things from your life —
notes, voice memos, articles, receipts — and an LLM extracts entities and
atomic facts into a plain-markdown brain at `~/brain/`. You chat with the
result; the agent searches, opens entities, and cites the underlying items.

The whole thing ships as a single Tauri `.app`: Rust shell, bundled Python
backend, React client, sqlite-vec for embeddings. No docker, no PostgreSQL,
no cloud. Your brain is a folder of markdown files on your disk.

**Open-source. Local-first. Single-user. Bring-your-own-agent.**

---

## Philosophy

### No Prescribed Structure

Categories, entity types, fact types, and relationship types all emerge from
what you capture. Early on, the brain might be a flat collection of people
and projects. Over time, the LLM notices clusters and the entity graph
thickens around topics that actually matter to you.

The user can guide ("treat these items as part of project X") but guidance
is optional. The default is: forward things, the LLM figures it out.

### Bring Your Own Agent

M3 ships zero inference. The user picks how the LLM runs:

- **Local agent (the friendliest path).** M3 shells out to whichever AI CLI
  the user already has logged in: `claude`, `codex`, `gemini`, `aider`,
  `mods`, `llm`, or a fully custom command. Reuses the user's existing
  subscription. No M3-managed key.
- **Anthropic API.** Paste `sk-ant-...`, switch in one click. Best quality
  with native tool use.
- **Ollama.** Point at a local instance for fully offline inference.

If nothing is configured, the server still boots; the UI shows a "pick one"
prompt in Settings and disables chat until the user picks. This is the BYO
contract: M3 never auto-provisions inference for you.

### Local-First, Not Cloud-Hosted

Your data lives on your machine, in plaintext markdown, queryable with
`grep`. No multi-tenant SaaS. No "self-hosted" backend you have to admin —
the .app manages its own venv, runs its own server on loopback, and updates
itself in place.

### What Flows In

Anything you might want to remember, reference, or reason about: meeting
notes, decisions, articles, receipts, voice memos, screenshots, URLs, ideas.
Today the practical capture surface is **direct upload** (text + files) and
the **Telegram bot**; other channels are future work (see Roadmap).

---

## Open-Core Model

M3 is MIT-licensed with an optional proprietary intelligence layer.

### What's Open (MIT, this repo)

Everything needed to run a fully functional M3 instance:

- Tauri shell (Rust), bundled Python wheel runtime, React client.
- FastAPI server, sqlite-vec embeddings, FTS5 search, brain on disk.
- Direct-upload + Telegram capture.
- LLM provider abstraction (anthropic, openai_compatible, ollama,
  local_agent, unconfigured).
- A **basic compilation engine**: ingests, extracts entities + atomic facts,
  resolves entities, builds an entity graph, runs the agent loop. Works
  fine, not exceptional.

### What's Private (separate repo, never published)

The intelligence layer that elevates the basic engine: premium prompt
chains for extraction / rendering / type consolidation / insight detection;
the orchestration logic that decides when to merge entities or split a
topic; the schema-evolution strategy. Loaded at runtime via a pluggable
interface — see `server/m3/core/extract.py` for the public extraction
contract; the private engine implements the same contract behind the scenes.

The basic engine is the Honda Civic. It gets you there. The private engine
is the "feels-like-magic" delta.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         M3.app                              │
│                                                             │
│  ┌─────────────────┐    ┌──────────────────────────────┐   │
│  │  Tauri shell    │    │  React client (bundled)      │   │
│  │  (Rust)         │    │                              │   │
│  │                 │    │  Search / Chat / Cluster /   │   │
│  │  • Window       │    │  Self / Entities / Open Qs / │   │
│  │  • Auto-update  │◀──▶│  Settings                    │   │
│  │  • Manages      │    │                              │   │
│  │    private venv │    │  + Ingest drawer             │   │
│  └────────┬────────┘    └──────────────────────────────┘   │
│           │ spawns                                          │
│           ▼                                                 │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  m3 Python backend (bundled wheel + private venv)   │  │
│  │                                                       │  │
│  │  FastAPI on 127.0.0.1:7007                           │  │
│  │                                                       │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │  │
│  │  │ Ingest       │  │ Agent loop   │  │ Cluster    │  │  │
│  │  │ extract +    │  │ (chat with   │  │ retrieve + │  │  │
│  │  │ resolve      │  │  tools)      │  │ neighbors  │  │  │
│  │  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘  │  │
│  │         │                 │                │          │  │
│  │         ▼                 ▼                ▼          │  │
│  │  ┌────────────────────────────────────────────────┐   │  │
│  │  │ LLM provider                                   │   │  │
│  │  │ • LocalAgentProvider (any installed CLI)       │   │  │
│  │  │ • AnthropicProvider                            │   │  │
│  │  │ • OllamaProvider                               │   │  │
│  │  │ • UnconfiguredProvider (boot-clean fallback)   │   │  │
│  │  └────────────────────────────────────────────────┘   │  │
│  └──────────────┬────────────────────────────────────────┘  │
│                 │                                            │
└─────────────────┼────────────────────────────────────────────┘
                  │
                  ▼
       ┌───────────────────────┐      ┌────────────────────┐
       │  ~/brain/             │      │  ~/.config/m3/     │
       │  • items/  (markdown) │      │  • config.yml      │
       │  • entities/          │      │    (chmod 600)     │
       │  • self.md            │      └────────────────────┘
       │  • chats/             │
       │  • _index/            │
       │    • items.sqlite     │
       │      (FTS5 + vec0)    │
       └───────────────────────┘
```

The whole stack is loopback-only by default; `M3_REQUIRE_AUTH=true` flips on
bearer-token auth for cases where the user wants to reach the same instance
from another device on a Tailscale net.

---

## 1. Capture Layer

### What's Built

| Channel              | Mechanism                                    | Status   |
|----------------------|----------------------------------------------|----------|
| Direct upload (UI)   | Text input, file upload (Ingest drawer)      | Built    |
| `m3 ingest` (CLI)    | Pipe text or pass a file path                | Built    |
| Telegram bot         | Forward messages/media to bot                | Built (opt-in) |

### Aspirational

WhatsApp Business, email forwarding, browser extension, OS share targets,
Slack — none of these are implemented. They're plausible plugins under the
provider abstraction but they're not promises.

### Capture UX

Drop content, optionally tag/project it, send. The LLM handles classification,
entity extraction, and source quoting.

### Raw Storage

Every captured item is stored verbatim under `~/brain/items/<id>/` as
plaintext markdown plus a pointer to any binary attachment. Processing
populates the entity graph alongside the raw item but never replaces it —
users can always go back to the source with `cat`.

---

## 2. LLM Layer

### Provider Abstraction

`LLMProvider` (`server/m3/core/llm/base.py`) advertises capability flags so
engines pick the shortest path:

```python
class LLMProvider(ABC):
    supports_tools: bool = False
    supports_vision: bool = False
    supports_audio: bool = False

    async def complete(...) -> str: ...
    async def complete_stream(...) -> AsyncIterator[str]: ...
    async def complete_tool(...) -> ToolResult: ...
```

### Implementations

- **`LocalAgentProvider`** (`server/m3/core/llm/local_agent.py`) — shells
  out to a user-installed AI CLI. Generic over the binary: any of
  `claude` / `codex` / `gemini` / `aider` / `mods` / `llm` (the curated
  `KNOWN_AGENTS` table powers the Settings picker), or a custom command
  the user types. Tool use is emulated via JSON-in-prompt
  (`server/m3/core/llm/_json_tool.py`), shared with `OllamaProvider`.
- **`AnthropicProvider`** — full native tool use, vision, audio.
- **`OllamaProvider`** — uses Ollama's native tools API when the model
  supports it, falls back to JSON-in-prompt otherwise.
- **`UnconfiguredProvider`** — placeholder when nothing is configured.
  Every method raises a clear "Open Settings…" error. The factory in
  `m3.app._make_llm` returns this on any construction failure (missing
  key, missing binary, unknown provider) so the server boots cleanly.

### Capability-Aware Engines

Engines (extraction, agent loop, type consolidation) check `supports_tools`
and pick the right path. `LocalAgentProvider` claims
`supports_tools=True` and emulates the contract via JSON prompts so the
agent loop in `core/agent.py` and the structured extraction in
`core/ingest.py` work uniformly across providers.

The user-visible cost: switching to a non-tool-capable provider (e.g.
local_agent or a small Ollama model) lowers extraction quality vs. native
tool use on Anthropic.

### Voice / Image / PDF

- Audio + vision are passed through to providers that advertise
  `supports_audio` / `supports_vision`. Other providers see a placeholder
  marker and a downgraded text path.
- PDF / DOCX text is extracted locally before reaching the LLM.
- URLs are fetched + readability-extracted locally.

### Configuration

`~/.config/m3/config.yml` (chmod 600). Env vars override:

```yaml
llm:
  # ollama | anthropic | local_agent
  provider: local_agent
  ollama_host: http://localhost:11434
  ollama_model: qwen2.5:7b
  anthropic_api_key: null          # via ANTHROPIC_API_KEY
  anthropic_model: claude-sonnet-4-20250514
  local_agent_command: claude
  local_agent_args: ["-p"]
```

```bash
M3_LLM_PROVIDER=local_agent
LOCAL_AGENT_COMMAND=claude
LOCAL_AGENT_ARGS="-p"             # comma-separated for multi-token lists
ANTHROPIC_API_KEY=sk-ant-...
```

`GET /api/v1/settings` returns `configured: bool` + `unconfigured_reason`
so the UI can render an empty-state CTA instead of letting users hit a 500
on first chat. `GET /api/v1/settings/agents` probes PATH for the curated
list of CLIs the local-agent picker offers.

---

## 3. Brain Layer

### Filesystem Layout

`~/brain/` is the source of truth. Plain markdown, hand-editable, grep-able:

```
~/brain/
├── items/                   one folder per ingested item
│   └── <yyyymm>/<id>/
│       ├── meta.json
│       ├── content.md
│       └── original.<ext>   raw attachment if any
├── entities/                one folder per resolved entity
│   └── <slug>/
│       ├── meta.json
│       └── entity.md
├── self.md                  the user's self-document
├── chats/                   per-session JSONL chat logs
└── _index/
    └── items.sqlite         FTS5 + sqlite-vec indices
```

### Pipeline per Ingest

```
raw text/file
   │
   ▼
extract()                 entities + atomic facts + (optional) relationships
   │
   ▼
entity_resolver           exact / alias / embedding / LLM disambiguation
                          merges "Kato" with "Kato AI" when appropriate
   │
   ▼
persist                   writes ~/brain/items/<id>/ and ~/brain/entities/<slug>/
                          updates _index/items.sqlite (FTS5 + vec0)
   │
   ▼
hooks                     touches `signals.md`, opens questions for the
                          things the LLM couldn't resolve
```

### Storage Engines

- **Markdown on disk.** Source of truth. Hand-editable. Survives any future
  index format change.
- **`_index/items.sqlite`** — FTS5 for keyword search, sqlite-vec for vector
  search. Built from the markdown corpus; `m3 reindex` rebuilds it.
- **No PostgreSQL, no MinIO, no Redis, no docker.** Earlier phases used
  that stack; the rewrite collapses to filesystem + sqlite.

### Schemas (no database — these are dataclasses serialized to markdown frontmatter)

```python
ItemMeta(id, kind, source, created_at, original_filename,
         when_iso, when_source, hooks, confidence)
EntityMeta(slug, canonical_name, entity_type, aliases, description,
           related[], signal_mentions)
```

---

## 4. Cluster View

The Cluster view (`client/src/views/Cluster.tsx`,
`server/m3/api/cluster.py`) takes a query, runs hybrid retrieve, and
renders the matched items + their related entities + their related items
as an interactive force-directed graph.

- Nodes: queries, items, entities. Type drives shape and color.
- Edges: `matched` (query → hits), `hooks` (item → entity), `related`
  (entity ↔ entity).
- Built with **`d3-force` + `@xyflow/react`** in `components/ClusterGraph.tsx`.
- Click → opens `/items/:id` or `/entities/:slug` in a new tab.

The Cluster view also drives chat: each chat turn recomputes the cluster
for the user's question, and the agent's tool calls live-highlight nodes
as it works.

---

## 5. Chat

The Chat view (`client/src/views/Chat.tsx`) runs the agent loop:

1. POST `/api/v1/chat` with the user message.
2. Server runs `run_agent(llm, tools=BrainTools(...))` — the agent picks
   tools (`search_brain`, `open_item`, `open_entity`,
   `list_open_questions`) up to 5 rounds, then writes the final answer.
3. Each agent step streams as an SSE event: `tool_call`, `tool_result`,
   `final`.
4. Chat UI renders tool events inline and live-highlights nodes in the
   cluster graph as they're touched.

If no LLM is configured, the chat router pre-flights and emits a single
`{"type": "unconfigured", "reason": ...}` SSE event. The UI renders a
"No AI agent configured — Open Settings" banner inline instead of a
generic error toast.

---

## 6. Self-Document

`~/brain/self.md` is the user's own model of themselves — a living
document the LLM updates with every ingest. Sections might cover
"Projects," "People I've talked to recently," "Decisions in flight," etc.;
the schema isn't fixed.

The Self view (`client/src/views/Self.tsx`) exposes per-section editing
via PUT `/api/v1/self/<slot>` so the user can guide the LLM by hand.

---

## 7. Open Questions

When the LLM ingests something it can't resolve ("you mentioned 'the
Tuesday meeting' but I don't know which one"), it emits an open question.
The Questions view (`client/src/views/Questions.tsx`) shows the queue;
answering one feeds back into ingest as new context.

---

## 8. Client

A single React + Vite + Tailwind SPA bundled into the Tauri shell. Seven
top-level routes plus a global Ingest drawer:

- `/search` — full-text + vector hybrid retrieve over the brain.
- `/chat` — agent loop with the Cluster graph alongside.
- `/cluster` — standalone cluster explorer for any query.
- `/self` — view + edit `self.md`.
- `/entities` + `/entities/:slug` — entity index and detail.
- `/questions` — open-questions queue.
- `/settings` — provider picker, agents detection, env-overrides surface.

The Ingest drawer is global: hit "+ Ingest" from the nav anywhere to drop
text or files into the brain.

### Aspirational Client Surfaces

PWA install + share target, mobile clients, browser extension — none built.
The current client is the bundled SPA only.

---

## 9. Distribution

### Self-Contained .app

The Tauri shell ships with the Python wheel inside its bundle. On first
launch it:

1. Creates `~/Library/Application Support/local.m3.app/runtime/venv` (or
   the Linux equivalent).
2. `pip install`s the bundled wheel into that venv.
3. Spawns the `m3` server as a child process on a free loopback port.
4. Loads the bundled SPA pointed at that port.

Updates are atomic: the auto-updater downloads a new `.app`, the next
launch reconciles the venv against the new bundled wheel. Brain data
under `~/brain/` is never touched.

### From Source

```bash
git clone https://github.com/yourusername/m3.git
cd m3
./scripts/update.sh    # builds wheel + frontend + .app
```

### Minimum Requirements

- macOS 12+ or Linux (Windows via WSL).
- `python3` 3.12+ on PATH (used to bootstrap the private venv on first
  launch; bundling Python directly is planned).
- 2 GB free disk for the brain to grow into.

---

## 10. Security & Privacy

- **Single-user only.** No multi-tenancy.
- **Loopback-only by default.** Server binds 127.0.0.1; the loopback is
  the security boundary.
- **Opt-in bearer-token auth.** `M3_REQUIRE_AUTH=true` (or `m3 auth`)
  enforces an API key on every request; intended for reaching M3 from a
  phone over Tailscale.
- **Config file is chmod 600.** API keys live there in plaintext; users
  who want stronger isolation can put secrets in `ANTHROPIC_API_KEY` env
  vars instead.
- **No telemetry.** Zero analytics, zero phone-home.
- **LLM privacy.** Only the configured provider sees your content. With
  the local-agent path, content reaches the user's CLI process and the
  upstream service that CLI talks to (e.g. Anthropic for Claude Code) —
  same as if the user invoked the CLI by hand. With Ollama, nothing
  leaves the machine.
- **Brain is plain markdown.** Encrypt the disk if you need encryption at
  rest; M3 doesn't add a layer.

### Known Security Debt

- The M3 API key (when auth is on) is held in `localStorage` on the
  client. XSS would exfiltrate it. A future cookie-based session is the
  right fix.
- Rate limiting is absent.

---

## 11. Roadmap

### Done

- Tauri shell + bundled wheel + private-venv bootstrap.
- In-app auto-update (signed releases pending).
- Brain on disk: items, entities, self, chats, FTS5 + sqlite-vec index.
- Hybrid retrieve (FTS + vector) with reasons.
- Agent loop chat with cluster-live-highlighting.
- LLM provider abstraction (anthropic, ollama, local_agent, unconfigured).
- Settings UI with installed-agent picker + custom-command escape hatch.
- "No LLM configured" empty-state CTA across Settings + Chat.
- Direct-upload + Telegram capture.

### Near term

- Per-CLI streaming for `LocalAgentProvider` (e.g. `claude
  --output-format stream-json`) so chat reveals tokens live.
- Brain export / backup endpoint (markdown bundle + index).
- Bundle a Python interpreter into the .app so users don't need
  system `python3`.
- Signed + notarized releases.

### Aspirational

- WhatsApp Business + email-forward capture.
- Browser extension + PWA share target.
- iOS Shortcuts ingest.
- MCP server exposure of M3's brain so external agents (Claude Code etc.)
  can search M3 from outside the .app.
- Plugin marketplace for capture / processing / view extensions.
- Mobile clients.

---

## What M3 Is NOT

- **Not a team tool.** One instance, one person.
- **Not a note-taking app.** You don't write in M3; you forward into M3.
- **Not a project manager.** It's the thinking layer above your PM tools.
- **Not cloud-hosted SaaS.** Your machine, your disk, your rules.
- **Not locked to any LLM.** Switch in one click in Settings.
- **Not a rigid schema.** Categories emerge from your content.

---

## Name

**M3** —

- **Me, Myself, Mine** — ownership and privacy
- **My Mind Map** — what it visualizes
- **Memory, Meaning, Map** — what it builds

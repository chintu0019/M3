# M3 — Me, Myself, Mine
## Personal Knowledge Operating System
### Product Specification v3 — Open Core

---

## What M3 Is

An open-source, self-hosted personal knowledge OS. You share things from anywhere in your life — emails, voice notes, messages, receipts, screenshots, articles, anything — and an LLM organizes it all into a living, evolving knowledge base. No prescribed structure. The system learns how you think and organizes accordingly.

You can view your knowledge as an interactive graph, chat with your entire brain from any device, and the system surfaces connections and insights you'd never find manually.

**Open-source. Self-hosted. Single-user. Fully private.**

---

## Philosophy

### No Prescribed Structure

M3 does not ship with a predefined wiki layout. No hardcoded folders for "projects" or "people" or "concepts." The LLM observes what you share, discovers categories organically, and builds a structure that reflects how your mind actually works.

Early on, the wiki might just be a flat collection of pages. Over time, the LLM will notice patterns: "This person keeps sharing things about three distinct projects, plus personal finance receipts, plus machine learning papers." It creates structure in response to reality, not ahead of it.

The user can always guide: "Create a section for my reading list" or "These items are all part of a project called Kato." But guidance is optional. The default is: share things, the LLM figures it out.

### What Flows In

Anything you encounter in life that you want to remember, reference, or reason about:

- Meeting notes and decisions
- Receipts and purchases
- Articles and papers you're reading
- Topics you're learning about
- Voice memos and quick thoughts
- Forwarded messages from any chat app
- Screenshots of interesting things
- URLs worth remembering
- Contacts and people context
- Ideas, half-formed or fully baked
- Files, documents, images

The only rule: if you might want to find it later or connect it to something else, share it with M3.

---

## Open-Core Model

M3 is open-source (MIT licensed) with a proprietary intelligence layer.

### What's Open (MIT, public repo)

Everything needed to run a fully functional M3 instance:

- FastAPI server, database schema, storage layer, task queue
- All capture channel plugins (Telegram, WhatsApp, email, etc.)
- Client apps (React web, Tauri desktop, PWA mobile)
- Graph visualization engine
- Chat interface and API
- Plugin architecture and loader
- Docker deployment and configuration system
- LLM provider abstraction layer
- A **basic compilation engine** that works. It ingests, classifies, writes wiki pages, creates backlinks, and maintains the index. Functional, not exceptional.

The basic engine is the Honda Civic. It gets you there.

### What's Private (never in the repo)

The intelligence that makes M3 genuinely good:

- **Premium compilation prompts**: The prompt chains that control how the LLM organizes knowledge, discovers categories, writes wiki pages, detects contradictions, and surfaces insights. This is not code. It's prompt engineering and pipeline design refined through extensive iteration.
- **Processing chain logic**: The specific sequence of LLM calls, what context gets passed between steps, how the system decides when to create a new page vs update an existing one, when to merge categories, when to split topics.
- **Schema evolution strategy**: How the LLM decides when and how to restructure the wiki as it grows. The rules for organic structure generation that produce surprisingly good results.
- **Insight generation**: The prompts and logic that surface non-obvious connections, contradictions, and patterns across the wiki.

These live in a **private repository** and are loaded at runtime as a swappable engine module.

### How the Abstraction Works

```python
# In the open-source repo: server/m3/core/engines/base.py
class CompilationEngine:
    """Base class. The open-source basic engine implements this."""
    
    async def classify(self, item: RawItem, wiki_index: str) -> Classification:
        """Classify a raw item: tags, project, content type."""
        raise NotImplementedError
    
    async def compile(self, item: ClassifiedItem, related_pages: list[WikiPage]) -> CompileResult:
        """Compile a classified item into wiki page updates."""
        raise NotImplementedError
    
    async def synthesize(self, wiki_index: str) -> SynthesisResult:
        """Cross-reference, find contradictions, surface insights."""
        raise NotImplementedError
    
    async def evolve_schema(self, wiki_index: str, schema: str) -> str:
        """Decide if wiki structure needs reorganization."""
        raise NotImplementedError


# In the open-source repo: server/m3/core/engines/basic.py
class BasicEngine(CompilationEngine):
    """Ships with M3. Works fine. Straightforward prompts."""
    # Functional but not exceptional


# In the PRIVATE repo: m3-engine-pro/engine.py
class ProEngine(CompilationEngine):
    """Premium engine. Much better synthesis, insight generation, 
    and organic structure evolution. Never published."""
    # This is the secret sauce
```

```yaml
# config.yml
compilation:
  engine: basic              # Default: ships with open-source
  # engine: pro              # Premium: loaded from private module
  # engine: custom           # User's own engine implementation
  # engine_path: /path/to/custom/engine.py  # For custom engines
```

Users who want to write their own compilation engine can. The interface is documented. But the ProEngine is never distributed.

### Why This Works

- **Open-source community** gets a fully functional product. They can self-host, extend with plugins, add capture channels, build views. No crippled free tier.
- **The private engine** is pure prompt engineering and LLM orchestration logic. Even if someone reads the interface, they can't reverse-engineer the prompts. The quality difference is in the nuance of how you instruct the LLM, not in the code structure.
- **Community engines will emerge.** Some will be good. That's fine. The ProEngine stays ahead through continuous iteration against real usage patterns.
- **Future monetization** (optional): the ProEngine could be offered as a paid add-on, a hosted API, or bundled with a managed M3 service. But that's not the priority now.

---

## Core Architecture

```
[Capture Channels]          [M3 Server]                    [Client Apps]
                                                           
Email forward ──┐           ┌─────────────────────┐       ┌──────────────┐
Voice note ─────┤           │                     │       │ Web App      │
WhatsApp fwd ───┤           │   API Server        │       │ (React PWA)  │
Telegram bot ───┤──HTTPS──▶ │   (FastAPI)         │◀─────▶│              │
Screenshot ─────┤           │                     │       │ - Wiki View  │
URL share ──────┤           │   ┌───────────────┐ │       │ - Graph View │
Manual note ────┤           │   │ LLM Router    │ │       │ - Chat       │
File upload ────┤           │   │ Claude / Any  │ │       │ - Inbox      │
Browser clip ───┤           │   └───────────────┘ │       │ - Insights   │
Receipt photo ──┘           │                     │       │ - Settings   │
                            │   ┌───────────────┐ │       └──────────────┘
                            │   │ Task Queue    │ │              │
                            │   │ (Background   │ │       Tauri wrapper for
                            │   │  processing)  │ │       macOS / Linux
                            │   └───────────────┘ │       desktop apps
                            └────────┬────────────┘
                                     │
                         ┌───────────┼───────────┐
                         ▼           ▼           ▼
                   ┌──────────┐ ┌──────────┐ ┌──────────┐
                   │PostgreSQL│ │  MinIO   │ │  Redis   │
                   │+ pgvector│ │(files,   │ │(queue,   │
                   │          │ │ voice,   │ │ cache)   │
                   │          │ │ images)  │ │          │
                   └──────────┘ └──────────┘ └──────────┘
```

---

## 1. Capture Layer

### Channels (Priority Order)

| Priority | Channel | Mechanism | Notes |
|----------|---------|-----------|-------|
| P0 | **App (direct)** | Text input, file upload, camera, mic | Core capture surface |
| P0 | **Telegram bot** | Forward messages/media to bot | Fastest to implement, rich media support |
| P1 | **WhatsApp bot** | Forward messages to WhatsApp Business bot | Most used by many people, requires Meta API approval |
| P1 | **Email** | Forward to brain@yourdomain.com | IMAP polling, handles attachments |
| P2 | **Browser extension** | Clip pages, highlight text | Chrome/Firefox |
| P2 | **Slack bot** | DM or forward messages | For work context |
| P3 | **SMS** | Forward texts | Via Twilio or SIM gateway |
| P3 | **Share target** | OS-level "Share to M3" | PWA share_target on Android |

### Capture UX

When sharing to M3, the user sees:

1. **Content preview** (what's being shared)
2. **Optional tag picker** (existing tags auto-suggested, can add new)
3. **Optional project picker** (existing projects, "new project", or leave blank)
4. **Send button**

That's it. Everything else is optional. The fastest path is: share → send. No tags, no project, no friction. The LLM handles classification.

### Raw Storage

Every captured item is stored as-is, forever. The original voice note, the original screenshot, the original email. Processing creates wiki content alongside the raw item, never replacing it. Users can always go back to the source.

```
Raw item stored in MinIO:
- Original file (audio, image, PDF, etc.)
- Extracted text (from OCR, transcription, parsing)
- Capture metadata (timestamp, source, device, user-provided tags)
- Processing status (pending, processed, failed)
```

---

## 2. LLM Engine

### Provider Architecture

M3 is LLM-agnostic. The user configures their preferred provider.

```python
# config.yml
llm:
  default_provider: claude
  
  providers:
    claude:
      type: anthropic
      api_key: ${ANTHROPIC_API_KEY}
      model: claude-sonnet-4-20250514
      # Works with API key OR can be configured for
      # subscription-based access patterns
      
    openai:
      type: openai
      api_key: ${OPENAI_API_KEY}
      model: gpt-4o
      
    local:
      type: ollama
      base_url: http://localhost:11434
      model: llama3.1:70b
      
    custom:
      type: openai_compatible
      base_url: https://your-endpoint.com/v1
      api_key: ${CUSTOM_API_KEY}
      model: your-model

  # Route different tasks to different providers
  routing:
    transcription: claude      # Audio → text
    classification: claude     # Tagging, project assignment
    synthesis: claude          # Wiki writing, cross-referencing
    chat: claude               # User queries
    # Users can mix: e.g. local model for classification,
    # Claude for synthesis
```

Switching providers is a config change, not a code change. The LLM interface is abstracted so any OpenAI-compatible API works.

### Voice Note Processing

Voice notes are handled by the LLM provider, not local Whisper. Flow:

1. User shares a voice note
2. M3 stores the original audio file in MinIO
3. During processing, the audio is sent to the configured LLM (Claude supports audio input)
4. LLM returns transcription + summary + extracted entities
5. Transcription is stored alongside the audio
6. Wiki is updated based on content

This keeps server requirements minimal. No GPU needed. If a user wants local transcription for privacy, they can configure Whisper as an optional preprocessor, but it's not the default path.

### Processing Pipeline

```
Raw Input Arrives
    │
    ▼
[Store original in MinIO]
    │
    ▼
[Queue for processing]
    │
    ▼
[Parse & Extract]
    │  Audio → send to LLM for transcription
    │  Image/Screenshot → send to LLM with vision for OCR + understanding
    │  PDF/DOCX → text extraction (local, no LLM needed)
    │  URL → Trafilatura content extraction (local)
    │  Email → parse headers, body, attachments (local)
    │  Receipt → send to LLM with vision for amount, vendor, date, items
    │
    ▼
[LLM: Understand & Classify]
    │  Input: extracted content + existing wiki index
    │  Output:
    │    - Summary
    │    - Auto-generated tags
    │    - Suggested project (or "none/new")
    │    - Identified entities (people, companies, concepts)
    │    - Content type (decision, idea, receipt, reading, contact, etc.)
    │    - Relationships to existing wiki pages
    │
    ▼
[LLM: Integrate into Wiki]
    │  Input: classification output + relevant existing wiki pages
    │  Output:
    │    - New or updated wiki pages (markdown)
    │    - New or updated backlinks
    │    - Updated index
    │    - Changelog entry
    │
    ▼
[Store in PostgreSQL + update graph]
```

### Organic Structure Generation

The LLM maintains a `_schema.md` file in the wiki root that describes the current structure it has created. This schema evolves:

```markdown
# Wiki Schema (auto-maintained by M3)

## Current Structure

### Top-Level Categories
- **Projects**: Active work streams (Kato AI, PilotPath, MoniSub)
- **Learning**: Topics being studied (LLM architectures, Irish tax law)
- **People**: Key contacts and relationship context
- **Finances**: Receipts, expenses, financial decisions
- **Ideas**: Unvalidated concepts and explorations

### Conventions
- Each category has an index.md listing all pages
- People pages link to every project they're associated with
- Receipt pages include: date, vendor, amount, category, linked project
- Reading pages include: source URL, key takeaways, related concepts

### Recent Structure Changes
- 2026-04-14: Created "Learning" category after 5+ items about ML papers
- 2026-04-10: Split "Work" into separate project categories
- 2026-04-08: Created "Finances" after first receipt was shared
```

The schema is descriptive (documenting what exists) not prescriptive (dictating what must exist). New categories emerge when the LLM notices clusters of related content.

---

## 3. Wiki Layer

### Storage

Wiki pages are stored in two places simultaneously:

1. **PostgreSQL**: Structured data (frontmatter fields, relationships, vectors for semantic search)
2. **Markdown files on disk** (via MinIO): The actual page content, always exportable

This dual storage means:
- Fast queries and search via PostgreSQL
- Full portability via markdown export
- Graph relationships computed from PostgreSQL data
- Users can always export their entire wiki as a folder of .md files

### Page Format

Every wiki page has LLM-generated frontmatter:

```yaml
---
id: uuid
title: Page Title
category: projects/kato     # LLM-assigned, can be moved
type: decision              # LLM-determined content type
tags: [pricing, strategy]   # Auto-generated + user-provided
created: 2026-04-13T10:30:00Z
updated: 2026-04-14T08:15:00Z
sources:                    # Links back to raw items
  - raw://voice-note-2026-04-13.m4a
  - raw://email-from-john-2026-04-12.eml
related:                    # Backlinks to other pages
  - wiki://go-to-market-strategy
  - wiki://people/john-smith
confidence: 0.85
---

[LLM-written page content in markdown]
```

Content types the LLM might assign (not prescribed, it discovers these):
- decision, idea, meeting, research, person, receipt, reading, project-overview, concept, pattern, insight, contact, learning, bookmark, quote, and whatever else emerges

### Graph Storage (PostgreSQL)

Simple relationship tables:

```sql
-- Pages
CREATE TABLE wiki_pages (
    id UUID PRIMARY KEY,
    title TEXT,
    category TEXT,
    type TEXT,
    content TEXT,
    embedding VECTOR(1536),  -- pgvector for semantic search
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    confidence FLOAT
);

-- Relationships between pages
CREATE TABLE wiki_links (
    source_id UUID REFERENCES wiki_pages(id),
    target_id UUID REFERENCES wiki_pages(id),
    link_type TEXT,          -- 'references', 'contradicts', 'extends', 'person_involved', etc.
    weight FLOAT DEFAULT 1.0,
    created_at TIMESTAMPTZ
);

-- Tags
CREATE TABLE wiki_tags (
    page_id UUID REFERENCES wiki_pages(id),
    tag TEXT
);
```

This is enough to power the graph visualization. D3.js on the client reads nodes (pages) and edges (links) and renders the interactive graph. Same data, different view.

If graph queries ever need more power (e.g. "find all paths between concept A and person B through any number of hops"), a Neo4j layer can be added behind the same API. But PostgreSQL handles this fine for thousands of pages.

---

## 4. Graph Visualization

### Obsidian-Style Graph View

Interactive, force-directed graph rendered with D3.js in the browser.

**Nodes**: Wiki pages. Size reflects number of connections. Color reflects category (auto-assigned, user can customize palette).

**Edges**: Links between pages. Thickness reflects strength (number of cross-references). Style reflects type (solid = direct reference, dashed = inferred connection).

**Interactions**:
- Click node → open page in wiki view
- Hover → show page title + summary
- Drag → reposition nodes
- Scroll → zoom in/out
- Search → highlight matching nodes, fade others
- Filter panel → toggle categories, types, date ranges, confidence levels

**Views**:
- **Full graph**: Everything connected
- **Project view**: Filter to one category/project
- **Ego graph**: Show one page and everything connected to it (1-2 hops)
- **Temporal**: Timeline showing when pages were created/updated
- **Clusters**: Auto-detected topic clusters highlighted

### Implementation

```
Server: GET /api/v1/wiki/graph?filter=...
  → Returns JSON: { nodes: [...], edges: [...] }

Client: D3.js force simulation
  → Renders in <canvas> or <svg>
  → Same component works in web, Tauri desktop, and mobile WebView
```

---

## 5. Chat Interface

### How It Works

User asks a question. M3:

1. Embeds the question using the configured LLM
2. Searches wiki via semantic search (pgvector) + keyword search
3. Retrieves relevant pages (top-k)
4. Sends pages + question to LLM
5. Streams the response with citations linking to wiki pages

### Chat Capabilities

- **Ask anything**: "What did I decide about pricing last month?"
- **Cross-reference**: "How are Kato and PilotPath similar in their go-to-market challenges?"
- **Draft content**: "Write a LinkedIn post about Kato using recent developments from my wiki"
- **Recall**: "What was the name of that person I met at the GEC event?"
- **Receipts/Finance**: "How much did I spend on travel in March?"
- **Learning**: "Summarize everything I've been reading about transformer architectures"
- **Actions**: "Create a new project called 'Side Project X' and move these items into it"
- **File back**: Good chat responses can be saved as wiki pages ("Save this to my wiki")

### Chat UI

- Streaming responses with markdown rendering
- Clickable citations that link to wiki pages
- Conversation history (stored locally, not in wiki)
- Quick actions: compile, create project, export

---

## 6. Insights Feed

The LLM periodically (or on-demand) generates observations:

- **Stale content**: "Your PilotPath section hasn't been updated in 6 weeks"
- **Contradictions**: "Your pricing strategy page says X, but last week's meeting note says Y"
- **Connections**: "You mentioned [concept] in both Kato and your ML reading notes"
- **Orphans**: "These 5 pages have no connections to anything else"
- **Patterns**: "You've shared 12 receipts from the same vendor in 3 months"
- **Suggestions**: "Based on your recent reading, you might want a wiki section on [topic]"
- **People**: "John appears across 3 of your projects"

Shown as a dismissable feed in the app. Each insight links to relevant pages.

---

## 7. Client Apps

### Single Codebase Strategy

```
┌──────────────────────────────────────────┐
│           React + Tailwind + Vite         │
│              (Single codebase)            │
│                                          │
│  ┌──────────┐ ┌─────────┐ ┌──────────┐  │
│  │Wiki View │ │Graph    │ │Chat      │  │
│  │          │ │View     │ │Interface │  │
│  └──────────┘ └─────────┘ └──────────┘  │
│  ┌──────────┐ ┌─────────┐ ┌──────────┐  │
│  │Inbox     │ │Insights │ │Settings  │  │
│  │(Capture) │ │Feed     │ │          │  │
│  └──────────┘ └─────────┘ └──────────┘  │
└──────────┬──────────┬──────────┬─────────┘
           │          │          │
     ┌─────┴───┐ ┌────┴────┐ ┌──┴──────────┐
     │ PWA     │ │ Tauri   │ │ PWA         │
     │ Android │ │ macOS   │ │ iOS (home   │
     │ (Chrome)│ │ Linux   │ │  screen)    │
     └─────────┘ └─────────┘ └─────────────┘
```

One React app. Three distribution channels:

1. **PWA (Progressive Web App)**: Works on Android (Chrome), iOS (Safari). Install to home screen. Share target support on Android. One codebase change reflects everywhere.
2. **Tauri**: Wraps the same React app as a native desktop binary for macOS and Linux. Tiny bundle size (~5MB vs Electron's ~150MB). Access to local filesystem if needed.
3. **Web browser**: Just open the URL. Works everywhere.

No separate Android or iOS codebases. No React Native. No Flutter. The PWA handles mobile, Tauri handles desktop, and the web app is the fallback for everything else.

### Mobile Capture UX

**Android**: PWA share target means "Share to M3" appears in the Android share sheet. Share a WhatsApp message, a screenshot, a URL, a file — it goes straight to M3's inbox.

**iOS**: PWA share target support is limited on iOS. Workaround: a Shortcuts action that sends content to the M3 API endpoint. One tap from the share sheet. Not as seamless as Android but functional.

---

## 8. Open-Source Design

### License

**MIT** for the open-source repository. Maximum adoption, lowest barrier.

The private compilation engine (ProEngine) is kept in a separate private repository, never distributed. See the Open-Core Model section for details.

### Plugin Architecture

M3 should be extensible without forking:

```
plugins/
├── capture/              # New capture channels
│   ├── telegram/         # Built-in
│   ├── whatsapp/         # Built-in
│   ├── discord/          # Community plugin
│   └── rss/              # Community plugin
│
├── processors/           # Custom processing steps
│   ├── receipt-parser/   # Enhanced receipt understanding
│   ├── calendar-sync/    # Sync calendar events as wiki items
│   └── github-activity/  # Import GitHub activity
│
├── outputs/              # Export/output formats
│   ├── daily-digest/     # Email digest of changes
│   ├── obsidian-export/  # Export compatible with Obsidian
│   └── anki-cards/       # Generate flashcards from learning pages
│
└── views/                # Custom UI views
    ├── timeline/         # Timeline view of all items
    ├── kanban/           # Kanban board for ideas/projects
    └── calendar/         # Calendar view of time-tagged items
```

Plugin interface:

```python
# Example: capture plugin interface
class CapturePlugin:
    name: str
    description: str
    
    async def setup(self, config: dict) -> None:
        """Initialize the plugin (e.g. register webhook)"""
        
    async def process_incoming(self, raw_data: bytes, metadata: dict) -> CapturedItem:
        """Transform incoming data into a standard CapturedItem"""
        
    async def health_check(self) -> bool:
        """Is this capture channel working?"""
```

### Repository Structure

```
m3/
├── README.md
├── LICENSE                 # MIT
├── docker-compose.yml      # One-command deployment
├── docs/
│   ├── getting-started.md
│   ├── configuration.md
│   ├── plugin-development.md
│   ├── architecture.md
│   └── api-reference.md
│
├── server/
│   ├── pyproject.toml
│   ├── m3/
│   │   ├── api/            # FastAPI routes
│   │   ├── core/
│   │   │   ├── engines/    # Compilation engine abstraction
│   │   │   │   ├── base.py     # Engine interface (public)
│   │   │   │   ├── basic.py    # Basic engine (public, ships with M3)
│   │   │   │   └── loader.py   # Loads engine from config (basic/pro/custom)
│   │   │   ├── compiler.py # Wiki compilation pipeline
│   │   │   ├── graph.py    # Graph computation
│   │   │   └── search.py   # Semantic + keyword search
│   │   ├── capture/        # Built-in capture plugins
│   │   ├── storage/        # PostgreSQL, MinIO, Redis interfaces
│   │   ├── plugins/        # Plugin loader
│   │   └── config.py       # Configuration management
│   ├── migrations/         # Alembic database migrations
│   └── tests/
│
├── client/
│   ├── package.json
│   ├── src/
│   │   ├── views/          # Wiki, Graph, Chat, Inbox, Insights, Settings
│   │   ├── components/     # Shared UI components
│   │   ├── hooks/          # API hooks
│   │   └── lib/            # Graph rendering, markdown parsing
│   ├── public/
│   │   └── manifest.json   # PWA manifest with share_target
│   └── src-tauri/          # Tauri desktop config
│
├── plugins/                # Official plugins
│   ├── capture-telegram/
│   ├── capture-whatsapp/
│   ├── capture-email/
│   └── ...
│
└── scripts/
    ├── setup.sh            # First-time setup helper
    └── backup.sh           # Automated backup script
```

**Private repository (never published):**

```
m3-engine-pro/              # Separate private repo
├── engine.py               # ProEngine implementation
├── prompts/
│   ├── classify.py         # Classification prompt chains
│   ├── compile.py          # Wiki compilation prompts
│   ├── synthesize.py       # Cross-referencing and insight prompts
│   ├── evolve.py           # Schema evolution prompts
│   └── insights.py         # Pattern detection and contradiction prompts
├── tests/
│   └── ...                 # Tests against the engine interface
└── README.md               # Private setup instructions
```

To use ProEngine: clone the private repo, point `engine_path` in config.yml to it. The public repo never references it.

### Configuration

Everything configurable via a single `config.yml` (or environment variables for Docker):

```yaml
# M3 Configuration

server:
  host: 0.0.0.0
  port: 8000
  secret_key: ${M3_SECRET_KEY}
  
database:
  url: postgresql://m3:${DB_PASSWORD}@postgres:5432/m3

storage:
  type: minio  # or 'local' for filesystem
  endpoint: minio:9000
  access_key: ${MINIO_ACCESS_KEY}
  secret_key: ${MINIO_SECRET_KEY}
  bucket: m3-data

llm:
  default_provider: claude
  providers:
    claude:
      api_key: ${ANTHROPIC_API_KEY}
      model: claude-sonnet-4-20250514
    # Add more providers as needed

processing:
  engine: basic                   # 'basic' (ships with M3) or 'custom'
  engine_path: null               # Path to custom engine module (e.g. /opt/m3-engine-pro/engine.py)
  auto_compile: true
  compile_interval_minutes: 60    # How often to process pending items
  deep_compile_cron: "0 3 * * 0"  # Weekly deep compile (Sunday 3am)
  
capture:
  telegram:
    enabled: true
    bot_token: ${TELEGRAM_BOT_TOKEN}
  whatsapp:
    enabled: false
    # WhatsApp config when ready
  email:
    enabled: false
    # IMAP config when ready

auth:
  type: api_key  # Single user, simple auth
  api_key: ${M3_API_KEY}
  totp_enabled: false
```

### Deployment Options

**Option 1: Home Server (default)**
```bash
git clone https://github.com/yourusername/m3.git
cd m3
cp config.example.yml config.yml
# Edit config.yml with your API keys
docker compose up -d
```

**Option 2: VPS (Hetzner, DigitalOcean, etc.)**
Same as above, but on a remote machine. Caddy handles TLS automatically.

**Option 3: Cloud-managed**
Community can build Helm charts, Terraform modules, etc. for Kubernetes, AWS, etc.

### Minimum Server Requirements

Since we're using Claude API (no local models, no GPU):

- **CPU**: 2 cores
- **RAM**: 4GB
- **Storage**: 20GB+ (grows with your data)
- **OS**: Any Linux with Docker
- **Cost**: ~$5-10/month on Hetzner/DigitalOcean + Claude API costs

If someone wants local models (Ollama), they'd need more RAM (16GB+) and optionally a GPU.

---

## 9. Security & Privacy

- **Single-user only**: No multi-tenancy. One M3 instance = one person.
- **Auth**: API key for all requests. Optional TOTP 2FA for web UI.
- **TLS**: Caddy auto-provisions Let's Encrypt certificates.
- **Data at rest**: PostgreSQL and MinIO volumes should be on encrypted disk.
- **LLM privacy**: Only the configured LLM provider sees your content. With local models, nothing leaves the server.
- **No telemetry**: Zero analytics, zero tracking, zero phone-home. Open source means auditable.
- **Backup**: Built-in backup script. Encrypted, to any S3-compatible target or local path.
- **Export**: One-click full wiki export as a folder of markdown files. Your data is never locked in.
- **Credential management**: API keys stored as environment variables, never in config files committed to git.

---

## 10. Build Roadmap

### Phase 1: Core Loop (Weeks 1-4)
**Goal: Share things → LLM organizes → browse wiki → chat with it**

- [ ] FastAPI server with PostgreSQL + pgvector + MinIO + Redis
- [ ] Universal ingest API endpoint
- [ ] LLM processing pipeline (Claude API integration)
- [ ] Organic wiki structure generation (no prescribed layout)
- [ ] Auto-tagging and classification
- [ ] Basic markdown wiki storage and retrieval
- [ ] Semantic search across wiki
- [ ] Chat endpoint with wiki context (streaming)
- [ ] Telegram bot for capture
- [ ] Basic web UI: inbox, wiki browser, chat
- [ ] Docker compose deployment
- [ ] Scheduled compile passes (Celery)
- [ ] Configuration system (config.yml)
- [ ] API key authentication

### Phase 2: Visualization & Intelligence (Weeks 5-7)
**Goal: See your knowledge graph, get insights**

- [ ] Graph visualization (D3.js force-directed)
- [ ] Graph filtering (by category, type, date, tags)
- [ ] Ego graph view (focus on one node)
- [ ] Insights feed (stale content, contradictions, orphans, connections)
- [ ] Wiki health dashboard
- [ ] Cross-reference detection and linking
- [ ] Schema evolution (LLM-managed _schema.md)
- [ ] Changelog and processing history

### Phase 3: More Channels (Weeks 8-10)
**Goal: Capture from everywhere**

- [ ] WhatsApp Business bot integration
- [ ] Email ingest (IMAP polling)
- [ ] Voice note support (audio → LLM transcription)
- [ ] Receipt parsing (image → structured data)
- [ ] URL content extraction (Trafilatura)
- [ ] Screenshot understanding (Claude Vision)
- [ ] Browser extension (Chrome)
- [ ] PWA share target (Android)

### Phase 4: Apps & Polish (Weeks 11-14)
**Goal: Use from any device, polished experience**

- [ ] PWA optimization (offline support, install prompts)
- [ ] Tauri desktop app (macOS + Linux)
- [ ] iOS capture via Shortcuts
- [ ] Plugin system architecture
- [ ] LLM provider abstraction (swap providers via config)
- [ ] Export system (full wiki as markdown, JSON, or both)
- [ ] Backup and restore
- [ ] Open-source documentation
- [ ] Contributing guidelines
- [ ] Setup wizard for first-time users

### Phase 5: Community & Ecosystem (Ongoing)
**Goal: Let others build on M3**

- [ ] Plugin marketplace / registry
- [ ] Community capture plugins (Discord, RSS, Slack, etc.)
- [ ] Community view plugins (timeline, kanban, calendar)
- [ ] Community processor plugins (calendar sync, GitHub activity)
- [ ] Obsidian export plugin (for people who want both)
- [ ] Fine-tuning pipeline (train a personal model on your wiki)
- [ ] Multi-language support

---

## 11. What M3 Is NOT

- **Not a team tool.** One instance, one person. Always.
- **Not a note-taking app.** You don't write in M3. You dump into M3, the LLM writes.
- **Not a project management tool.** It's the thinking layer above your PM tools.
- **Not cloud-hosted SaaS.** Your server, your data, your rules.
- **Not locked to any LLM.** Swap providers anytime via config.
- **Not a rigid system.** No prescribed structure. The LLM adapts to you.

---

## 12. Name

**M3** — interpretations:

- **Me, Myself, Mine** — ownership and privacy
- **My Mind Map** — what it visualizes
- **Memory, Meaning, Map** — what it builds

---

## 13. Comparable Projects

For positioning and differentiation:

| Project | How M3 Differs |
|---------|---------------|
| Obsidian | M3 writes the wiki for you. Obsidian is manual. M3 has universal capture. |
| Karpathy's LLM Wiki | M3 productizes the pattern. No terminal needed. Multi-channel capture. |
| Notion | M3 is self-hosted, single-user, LLM-native. Notion is cloud, team-first, manual. |
| Mem.ai | M3 is open-source and self-hosted. Mem is proprietary SaaS. |
| Khoj | Closest competitor. Khoj is a personal AI assistant. M3 goes further with organic wiki structure and graph visualization. |
| Recall.ai | Cloud-based, not self-hosted. M3 is fully private. |
| NotebookLM | Stateless RAG. M3 builds compounding knowledge. |
| OpenClaw | OpenClaw is a general AI agent for messaging channels. M3 is a knowledge OS that builds a compounding wiki. Different jobs. Could potentially integrate as an OpenClaw skill in the future. |

### Open-Core Precedents

Projects M3's business model takes inspiration from:

| Project | Open | Proprietary |
|---------|------|-------------|
| GitLab | Core platform (MIT) | Premium features (EE license) |
| Supabase | Database, auth, storage (Apache 2.0) | Managed cloud, enterprise features |
| Sentry | Error tracking platform (BSL) | Hosted service, enterprise |
| OpenClaw | Gateway + channels (MIT) | OpenClaw Launch (managed hosting) |
| **M3** | Platform, apps, plugins (MIT) | Compilation engine (ProEngine) |

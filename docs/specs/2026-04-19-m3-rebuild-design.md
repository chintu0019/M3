# M3 — Full Rebuild Design

> Status: design / pre-plan. Written 2026-04-19. Supersedes the current M3 implementation.

## 1. Why a rebuild

The current M3 is complex (Postgres + pgvector + Redis + ARQ + MinIO + FastAPI + React, six to seven LLM passes per item) and still fails at the basics: facts misattributed ("Manoj likes FluentCRM" extracted from content where he was against it), entity drift not resolved (`Pilot Path` / `PilotPath` / `Pilot Path Group` treated as three different things), the self page empty because only conversations feed it, and wiki pages that read like Wikipedia rather than like notes about the user's world.

Every complex layer in the current system exists to build synthesized artifacts (compiled wiki pages, entity graph with link weights, typed insights) — and those synthesized artifacts are what's wrong. The rebuild deletes the synthesis layer and keeps the items as the source of truth.

## 2. What M3 is

A local-first personal brain that runs as a native app on Mac and Linux. Its one non-negotiable job is **remembering**: anything the user has shared is findable later, accurately, regardless of whether the user remembers a precise phrase, a person, a date, a project, or just a vague vibe.

Remembering is the floor. Four capabilities stack on top, in priority order:

1. **Remembering** (A) — floor, must never fail
2. **Answering** (B) — query your own stuff and get grounded answers
3. **Understanding** (C) — the evolving picture of you, who you know, what you work on
4. **Reflecting** (D) — patterns surfaced you wouldn't catch yourself
5. **Acting** (E) — offload operational work (future)

C is not separate from A; it is the *hook infrastructure* that makes A work for humans. You cannot retrieve by "Sarah" unless the system has decided Sarah is a thing. So C exists in service of A, not in parallel to it. B and D are interfaces over A.

E is explicitly out of scope for the first rebuild.

## 3. Core principle: items are the atoms, hooks are the index, views are rendered on read

The single biggest shift from the current system.

- **Items** (the raw thing the user shared: text, image, voice memo, PDF, URL) are immutable source of truth. They are never rewritten. They live in `~/brain/items/` as original bytes plus a sidecar JSON of extracted text and metadata.
- **Hooks** are the extraction contract — a small, reliable set of tags every item must be indexed by. Extraction's only job is to fill hooks correctly. Hooks are what fragments latch onto at retrieval time.
- **Entities** (person, project, topic, place, company) are *hook namespaces*, not compiled pages. Opening "Pilot Path" does not show you an LLM-written narrative; it shows you every item that hooks to Pilot Path, plus an overview generated on demand at read time if you ask for one. The LLM never writes permanent prose; it only writes hooks.
- **Self** is one special entity with fixed slots (preferences, people, projects, goals, context, beliefs, timeline). Its slots are short diff-applied markdown, written by the LLM with the three hardening rules below. This is the only compiled artifact, because the self needs a stable shape for the user to navigate.

### 3.1 The hook set

Every item gets these hooks extracted. Missing a hook is acceptable; fabricating one is not.

| Hook | What it holds | How it's used |
|---|---|---|
| `who` | People entities mentioned | Retrieval by person, person-centric views |
| `what` | Topic / concept / thing entities | Retrieval by topic, cluster view |
| `where` | Place entities (physical or digital — "Bangalore", "on Twitter") | Retrieval by location |
| `when` | Dates/times parsed from inside the content | Timeline retrieval, temporal queries |
| `source` | Channel / medium (Telegram, share-sheet, drag-drop, email-in, voice) | Retrieval by source, filtering |
| `project` | Which project or life-area this sits in | Retrieval by context |
| `stance` | List of `{entity_name, value, evidence_quote}`; value ∈ positive / negative / uncertain / neutral | Prevents the "Manoj likes FluentCRM" bug |
| `full_text` | Raw extracted text (not LLM-emitted — already present in `items/meta/*.extracted_text`) | Keyword search |

The hook set is deliberately small. Adding hooks later is cheap; relying on hooks that don't exist yet is not.

## 4. The three hardening rules

These govern everything the LLM produces.

### 4.1 Temporal grounding

Every item has a `when` hook. The LLM resolves relative dates ("last Tuesday", "yesterday") against today's date. If `when` cannot be determined, it is explicitly `null` with a `when_source` of `unknown`, not inferred from ingest time unless the LLM says so explicitly.

### 4.2 No hallucination — the open-questions queue

When content is ambiguous (name mumbled in a voice memo, unclear sender on a screenshot, `"J"` that could be Jerome or Jasper), the LLM must not guess. It emits an entry into `~/brain/open_questions.md`:

```markdown
- [ ] Who is "J" in [item 2f3a…](items/meta/2f3a.json)? Context: "call w/ J at 3pm" — 2026-04-18
```

The dependent extraction (whatever hook needed "J" resolved) is skipped. The rest of the item is processed normally. When the user answers the question, the item is re-queued for extraction with the answer as an item note.

### 4.3 Diff-aware updates

Before writing to `self.md` or to any entity page section, the LLM receives the existing content and outputs a diff operation: `append`, `replace_section`, or `revise`. Blind appends are forbidden. When stance or facts change (user previously said FluentCRM was neutral, now says it's bad), the output is a `revise` that records the change in the changelog with a one-line summary.

## 5. Item kinds — routing at the front door

Not everything a user shares is about them. A receipt is not a thought; a news article isn't a preference. The LLM classifies each item into one of four kinds as the first field of its extraction output, and the rest of the extraction is shaped accordingly.

| Kind | Examples | What gets extracted | Where it lands |
|---|---|---|---|
| `personal` | Notes, thoughts, voice memos, whiteboard photos, conversations | Full hook set + self updates + entity hooks with stance | `self.md`, `entities/*.md`, `items/meta/` |
| `reference` | Articles, papers, books, tutorials, docs the user wants to remember | Neutral ≤1-paragraph summary + "why saved" + hooks into the user's world | `entities/*.md` (with `summary_external` frontmatter key), `items/meta/` |
| `record` | Receipts, bills, tickets, invoices, confirmations | Structured fields: `amount`, `vendor`, `date`, `category`, `due_date`, `reference_id`. No narrative. | `records/<date>-<vendor>.json`, `items/meta/` |
| `signal` | News articles, tweets, random links that caught the eye | One-line takeaway + topic hooks. **No entity page created.** Matches against existing entities as a dated mention. Graduates to a first-class entity after 3 mentions or explicit user promotion. | `signals/<YYYY-MM>.md`, `items/meta/` |

This routing is what prevents the current system's noise pollution — a single Twitter bookmark about FluentCRM no longer produces a FluentCRM entity page with a wrong "preference" attached.

## 6. Ingest pipeline — one LLM call per item

Replaces the current classify → extract → resolve → link → consolidate → find_insights → render chain.

### 6.1 Inputs assembled by the ingester

1. `self.md` as one string (~few KB, always under the prompt budget).
2. Top-K (default 20) existing entities by vector similarity over the item's embedded text. No type filter — cross-type matching catches `Pilot Path` (company) vs `Pilot Path Group` (organization).
3. The item: full extracted text, plus original bytes for image/audio if the active LLM supports vision/audio.
4. Any `item_notes` the user attached.
5. Today's date (as of 2026-04-19).

### 6.2 The tool schema

One tool, `process_item`, with this shape:

```jsonc
{
  "kind": "personal | reference | record | signal",

  "interpretation": {
    "what_happened": "one paragraph describing what this item is",
    "when": {
      "iso": "YYYY-MM-DD or YYYY-MM-DDTHH:MM, or null",
      "source": "explicit_in_content | inferred_from_metadata | ingest_time | unknown",
      "note": "short explanation, e.g. 'content says last Tuesday, ingest 2026-04-18, resolved to 2026-04-15'"
    },
    "confidence": 0.0
  },

  "open_questions": [
    {
      "question": "Who is 'J' in this note?",
      "context_snippet": "…call w/ J at 3pm…",
      "blocks": ["hook:who:J"]
    }
  ],

  "hooks": {
    "who": [ {"name": "Sarah", "match_existing_id": "uuid or null", "merge_aliases": ["Sarah M."]} ],
    "what": [ /* same shape */ ],
    "where": [ /* same shape */ ],
    "when": "ISO or null (redundant with interpretation.when for convenience)",
    "source": "telegram | share_sheet | drag_drop | email_in | voice",
    "project": ["Pacific"],
    "stance": [
      {"entity_name": "FluentCRM", "value": "negative", "evidence_quote": "verbatim span"}
    ]
  },

  "self_updates": [
    {
      "slot": "preferences | people | projects | goals | context | beliefs | timeline",
      "operation": "append | replace_section | revise",
      "section_heading": "## FluentCRM",
      "new_content": "markdown with [^item_id] footnotes",
      "change_summary": "flipped stance: was neutral, now negative",
      "cites": ["<item_id>"]
    }
  ],

  "entity_updates": [
    {
      "match_existing_id": "uuid or null",
      "merge_aliases": ["PilotPath", "Pilot Path Group"],
      "canonical_name": "Pilot Path",
      "entity_type": "company",
      "summary_external": "optional, for reference kind only",
      "section_update": {
        "operation": "append | replace_section | revise",
        "section_heading": "## Your history",
        "new_content": "markdown with [^item_id] citations",
        "change_summary": "added note about meeting outcome"
      },
      "related_entity_names": ["Manoj", "Pacific"]
    }
  ],

  "structured_fields": {
    /* record kind only */
    "amount": 42.50, "currency": "USD", "vendor": "Uber",
    "date": "2026-04-15", "category": "transportation",
    "due_date": null, "reference_id": "INV-00123"
  },

  "signal": {
    /* signal kind only */
    "topic_entities": ["Anthropic"],
    "one_line_takeaway": "Claude 4.7 ships with 1M context on Opus."
  }
}
```

### 6.3 What the ingester does with the tool output

1. Apply `merge_aliases`: fold names into the matched entity's aliases; if multiple existing entities collapse, one survives and the others are `git mv`'d into the survivor with their history preserved in changelog.
2. For each `entity_updates[].section_update`, patch `entities/<slug>.md` by the three diff operations.
3. For each `self_updates[]`, patch the named section of `self.md`.
4. Append `open_questions[]` to `open_questions.md`.
5. For `record` kind: write `records/<date>-<vendor>.json`.
6. For `signal` kind: append to `signals/<YYYY-MM>.md` and increment a `signal_mentions` counter on each matched entity's frontmatter. If an unmatched topic crosses 3 mentions in the rolling 90-day window, promote it to a first-class entity at `entities/<slug>.md` with `summary_external` populated from its signal takeaways. The user can also explicitly promote via the UI.
7. Index hooks in `index/vectors.sqlite` (via `sqlite-vec`): item embedding plus per-entity references.
8. Write `items/meta/<uuid>.json` with everything the LLM said about this item for auditability.
9. Append a one-line changelog entry per patched file.
10. `git add -A && git commit -m "ingest <item_id>: <summary>"` in `~/brain/`.

An ingest is atomic at the commit level: if anything fails mid-way, the last good commit is still there, and `git reset --hard` recovers.

## 7. Retrieval — three surfaces, all first-class

Memory is reconstructive, so no single entry point wins. The app exposes three views; all are wired to the same search backend.

### 7.1 Ranked candidate list (B) — default

The user types a fragment. The backend runs multi-signal match against items:

- Keyword (sqlite FTS5 over `items/meta/*.extracted_text`)
- Embedding (sqlite-vec nearest neighbours on item vectors)
- Hook match (exact or fuzzy match against `who` / `what` / `where` / `project`)
- Temporal phrase extraction (if the fragment contains "last October" etc., filter by `when` hook)

Scores are combined (not a complex learned ranker — a weighted sum is enough). The UI shows the top 10 with: excerpt, source, date, and a "why this matched" strip (`matched 'Sarah' + 'analytics' + March 2025`). The user recognizes and clicks.

### 7.2 Cluster view (C) — exploratory

Same query, different visualization. The result is rendered as a force-directed graph: the query fragment at the centre, candidate items and their hook entities arrayed around it, edges showing the hooks that linked them. The user browses outward from the fragment until they find the thread they were looking for.

Reuse: the existing canvas's force-directed SVG code is the right starting point. Layout math keeps, node and edge semantics change.

### 7.3 Chat (D) — escape hatch

When B and C don't land, the user opens a chat panel. Chat is an agent session — see Section 8.

## 8. The agent runner — M3 owns the conversation

Chat and ingest share the same infrastructure: a provider-agnostic agent runner that streams to/from an LLM and executes M3-defined tools against `~/brain/`.

### 8.1 The tool set M3 exposes to any agent

```
search_brain(query, filters) → ranked list (same backend as retrieval surface B)
open_item(id) → raw item + metadata + extracted text
open_entity(name) → items that hook to this entity + overview
list_timeline(range) → items within a date window
list_open_questions() → unresolved queue
propose_update_self(slot, operation, content, cites) → queued, user confirms
propose_entity_update(name, ...) → queued, user confirms
answer_open_question(id, answer) → resolves question, re-queues affected items
```

These are the entire surface area the LLM sees. Ingest uses a subset (`propose_update_self`, `propose_entity_update`, `answer_open_question`, implicitly via the extraction tool schema). Chat uses all of them.

### 8.2 LLM providers

**Subscription-backed providers are excluded. The Anthropic policy change of 2026-04-04 explicitly prohibits third-party tools from running against Claude Pro/Max subscription tokens. M3 must not implement the `ClaudeCode` provider that was in earlier drafts.**

Supported providers:

| Provider | How | Default for |
|---|---|---|
| `Ollama` | Local HTTP on `:11434` | Recommended default. Zero-config if Ollama is running. Free, offline. |
| `Anthropic` | Direct HTTPS with user-supplied API key | Quality upgrade for users willing to pay per-token |
| `OpenAI` / OpenAI-compatible | Direct HTTPS with user-supplied API key | Alternative quality upgrade |
| *(Claude Max via `claude` CLI)* | **Not supported. Violates Anthropic ToS.** | — |
| *(ChatGPT Plus via `codex` CLI)* | Not supported pending OpenAI ToS verification; default to "no" until proven otherwise. | — |

First-run detection: check `localhost:11434` → if alive, preselect Ollama. Otherwise prompt the user to install Ollama *or* paste an API key. Provide a "compare cost" note for API users: typical personal ingest ≈ 50 items/day × ~$0.05/item at Sonnet rates ≈ $75/month in the heavy case. A lightweight local model on Ollama is free but lower-quality extraction (see risks §13).

### 8.3 "Open in Claude Code" — user-driven escape hatch

M3 offers a menu action `Open this brain in Claude Code`. It launches the system `claude` binary with `cwd=~/brain/`. From that point on, the user is in Claude Code, using their own subscription, and M3 is no longer in the loop. M3 does not inject tools, system prompts, or automation. This is a shortcut to the official product, not a wrapper. Acceptable under Anthropic's policy because the user is driving interactively.

### 8.4 Persona

M3 has a system prompt establishing the M3 persona, loaded for every agent call regardless of provider. The user sees "M3" in the chat header, not "Claude" or "GPT". Responses are grounded via the tool set; M3 refuses to answer from parametric knowledge alone when the question is about the user's brain.

## 9. Data layout — `~/brain/` as the schema

```
~/brain/
├── self.md                          # fixed slots: ## Preferences / ## People / ## Projects / ## Goals / ## Context / ## Beliefs / ## Timeline
├── entities/
│   └── <slug>.md                    # YAML frontmatter (type, aliases, related[], summary_external) + markdown body
├── items/
│   ├── originals/<uuid>.<ext>       # raw bytes as shared
│   └── meta/<uuid>.json             # {kind, source, created_at, when, extracted_text, hooks, llm_output_raw}
├── records/<YYYY-MM-DD>-<vendor>.json   # structured receipts / bills / tickets
├── signals/<YYYY-MM>.md             # month-per-file log of news / tweets / signal items
├── open_questions.md                # checklist, tied to item ids
├── changelog.md                     # append-only, one line per file patch
├── index/
│   └── vectors.sqlite               # sqlite-vec: item vectors + entity vectors + FTS5 over extracted_text
├── config.yml                       # llm provider choice, capture settings, api keys (stored with OS keychain integration, yaml holds only the keychain reference)
└── .git/                            # auto-committed after every ingest
```

Everything derived is in files. No database. No docker. No worker process. `rm -rf entities/ records/ signals/ index/` plus `m3 reprocess` rebuilds the entire brain from the items. This is the clean-slate migration: Section 11.

## 10. App shell — Tauri + React, one binary

Distributed as:

- Mac: `.app` bundle, notarized
- Linux: `.AppImage` and `.deb`

Internals:

- Tauri shell (Rust) manages window, menu, single-instance, filesystem permissions, updater.
- Python runtime bundled via `python-build-standalone` — a stripped Python interpreter shipped inside the app bundle. No system Python dependency.
- The Python backend runs as a Tauri-managed subprocess on a random localhost port. The Rust shell proxies HTTP to it.
- The existing React client (already present under `client/`) is compiled to static assets served by Tauri. Chat SSE and canvas force-directed math are kept; the wiki-page, entity-page, and library-as-inbox views are rewritten for the new hook-based model.
- Embeddings use `fastembed` (already a dependency); `sqlite-vec` is loaded via its Python bindings.

Why Tauri over Electron: smaller bundle (10–15 MB vs 100+), lower memory, actively maintained, first-class Rust ecosystem for desktop primitives.

Why React kept (vs rewrite in Svelte/Solid): the UX changes we need are layout changes, not framework changes. The canvas force-directed code is reusable. Rewriting the client buys nothing that moves the product forward.

## 11. Migration: clean slate

There is no data migration. The current Postgres/MinIO/Redis stack is replaced end-to-end. The plan:

1. Export raw items out of the current Postgres/MinIO into `~/brain/items/originals/` and `~/brain/items/meta/` (one-time script; items are the only things worth preserving; `wiki_pages`, `entity_facts`, `entity_links`, `insights`, `wiki_schema`, `changelog`, all old derived tables are dropped).
2. Run `m3 reprocess` end-to-end: the new pipeline walks every item and produces fresh entities, hooks, self, records, signals.
3. Tear down the old Docker stack permanently.

All user-facing wiki pages, graphs, and insights currently in the running system are assumed to be garbage and disappear. This is the explicit decision: the complexity was producing wrong output, so preserving it would preserve garbage.

## 12. What's deleted from the current repo, what stays

**Delete:**

- `server/migrations/` (no Alembic)
- `server/m3/storage/database.py` (no Postgres)
- `server/m3/storage/files.py` (no MinIO)
- `server/m3/storage/cache.py` (no Redis)
- `server/m3/storage/models.py` (no SQLAlchemy)
- `server/m3/storage/user_settings.py` (moves into `config.yml`)
- `server/m3/core/compiler.py` (rewritten as `core/ingest.py`)
- `server/m3/core/engines/basic.py` (rewritten as `core/extract.py` — one tool-call)
- `server/m3/core/engines/loader.py` (no pluggable engines)
- `server/m3/core/entity_resolver.py` (LLM handles inline via `match_existing_id` / `merge_aliases`)
- `server/m3/core/insight_engine.py` (no insights pass; D capabilities come later)
- `server/m3/workers/` (no worker process)
- `docker-compose.yml`, `Dockerfile`, `Caddyfile`
- Client views: `wiki pages`, `entity detail`, `library as raw-inbox-browser` — replaced by hook-based views

**Keep (with changes):**

- `server/m3/core/extractors.py` — PDF/DOCX/XLSX/PPTX/HTML/EPUB text extraction. Unchanged.
- `server/m3/core/llm.py` — trim provider list (remove Anthropic-via-subscription paths), add `Ollama` provider, keep `Anthropic`/`OpenAI` API-key providers.
- `server/m3/capture/telegram.py` — refactored to write to `~/brain/items/` instead of enqueueing ARQ jobs.
- `server/m3/schemas/api.py` — Pydantic shapes mostly stay; the client depends on them.
- `client/` — React app kept, canvas force-directed graph kept, SSE chat kept, settings/layout kept. New views: fragment search (B), cluster retrieval (C), open-questions screen, per-entity-hook browser.

**New modules:**

- `server/m3/brain/` — filesystem I/O for `~/brain/`:
  - `layout.py`, `self_doc.py`, `entity_doc.py`, `items.py`, `records.py`, `signals.py`, `questions.py`, `changelog.py`, `git.py`, `vectors.py` (sqlite-vec wrapper)
- `server/m3/core/ingest.py` — the one-LLM-call per item orchestrator
- `server/m3/core/extract.py` — system prompt + tool schema for `process_item`
- `server/m3/core/agent.py` — provider-agnostic agent runner with tool loop
- `server/m3/core/tools.py` — the M3 tool set (search_brain, open_item, etc.)
- `server/m3/core/llm/ollama.py` — new Ollama provider
- `server/m3/api/retrieval.py` — B (ranked) + C (cluster) endpoints
- `server/m3/api/questions.py` — open questions CRUD
- `server-tauri/` — new Tauri shell

## 13. Risks and mitigations

### 13.1 Local model tool-use reliability

Ollama models are weaker than Sonnet at strict tool-use. Risk: extraction schema violations, missed hooks, worse stance detection.

Mitigation:
- Fallback JSON-with-repair path (similar to current `_extract_fallback`) for local models.
- Recommend a tool-use-capable model (`qwen2.5` family, `llama3.1:70b`) in first-run setup.
- Surface extraction confidence in the UI. When confidence is low, prompt the user to verify the extraction inline. Low-confidence extractions are a gentler form of an open question.
- Document the quality gap in the first-run wizard. Users who care about accuracy get a clear pointer to the API-key upgrade path.

### 13.2 Cost surprise on API-key mode

50 items/day × Sonnet-sized extraction ≈ $1–3/day ≈ $30–90/month. Reasonable for an active user, but it's still real money.

Mitigation:
- Show running cost estimate in settings.
- Default to local Ollama.
- Batch low-priority items (signals, records) with the cheapest tier of the active provider.

### 13.3 Anthropic policy drift

Anthropic's policy around third-party subscription use changed in Feb/Apr 2026. Further restrictions are possible (e.g., API terms for agent tools).

Mitigation:
- Document the current policy boundary in the repo README; review before each release.
- Keep the LLM abstraction clean so replacing a provider is one file.
- The "Open in Claude Code" shortcut is documented as user-driven and unsupervised.

### 13.4 Rebuild scope creep

A rebuild is the moment to add features. It is also the moment to ship nothing for three months.

Mitigation:
- First milestone: deliberate-capture ingest + B (ranked retrieval) + basic entity pages + self. No canvas, no chat, no open-questions-queue UI. Prove the extraction is accurate.
- Second milestone: C (cluster) and open-questions UI.
- Third milestone: D (chat agent).
- Reflecting (D as a stacked capability) and Acting (E) are out of scope entirely for this spec.

## 14. Success criteria

The rebuild is done when all of these hold on real user data:

1. Sharing a note where the user expresses *dislike* of a tool results in a `negative` stance being attached, not a `preferences.likes` entry.
2. Sharing three items that mention `PilotPath`, `Pilot Path`, and `Pilot Path Group` results in one entity, not three.
3. Sharing a voice memo with an ambiguous name produces an open question, not a guessed person.
4. The self page is non-empty after ~10 personal items ingested, with all seven slots showing user-specific content (not generic boilerplate).
5. Typing a fragment of something the user remembers ("sarah coffee october") returns the relevant item in the top 3 candidates.
6. Ingest of a receipt produces a `records/*.json` entry with the amount/vendor/date filled, and does *not* produce a narrative wiki page about the vendor.
7. Ingest of a news article produces a `signals/<month>.md` entry, not an entity page about the headline.
8. `rm -rf ~/brain/entities ~/brain/records ~/brain/signals ~/brain/index && m3 reprocess` rebuilds the brain from items with no manual intervention.
9. The full app installs as a single `.app` bundle on macOS (or `.AppImage` on Linux) with no Docker, no Postgres, no external services.
10. Default LLM path works offline with Ollama installed; API-key path works when a user provides one. No subscription path is implemented.

## 15. Explicit non-goals

- Multi-user / team / hosted deployment
- Windows support (not Phase 1)
- Mobile clients (Telegram bot is the mobile path for now)
- Passive stream ingestion (email, calendar, photo library, browser history)
- The "Reflecting" (D) layer beyond open questions
- The "Acting" (E) layer entirely
- Migrating existing derived data (pages, facts, insights) from the current Postgres
- Any use of Claude Pro/Max subscription via M3
- Any feature flag or config to enable subscription-backed providers in future; if that changes, it's a separate decision with a separate legal review

---

*End of design.*

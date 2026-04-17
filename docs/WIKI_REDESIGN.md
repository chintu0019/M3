# Wiki Redesign: Entity-Centric Knowledge Graph

> **Tracking document.** Update the status/progress fields and checkboxes as work lands. This persists across sessions.

## Why

M3's current wiki treats every uploaded item as a page source. `BasicEngine.compile()` produces wiki page updates per-item, so the wiki ends up as near-duplicate summary pages named after source documents. `synthesize()` only runs weekly. The result is a pile of summaries, not a knowledge graph.

**Target:** A "second brain" organized around entities and concepts (project Kato, person John, concept "LLM caching"), not source documents. Each entity page is a living synthesis of everything mentioning it. The LLM extracts structured facts and attaches them to entities. Insights surface automatically.

---

## Overall Progress

| Phase | Description | Status | Branch/Commits |
|-------|-------------|--------|----------------|
| 1 | Schema + Models | **DONE** | `f414e33`..`0f2cded` |
| 2 | Extract Pipeline + Entity Resolver (capability-aware) | **DONE** | `4bbf96b`, `64e3fd5` |
| 3 | Entity Renderer + Type Consolidation | **DONE** | `e86aa0e`..`fa5f513` |
| 4 | API + Insight Feed (graph-aware) | **DONE** | Phase 4 commits |
| 5 | Wiki View Rebuild + Graph View | **DONE** | Phase 5 commit |
| 6 | Backfill + Flip Default | **DONE** | Phase 6 commit |
| 7 | Cleanup Legacy Code | **DONE** | Phase 7 commit |

Entity mode is the only pipeline. The `wiki_mode` flag, document-pipeline
methods, legacy `/api/v1/wiki` endpoints, and the old wiki UI are gone.

## Design principle: capability-aware engines

The redesign stops baking small-model habits (many short prompts, JSON repair
retries, character-capped context, hardcoded type whitelists, text-only input)
into the engine ABC. Instead, `LLMProvider` advertises `supports_tools`,
`supports_vision`, `supports_audio`; `CompilationEngine` advertises an
`EngineCapabilities` record; and BasicEngine picks the shortest path at
runtime.

- Anthropic Sonnet/Opus -> one tool-use call returns entities + facts +
  semantic relationships in a schema-validated payload, consumes raw image
  / audio directly, no 6k character cap, no JSON-repair retry.
- OpenAI-compatible cloud providers with tool support -> same path.
- Local Ollama / models without tool support -> fall back to the two-call
  JSON-repair path with a character cap. This is the local-safe mode; it's
  there so the system still works, not the headline design.

Entity / fact / role types are suggestions, not walls. Migration 004 drops
the implicit whitelists and adds dim tables (`entity_types`, `fact_types`,
`fact_roles`) so a later `consolidate_types()` pass can merge near-duplicates
the same way `evolve_schema` reorganises the wiki.

---

## Phase 1: Schema + Models -- DONE

**What:** Foundation tables, ORM models, feature flag, extract() stub. No runtime behavior change.

**Commits:**
- [x] `f414e33` -- migration 003: entities, entity_facts, entity_fact_links, entity_links, insights + wiki_pages.legacy
- [x] `b8bc31b` -- ORM models: Entity, EntityFact, EntityFactLink, EntityLink, Insight
- [x] `39263bd` -- `processing.wiki_mode` feature flag (default "document")
- [x] `0f2cded` -- CompilationEngine.extract() stub + EntityMention, ExtractedFact, ExtractionResult dataclasses

**Key files:**
- `server/migrations/versions/003_entity_centric_wiki.py`
- `server/m3/storage/models.py`
- `server/m3/config.py`
- `server/m3/core/engines/base.py`

---

## Phase 2: Extract Pipeline + Entity Resolver -- IN PROGRESS

**What:** Capability-aware entity extraction running alongside the document
pipeline in shadow mode. The LLMProvider surface gains tool use + multimodal
flags; BasicEngine's `extract()` picks a one-call tool-use path when the
provider supports it and falls back to the original two-call JSON-repair
path otherwise.

**Detailed plan:** `docs/superpowers/plans/2026-04-16-wiki-redesign-phase-2-extract-pipeline.md`
(revised 2026-04-16 for capability-aware design).

- [x] **Task 0: LLMProvider capability surface** -- `server/m3/core/llm.py`
  - `supports_tools` / `supports_vision` / `supports_audio` flags
  - `complete_tool(messages, tools, tool_choice)` returning parsed `ToolResult`
  - Anthropic: always capable; OpenAI-compatible: configurable per provider

- [x] **Task 1: Organic type vocabularies** -- migration 004 + ORM
  - Drops whitelists, adds `entity_types` / `fact_types` / `fact_roles` dim
    tables with `usage_count` and `merged_into` for future consolidation

- [x] **Task 2: Widen CompilationEngine ABC** -- `server/m3/core/engines/base.py`
  - `ContentBlock` union (TextBlock / ImageBlock / AudioBlock), `content_to_text()`
  - `EngineCapabilities` dataclass
  - `ExtractionResult.relationships: list[ProposedRelationship]`
  - `find_insights()` + `consolidate_types()` default no-ops

- [x] **Task 3: Entity Resolver** -- `server/m3/core/entity_resolver.py`
  - Layered: exact/alias -> trigram (pg_trgm >= 0.50) -> embedding (cosine >= 0.78) -> LLM disambiguation
  - Tool-use disambiguation when provider supports it; letter-pick fallback otherwise
  - Type-scoped, auto-merge threshold 0.88

- [x] **Task 4: BasicEngine.extract()** -- `server/m3/core/engines/basic.py`
  - Capable path: one tool-use call returning entities + facts + relationships (schema-validated, no 6k cap)
  - Fallback path: two short LLM calls + JSON-repair retry for local models
  - Multimodal: image / audio blocks passed straight to the LLM when vision / audio is supported

- [x] **Task 5: Compiler._persist_extraction + wiki_mode branch** -- `server/m3/core/compiler.py`
  - Resolve mentions, insert facts + fact_links, bump dim-table usage counts
  - Upsert entity_links from both co-occurrence (fallback) and engine-proposed relationships (capable)
  - `process_item` branches on wiki_mode: "document" / "entity" / "both"; errors in one mode don't block the other

- [ ] **Task 6: End-to-end smoke test**
  - wiki_mode="both", ingest meeting note, verify entities + facts + relationships + wiki page
  - Ingest receipt image (Anthropic provider) and confirm multimodal extraction populates vendor entity
  - Two items mentioning same entity -> one entity row
  - Clean up, revert flag

---

## Phase 3: Entity Renderer + Type Consolidation -- DONE

**What:** Background worker regenerates dirty entity pages from facts, and a
periodic `consolidate_types()` pass merges near-duplicate vocabulary entries.
Plus a minimal read API so pages are reachable over HTTP.

**Detailed plan:** `docs/superpowers/plans/2026-04-17-wiki-redesign-phase-3-entity-renderer.md`

- [x] **Task 1: Render engine method** -- `base.py` ABC + `basic.py`
  - `RenderedPage` dataclass on ABC
  - Capable path: single tool-use call (`RENDER_TOOL_SCHEMA`), all facts
  - Fallback path: LLM summary of older facts + deterministic cited bullet list of recent 30
- [x] **Task 2: Renderer module** -- `server/m3/core/entity_renderer.py`
  - Picks dirty entities `ORDER BY facts_since_render DESC, updated_at ASC`
  - Loads facts + bidirectional related entities
  - Regex-validates `[^<item_id>]` citations; bogus ones trip a deterministic template fallback
  - Per-entity commit for fault isolation
- [x] **Task 3: `consolidate_types`** -- `basic.py` + `server/m3/core/type_consolidator.py`
  - Capable path: tool-use call with `CONSOLIDATE_TOOL_SCHEMA`
  - Applier writes `merged_into` on the dead row and rewrites base tables to the canonical name
  - Local fallback is a deliberate no-op (local models do this badly)
- [x] **Task 4: Background cron** -- `server/m3/workers/tasks.py`
  - `render_dirty_entities_task` every 5 minutes
  - `consolidate_types_task` daily at 04:00 UTC
- [x] **Task 5: Minimal read endpoint** -- `server/m3/api/entities.py`
  - `GET /api/v1/entities` (paginated, optional `entity_type` filter)
  - `GET /api/v1/entities/{id}` (detail with `page_content`, `page_overview`, top 10 related)
- [x] **Task 6: End-to-end smoke**
  - Ingest -> render -> pages persisted with valid citations
  - Re-ingest flips `page_dirty=true`; next render updates overview to latest fact
  - Drift-seed + consolidate clean no-op against local model (capable-path merges
    gated on a capable provider)

---

## Phase 4: API + Insight Feed -- DONE

**What:** Insight pass after every entity-mode ingest, scoped to the 2-hop
neighbourhood of touched entities; endpoints for entities (list/detail) and
insights (list/filter/PATCH status); entity detail grows to carry open
insights referencing that entity.

**Detailed plan:** `docs/superpowers/plans/2026-04-17-wiki-redesign-phase-4-insights.md`

- [x] **Task 1: `BasicEngine.find_insights`** -- `basic.py`
  - Capable path: one tool-use call (`INSIGHTS_TOOL_SCHEMA`) covering all seven categories
  - Fallback path: deliberate no-op (local models hallucinate patterns)
  - Grew `Insight` dataclass with `related_entity_names` + `related_item_ids`
- [x] **Task 2: Insight engine orchestrator** -- `server/m3/core/insight_engine.py`
  - 2-hop neighbourhood walk via `entity_links`
  - Recent-facts loader (cap 20 per entity)
  - Name -> id resolution preferring the touched/neighbourhood set
  - Dedup against existing `(insight_type, sorted(related_entity_ids))` in new/acknowledged status
- [x] **Task 3: Compiler hook** -- `server/m3/core/compiler.py`
  - `_persist_extraction` now returns `(facts, touched_entity_ids)`
  - `_run_entity_mode` calls `find_for_touched` after persist; errors logged, never raise
  - Bonus: dedup entity refs per fact on resolved entity id (LLM sometimes
    emits the same entity twice with different roles; PK violation fixed)
- [x] **Task 4: `/api/v1/insights`** -- `server/m3/api/insights.py` + `schemas/api.py`
  - GET list (status + insight_type filters, pagination)
  - PATCH status (new | acknowledged | dismissed)
- [x] **Task 5: Entity detail includes open insights** -- `api/entities.py`
- [x] **Task 6: End-to-end smoke**
  - API CRUD against seeded rows (list/filter/PATCH/400 on bad status)
  - Ingest in wiki_mode=both against ollama: entity mode succeeds, worker
    logs `find_insights skipped`, zero insight rows (capable-path rows
    gated on a real provider key)

---

## Phase 5: Wiki View Rebuild + Graph View -- DONE

**What:** Frontend switches from document-backed wiki to entity-backed
views, adds a force-directed graph of the entity link structure, and a
full insights feed. Legacy /wiki stays reachable during Phase 6.

- [x] **Task 1: Backend graph endpoint** -- `/api/v1/entities/graph`
  (nodes with fact_count, edges with weight, optional type filter, node cap)
- [x] **Task 2: Frontend API client** -- `api.entities.*`, `api.insights.*`,
  TS types for EntitySummary/Detail, InsightSummary, EntityGraph
- [x] **Task 3: Entities view** -- `client/src/views/Entities.tsx`
  - Three-pane: sidebar (grouped by type + filter + search), main
    (page_content markdown with [^<uuid>] -> clickable /library/:id),
    right rail (related + open insights with ack/dismiss)
- [x] **Task 4: Insights view** -- `client/src/views/Insights.tsx`
  - Status tabs (new/acknowledged/dismissed/all), type filter,
    per-card ack/dismiss/reopen, entity deep-links
- [x] **Task 5: Interactive graph** -- `client/src/views/Graph.tsx`
  - d3-force simulation, React-rendered SVG (positions updated via state
    on every tick), drag, pan/zoom, click-to-navigate, type filter,
    hover tooltip, radius scaled by fact_count
- [x] **Task 6: Nav + routing** -- App.tsx: `/entities`, `/entities/:id`,
  `/graph`, `/insights`. `/wiki` kept reachable during Phase 6 transition.
- [x] **Task 7: Browser smoke** -- seeded 3 entities + 1 insight, verified
  via playwright: entities list, detail with citations, graph with nodes
  and edges, insights feed PATCH flow (new → acknowledged → visible
  across views).

---

## Phase 6: Backfill + Flip Default -- DONE

**What:** Re-processed existing items through the entity pipeline and flipped the
default so new ingests stop double-writing.

**Detailed plan:** `docs/superpowers/plans/2026-04-17-wiki-redesign-phase-6-backfill.md`

- [x] **Backfill script** -- `server/m3/scripts/backfill_entities.py`
  - `--dry-run` reports what would happen
  - Idempotent (skips items that already have `entity_facts`)
  - Per-item commit, `--delay` pacing, `--limit` cap
  - `--mark-legacy-only` runs just the wiki_pages sweep
- [x] **Legacy flag sweep** -- `UPDATE wiki_pages SET legacy=true WHERE page_type != '_index'`
- [x] **Flip default** -- `ProcessingSettings.wiki_mode: "document"` → `"entity"`
- [x] **End-to-end smoke**
  - 14 pre-existing items backfilled: 66 entities, 120 facts, 18 edges
  - Re-run reports "0 items to process, 14 already skipped"
  - Legacy sweep flags 42 wiki_pages
  - Fresh ingest under new default produces entities only (0 legacy pages)

---

## Phase 7: Cleanup Legacy Code -- DONE

**What:** Removed the document pipeline now that entity mode is the only
path. Chat ported to entity-based retrieval (hybrid semantic + FTS over
`entities.embedding` + canonical_name / aliases / description / page_overview),
citations switched from `[[Page Title]]` to `[[Entity Name]]` resolved
against canonical_name and aliases.

- [x] Drop `classify() / compile() / synthesize()` from `BasicEngine` +
      related dataclasses (Classification / PageUpdate / LinkUpdate /
      CompileResult / SynthesisResult) from the engine ABC.
- [x] Remove `_run_document_mode` and all doc helpers from `Compiler`
      (`_write_page`, `_upsert_link`, `_update_wiki_index`,
      `_find_related_pages`, `_get_wiki_*`, `_get_existing_*`).
- [x] Remove the `wiki_mode` flag from `ProcessingSettings` and the
      Compiler constructor; `process_item` runs one path now.
- [x] Delete `compile_pass` / `deep_compile` ARQ tasks + crons; replace
      the startup pass with a simpler `drain_pending_items` sweep.
- [x] Delete `server/m3/api/wiki.py` and unregister its router.
- [x] Port chat + `SearchEngine` to `entities` (hybrid vector + FTS).
- [x] Delete `client/src/views/Wiki.tsx`, `/wiki` routes, the
      `Wiki` NavLink, `api.wiki.*`, plus `WikiPagesList` and
      `ClassificationCard` (replaced by a minimal `UserInputsCard`).
- [x] Migration 005: drop `wiki_pages`, `wiki_links`, `wiki_schema`,
      `changelog` tables and `entities.legacy_page_id` column.
- [x] Delete obsolete `backfill_entities.py` script.
- [x] Drop `WikiPageLinkedToItem` / linked_wiki_pages / legacy Wiki
      schemas from `schemas/api.py` and the library detail flow.

---

## Architecture Reference

### Entity Resolution (core magic)

Type-scoped. A person "Kato" never merges with project "Kato AI".

```
1. Exact match (case-insensitive canonical_name or alias, same type)
2. Trigram candidates (pg_trgm similarity >= 0.50, top 5)
3. Embedding candidates (cosine sim >= 0.78, top 5)
4. Merge + score (0.4 * trigram + 0.6 * embedding)
5. Auto-merge if one candidate >= 0.88
6. LLM disambiguation if multiple candidates
7. Create new if none
```

### Data Flow

```
raw_item -> extract() -> [EntityMention[], ExtractedFact[]]
                              |
                    entity_resolver.resolve_mention()
                              |
                    Entity row (existing or new)
                              |
                    EntityFact + EntityFactLink rows
                              |
                    EntityLink co-occurrence upsert
                              |
                    entity.page_dirty = true
                              |
              (background) -> render_entity() -> entity.page_content
                              |
              (after ingest) -> find_insights() -> Insight rows
```

### Key Design Principles

1. **Facts, not summaries** -- LLM extracts structured claims, prose comes from rendering
2. **Entity resolution is the magic** -- merging "Kato" and "Kato AI" is what makes this a second brain
3. **Never hallucinate** -- every fact grounds in the source, anti-hallucination hardcoded in prompt
4. **Graceful degradation** -- LLM failures never block item processing
5. **Local-model safe** -- short calls, JSON schema, retry-with-repair
6. **Shadow mode first** -- new pipeline runs alongside old before flipping default

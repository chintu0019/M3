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
| 2 | Extract Pipeline + Entity Resolver (capability-aware) | **IN PROGRESS** | -- |
| 3 | Entity Renderer + Type Consolidation | NOT STARTED | -- |
| 4 | API + Insight Feed (graph-aware) | NOT STARTED | -- |
| 5 | Wiki View Rebuild | NOT STARTED | -- |
| 6 | Backfill + Flip Default | NOT STARTED | -- |
| 7 | Cleanup Legacy Code | NOT STARTED | -- |

**Feature flag:** `settings.processing.wiki_mode` -- `"document"` (default), `"entity"`, `"both"` (shadow mode)

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

## Phase 3: Entity Renderer + Type Consolidation -- NOT STARTED

**What:** Background worker regenerates dirty entity pages from facts, and a
periodic `consolidate_types()` pass merges near-duplicate vocabulary entries.

- [ ] **Task 1: Render engine method** -- `base.py` ABC + `basic.py` prompt
  - Capable path: pass all facts in one call, Wikipedia-style synthesis with `[^item_id]` citations, no tiering
  - Fallback path: tiered (overview of older facts + raw recent 30 + citations)

- [ ] **Task 2: Renderer module** -- `server/m3/core/entity_renderer.py`
  - Pick dirty entities ordered by facts_since_render DESC
  - Validate: every `[^item_id]` must resolve to input fact's item_id
  - Fallback to deterministic template if validation fails

- [ ] **Task 3: Background cron** -- `server/m3/workers/tasks.py`
  - `render_dirty_entities` every 5 min
  - `consolidate_types` daily: review entity_types / fact_types / fact_roles, merge duplicates
  - Clear page_dirty + reset facts_since_render after render

---

## Phase 4: API + Insight Feed -- NOT STARTED

**What:** Entity + insight endpoints. Insight pass runs after every ingest.

- [ ] **Task 1: Entity API** -- `server/m3/api/entities.py`
  - GET /entities (list, filterable by type)
  - GET /entities/:id (detail with facts, related entities)

- [ ] **Task 2: Insight API** -- `server/m3/api/insights.py`
  - GET /insights (feed with status filter)
  - PATCH /insights/:id (acknowledge/dismiss)

- [ ] **Task 3: Insight engine** -- `base.py` + `basic.py`
  - find_insights() runs after every process_item, scoped to 2-hop neighbourhood of touched entities
  - Capable path: one tool-use call per ingest, emits the seven insight categories; no per-item cap
  - Dedup by (insight_type, related_entity_ids) so re-ingests don't spam
  - Weekly deep pass for graph-wide patterns

- [ ] **Task 4: Wire routers** -- `server/m3/main.py` + `server/m3/schemas/api.py`

---

## Phase 5: Wiki View Rebuild -- NOT STARTED

**What:** Frontend switches from document-backed wiki to entity-backed view.

- [ ] **Task 1: Entity-backed Wiki.tsx**
  - Sidebar: entity list grouped by type
  - Main: entity page content with fact citations
  - Right: related entities + insights for current entity

- [ ] **Task 2: Insights.tsx** -- new page for full insight feed

- [ ] **Task 3: API client** -- `api.entities.*`, `api.insights.*`

- [ ] **Task 4: Routing** -- `/insights` route, re-point wiki to entity data

---

## Phase 6: Backfill + Flip Default -- NOT STARTED

**What:** Re-process existing items, flip default to entity mode.

- [ ] Backfill script: re-run extract() over all existing raw_items
- [ ] Dry-run mode: report "would create N entities, M facts" first
- [ ] Flag old wiki_pages as legacy=true
- [ ] Flip wiki_mode default to "entity"
- [ ] User confirmation before deleting legacy pages

---

## Phase 7: Cleanup Legacy Code -- NOT STARTED

**What:** Remove document compile/synthesize after stable period.

- [ ] Drop compile() and synthesize() from BasicEngine
- [ ] Remove document-mode branch from process_item
- [ ] Remove wiki_mode flag
- [ ] Clean up legacy column / dead code

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

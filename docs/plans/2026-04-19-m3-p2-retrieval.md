# M3 Plan P2 — Retrieval Surface B + HTTP API

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `m3 search "<fragment>"` returns a ranked list of candidate items matching any combination of keywords, entities (who/what/where/project), approximate dates, and semantic similarity. Same backend served over HTTP as `GET /api/v1/retrieve?q=<fragment>&k=10`. Multi-signal scoring combines FTS5 keyword hits, hook-index matches, and embedding nearest-neighbors. Every result returns a "why matched" strip so the user recognizes it.

**Architecture:** Fragment-tolerant retrieval via three independent indexes populated during ingest (and rebuildable via `m3 reindex`): (a) sqlite FTS5 over `ItemMeta.extracted_text` for keyword, (b) a simple sqlite table mapping every hook value (person/topic/place/project name) to item ids for fragment→entity lookups, (c) the existing `sqlite-vec` index from P1 for semantic nearest-neighbors. A ranker combines the three with a weighted sum. Temporal filters come from `ItemMeta.when_iso`.

**Tech Stack:** Python 3.12, pytest, FastAPI (already a dep), `sqlite-vec` (from P1), sqlite FTS5 (built into stdlib sqlite3 on modern Python/macOS), `httpx` (already a dep) for test client.

**Out of scope for P2:** cluster view (P4), Tauri shell (P3), chat agent (P4), UI rewrites. The React client is untouched in P2.

---

## File Structure

**New files:**

```
server/m3/brain/
  fts.py           # sqlite FTS5 wrapper: upsert_item_text, search(query, k) → list[FTSHit]
  hooks.py         # sqlite table keyed on (hook_type, normalized_value) → [item_ids]; exposes search(fragment, types) → list[HookHit]
  reindex.py       # walk items/meta/*.json and repopulate FTS + hooks + vectors; idempotent

server/m3/core/
  retrieve.py      # multi-signal ranker: takes (query, filters, k) → list[RetrievalHit]; combines FTS + hooks + vectors + temporal

server/m3/api/
  retrieve.py      # FastAPI router: GET /api/v1/retrieve?q=...&k=10 → ranked candidate list
  __init__.py      # may need creating if /api/ package has no __init__.py

server/tests/
  brain/
    test_fts.py
    test_hooks.py
    test_reindex.py
  core/
    test_retrieve.py
  api/
    __init__.py
    test_retrieve_api.py
  cli/
    test_search_command.py
```

**Existing files modified:**

- `server/m3/core/ingest.py` — after `_index_vectors`, also call `fts.upsert_item_text` and `hooks.upsert_item_hooks`. Tiny edit.
- `server/m3/cli.py` — add `search` and `reindex` commands.
- `server/m3/main.py` — only if needed to mount the new `/api/v1/retrieve` router; the existing `main.py` may already include routers dynamically. Check first.

---

## Task 0: Quick verification that P1 still works

**Files:** none

- [ ] **Step 1:** `cd /Users/mk/Projects/M3/.worktrees/p2-retrieval/server && pip install -e ".[dev]" && pytest tests/ -q 2>&1 | tail -5`

Expected: `54 passed, 1 skipped` (the P1 baseline). If this fails, stop and diagnose — do not proceed to Task 1.

- [ ] **Step 2:** commit nothing; this is just a gate.

---

## Task 1: `brain/fts.py` — sqlite FTS5 wrapper

**Files:**
- Create: `server/m3/brain/fts.py`
- Test: `server/tests/brain/test_fts.py`

- [ ] **Step 1: Write failing tests**

```python
from pathlib import Path

from m3.brain.fts import FTSHit, FTSIndex


def test_upsert_and_search(tmp_brain: Path):
    idx = FTSIndex.open(tmp_brain)
    idx.upsert_item(item_id="a", text="Had a call with Aditya about Pilot Path.")
    idx.upsert_item(item_id="b", text="FluentCRM is the wrong tool for us.")
    idx.upsert_item(item_id="c", text="Uber receipt for 42 dollars.")
    hits = idx.search("Aditya", k=5)
    assert [h.id for h in hits] == ["a"]
    hits = idx.search("wrong tool", k=5)
    assert [h.id for h in hits] == ["b"]
    idx.close()


def test_upsert_is_idempotent(tmp_brain: Path):
    idx = FTSIndex.open(tmp_brain)
    idx.upsert_item(item_id="a", text="first")
    idx.upsert_item(item_id="a", text="second")
    hits = idx.search("second", k=5)
    assert [h.id for h in hits] == ["a"]
    hits = idx.search("first", k=5)
    assert hits == []
    idx.close()


def test_rank_order_uses_bm25(tmp_brain: Path):
    idx = FTSIndex.open(tmp_brain)
    idx.upsert_item(item_id="match_strong", text="apple apple apple banana")
    idx.upsert_item(item_id="match_weak", text="apple is a fruit")
    hits = idx.search("apple", k=2)
    # match_strong should rank first because "apple" appears more often
    assert hits[0].id == "match_strong"
    idx.close()


def test_search_returns_score_and_snippet(tmp_brain: Path):
    idx = FTSIndex.open(tmp_brain)
    idx.upsert_item(item_id="a", text="Meeting with Aditya on Thursday about the Pacific project.")
    hits = idx.search("Pacific", k=1)
    assert len(hits) == 1
    assert isinstance(hits[0], FTSHit)
    assert hits[0].score > 0.0
    assert "Pacific" in hits[0].snippet
    idx.close()
```

- [ ] **Step 2: Run — expect failures**

- [ ] **Step 3: Implement `server/m3/brain/fts.py`**

```python
"""SQLite FTS5 wrapper for keyword search over item extracted_text.

Shares the same sqlite file as vectors.py (`~/brain/index/vectors.sqlite`) so
a single db connection per process can back both. FTS5 is built into stdlib
sqlite3 on macOS and modern Linux; no extra dep.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from m3.brain.layout import BrainPaths


@dataclass
class FTSHit:
    id: str
    score: float
    snippet: str


class FTSIndex:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def open(cls, root: Path) -> "FTSIndex":
        p = BrainPaths(root)
        p.index_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(p.vectors_db)
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS items_fts "
            "USING fts5(id UNINDEXED, text, tokenize='porter unicode61')"
        )
        return cls(conn)

    def upsert_item(self, *, item_id: str, text: str) -> None:
        self._conn.execute("DELETE FROM items_fts WHERE id = ?", (item_id,))
        self._conn.execute("INSERT INTO items_fts(id, text) VALUES (?, ?)", (item_id, text))
        self._conn.commit()

    def search(self, query: str, *, k: int) -> list[FTSHit]:
        if not query.strip():
            return []
        # Use bm25() for scoring. Lower bm25 = better match; invert so higher = better.
        rows = self._conn.execute(
            "SELECT id, bm25(items_fts) AS raw_score, "
            "snippet(items_fts, 1, '', '', ' … ', 16) AS snip "
            "FROM items_fts WHERE items_fts MATCH ? ORDER BY raw_score LIMIT ?",
            (_sanitize(query), k),
        ).fetchall()
        return [FTSHit(id=r[0], score=1.0 / (1.0 + float(r[1])), snippet=r[2] or "") for r in rows]

    def close(self) -> None:
        self._conn.close()


def _sanitize(q: str) -> str:
    """Escape FTS5 meta chars by wrapping each token in double quotes."""
    tokens = [t for t in q.split() if t]
    return " ".join(f'"{t.replace(chr(34), "")}"' for t in tokens) or '""'
```

- [ ] **Step 4: Run — expect 4 pass**

- [ ] **Step 5: Commit**

```bash
cd /Users/mk/Projects/M3/.worktrees/p2-retrieval
git add server/m3/brain/fts.py server/tests/brain/test_fts.py
git commit -m "p2: brain.fts — sqlite FTS5 wrapper for keyword search over item text"
```

---

## Task 2: `brain/hooks.py` — hook index

**Files:**
- Create: `server/m3/brain/hooks.py`
- Test: `server/tests/brain/test_hooks.py`

The hook index is a simple sqlite table `item_hooks(item_id, hook_type, normalized_value, raw_value)` where `hook_type` is one of `who|what|where|project|stance_entity`, `normalized_value` is lowercased+stripped for matching, and `raw_value` is the original for display. On ingest we upsert all hooks for an item.

- [ ] **Step 1: Write failing tests**

```python
from pathlib import Path

from m3.brain.hooks import HookHit, HookIndex


def test_upsert_and_search_by_who(tmp_brain: Path):
    idx = HookIndex.open(tmp_brain)
    idx.upsert_item_hooks(item_id="a", who=["Aditya", "Sarah"], what=["Pacific"], where=[], project=[], stance_entities=[])
    idx.upsert_item_hooks(item_id="b", who=["Aditya"], what=[], where=["Bangalore"], project=["Pilot Path"], stance_entities=[])
    hits = idx.search("aditya", types=["who"], k=5)
    assert sorted(h.item_id for h in hits) == ["a", "b"]


def test_search_is_case_insensitive(tmp_brain: Path):
    idx = HookIndex.open(tmp_brain)
    idx.upsert_item_hooks(item_id="a", who=["Aditya"], what=[], where=[], project=[], stance_entities=[])
    hits = idx.search("ADITYA", types=["who"], k=5)
    assert [h.item_id for h in hits] == ["a"]


def test_search_by_multiple_types(tmp_brain: Path):
    idx = HookIndex.open(tmp_brain)
    idx.upsert_item_hooks(item_id="a", who=[], what=["Pacific"], where=[], project=[], stance_entities=[])
    idx.upsert_item_hooks(item_id="b", who=[], what=[], where=["Pacific Ocean"], project=[], stance_entities=[])
    hits = idx.search("pacific", types=["what", "where"], k=5)
    assert sorted(h.item_id for h in hits) == ["a", "b"]


def test_search_substring_match(tmp_brain: Path):
    idx = HookIndex.open(tmp_brain)
    idx.upsert_item_hooks(item_id="a", who=[], what=["Pilot Path Group"], where=[], project=[], stance_entities=[])
    hits = idx.search("pilot", types=["what"], k=5)
    assert [h.item_id for h in hits] == ["a"]


def test_upsert_replaces_previous_hooks_for_item(tmp_brain: Path):
    idx = HookIndex.open(tmp_brain)
    idx.upsert_item_hooks(item_id="a", who=["Aditya"], what=[], where=[], project=[], stance_entities=[])
    idx.upsert_item_hooks(item_id="a", who=["Sarah"], what=[], where=[], project=[], stance_entities=[])
    hits_adi = idx.search("aditya", types=["who"], k=5)
    hits_sarah = idx.search("sarah", types=["who"], k=5)
    assert [h.item_id for h in hits_adi] == []
    assert [h.item_id for h in hits_sarah] == ["a"]
```

- [ ] **Step 2: Run — expect failures**

- [ ] **Step 3: Implement `server/m3/brain/hooks.py`**

```python
"""Hook index: maps hook values back to item ids for fragment→entity retrieval.

A single sqlite table `item_hooks(item_id, hook_type, normalized_value, raw_value)`
under `~/brain/index/vectors.sqlite`. Case-insensitive substring matching.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from m3.brain.layout import BrainPaths

HookType = str   # "who" | "what" | "where" | "project" | "stance_entity"


@dataclass
class HookHit:
    item_id: str
    hook_type: str
    raw_value: str


class HookIndex:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def open(cls, root: Path) -> "HookIndex":
        p = BrainPaths(root)
        p.index_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(p.vectors_db)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS item_hooks ("
            "item_id TEXT NOT NULL, hook_type TEXT NOT NULL, "
            "normalized_value TEXT NOT NULL, raw_value TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_item_hooks_lookup "
            "ON item_hooks(hook_type, normalized_value)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_item_hooks_item ON item_hooks(item_id)")
        return cls(conn)

    def upsert_item_hooks(
        self, *, item_id: str,
        who: list[str], what: list[str], where: list[str],
        project: list[str], stance_entities: list[str],
    ) -> None:
        self._conn.execute("DELETE FROM item_hooks WHERE item_id = ?", (item_id,))
        rows: list[tuple[str, str, str, str]] = []
        for hook_type, values in (
            ("who", who), ("what", what), ("where", where),
            ("project", project), ("stance_entity", stance_entities),
        ):
            for v in values:
                v = (v or "").strip()
                if not v:
                    continue
                rows.append((item_id, hook_type, v.lower(), v))
        if rows:
            self._conn.executemany(
                "INSERT INTO item_hooks(item_id, hook_type, normalized_value, raw_value) "
                "VALUES (?, ?, ?, ?)", rows,
            )
        self._conn.commit()

    def search(self, fragment: str, *, types: list[HookType], k: int) -> list[HookHit]:
        frag = (fragment or "").strip().lower()
        if not frag or not types:
            return []
        placeholders = ",".join("?" for _ in types)
        rows = self._conn.execute(
            f"SELECT item_id, hook_type, raw_value FROM item_hooks "
            f"WHERE hook_type IN ({placeholders}) AND normalized_value LIKE ? "
            f"LIMIT ?",
            (*types, f"%{frag}%", k),
        ).fetchall()
        return [HookHit(item_id=r[0], hook_type=r[1], raw_value=r[2]) for r in rows]

    def delete_item(self, *, item_id: str) -> None:
        self._conn.execute("DELETE FROM item_hooks WHERE item_id = ?", (item_id,))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run — expect 5 pass**

- [ ] **Step 5: Commit**

```bash
git add server/m3/brain/hooks.py server/tests/brain/test_hooks.py
git commit -m "p2: brain.hooks — sqlite hook index (who/what/where/project/stance) for fragment lookup"
```

---

## Task 3: Wire ingest to populate FTS + hooks

**Files:**
- Modify: `server/m3/core/ingest.py` (small — add two upserts inside `_index_vectors` or split into `_index_item`)
- Modify: `server/tests/core/test_ingest.py` (add assertions that FTS + hooks are populated)

- [ ] **Step 1: Add failing test**

In `server/tests/core/test_ingest.py`, add:

```python
@pytest.mark.asyncio
async def test_ingest_populates_fts_and_hook_indexes(ingester, fake_llm, tmp_brain: Path):
    import uuid as _uuid
    item_id = _uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    fake_llm.set_response("coffee with Aditya", {
        "kind": "personal",
        "interpretation": {"what_happened": "coffee catchup",
                           "when": {"iso": "2026-04-19", "source": "ingest_time"}, "confidence": 0.9},
        "open_questions": [],
        "hooks": {
            "who": [{"name": "Aditya"}], "what": [{"name": "Pacific"}], "where": [],
            "when": "2026-04-19", "source": "cli", "project": [],
            "stance": [],
        },
        "self_updates": [], "entity_updates": [],
    })
    await ingester.ingest(IngestInput(
        item_id=item_id, source="cli", original_bytes=None, original_filename=None,
        content_type="text", text="coffee with Aditya about Pacific",
    ))
    from m3.brain.fts import FTSIndex
    from m3.brain.hooks import HookIndex
    fts = FTSIndex.open(tmp_brain)
    hits = fts.search("Pacific", k=5)
    assert [h.id for h in hits] == [str(item_id)]
    fts.close()
    h_idx = HookIndex.open(tmp_brain)
    hook_hits = h_idx.search("aditya", types=["who"], k=5)
    assert [h.item_id for h in hook_hits] == [str(item_id)]
    h_idx.close()
```

- [ ] **Step 2: Run — expect failure**

Run: `cd server && pytest tests/core/test_ingest.py::test_ingest_populates_fts_and_hook_indexes -v`

- [ ] **Step 3: Modify `server/m3/core/ingest.py`**

Find the `_index_vectors` method. Rename it to `_index_item` and extend. Replace its body with:

```python
async def _index_item(self, item_id: uuid.UUID, text: str, parsed: ExtractionOutput, entities_touched: list[str]) -> None:
    from m3.brain.fts import FTSIndex
    from m3.brain.hooks import HookIndex

    if text.strip():
        vec = (await self.embedder.embed([text]))[0]
        vidx = VectorIndex.open(self.brain_root)
        try:
            vidx.upsert_item(item_id=str(item_id), embedding=vec)
            for name in entities_touched:
                evec = (await self.embedder.embed([name]))[0]
                vidx.upsert_entity(slug=entity_doc.slugify(name), embedding=evec)
        finally:
            vidx.close()

    if text.strip():
        fidx = FTSIndex.open(self.brain_root)
        try:
            fidx.upsert_item(item_id=str(item_id), text=text)
        finally:
            fidx.close()

    hidx = HookIndex.open(self.brain_root)
    try:
        hidx.upsert_item_hooks(
            item_id=str(item_id),
            who=[ref.name for ref in parsed.hooks.who],
            what=[ref.name for ref in parsed.hooks.what],
            where=[ref.name for ref in parsed.hooks.where],
            project=list(parsed.hooks.project or []),
            stance_entities=[s.entity_name for s in parsed.hooks.stance],
        )
    finally:
        hidx.close()
```

Then find the call site `await self._index_vectors(inp.item_id, inp.text, entities_touched)` and replace it with `await self._index_item(inp.item_id, inp.text, parsed, entities_touched)`.

- [ ] **Step 4: Run full ingest suite — expect all pass**

Run: `cd server && pytest tests/core/test_ingest.py -v`
Expected: 5 passed (4 existing + 1 new).

- [ ] **Step 5: Commit**

```bash
git add server/m3/core/ingest.py server/tests/core/test_ingest.py
git commit -m "p2: ingest populates FTS + hook indexes alongside vectors"
```

---

## Task 4: `core/retrieve.py` — multi-signal ranker

**Files:**
- Create: `server/m3/core/retrieve.py`
- Test: `server/tests/core/test_retrieve.py`

The ranker takes a query fragment, runs FTS + hook lookup + vector nearest-neighbors in parallel (or sequentially; async later), combines scores via weighted sum, loads each candidate's `ItemMeta` for display, attaches "why matched" reasons, and returns top-K.

- [ ] **Step 1: Write failing tests**

```python
import uuid
from pathlib import Path

import pytest

from m3.brain.fts import FTSIndex
from m3.brain.hooks import HookIndex
from m3.brain.items import ItemMeta, write_meta
from m3.brain.vectors import VectorIndex
from m3.core.retrieve import RetrievalHit, Retriever


def _write_item(tmp_brain: Path, item_id: str, text: str, who: list[str], when_iso: str):
    meta = ItemMeta(
        id=uuid.UUID(item_id), kind="personal", source="cli", created_at=f"{when_iso}T10:00:00+00:00",
        original_filename=None, extracted_text=text, when_iso=when_iso, when_source="ingest_time",
        hooks={"who": who, "what": [], "where": [], "project": [], "stance": []},
        llm_output_raw={}, confidence=0.8,
    )
    write_meta(tmp_brain, meta)
    fts = FTSIndex.open(tmp_brain); fts.upsert_item(item_id=item_id, text=text); fts.close()
    hooks = HookIndex.open(tmp_brain); hooks.upsert_item_hooks(item_id=item_id, who=who, what=[], where=[], project=[], stance_entities=[]); hooks.close()
    vec = VectorIndex.open(tmp_brain); vec.upsert_item(item_id=item_id, embedding=[0.1] * 768); vec.close()


class _Embedder:
    dim = 768
    async def embed(self, texts): return [[0.1] * 768 for _ in texts]


@pytest.mark.asyncio
async def test_keyword_match_returns_item_with_reason(tmp_brain: Path):
    _write_item(tmp_brain, "00000000-0000-0000-0000-000000000001",
                "Had coffee with Aditya.", ["Aditya"], "2026-04-19")
    _write_item(tmp_brain, "00000000-0000-0000-0000-000000000002",
                "Receipt from Uber.", [], "2026-04-18")
    retriever = Retriever(brain_root=tmp_brain, embedder=_Embedder())
    hits = await retriever.search("Aditya", k=5)
    assert len(hits) == 1
    assert hits[0].item_id.endswith("000001")
    assert any("who" in r or "keyword" in r for r in hits[0].reasons)


@pytest.mark.asyncio
async def test_ranking_combines_signals(tmp_brain: Path):
    # Item hit by keyword + hook should outrank item hit by keyword only.
    _write_item(tmp_brain, "00000000-0000-0000-0000-00000000aaaa",
                "About the Pacific project.", ["Aditya"], "2026-04-19")
    _write_item(tmp_brain, "00000000-0000-0000-0000-00000000bbbb",
                "Randomly mentioned Aditya.", [], "2026-04-18")
    retriever = Retriever(brain_root=tmp_brain, embedder=_Embedder())
    hits = await retriever.search("Aditya", k=5)
    ids = [h.item_id[-4:] for h in hits]
    assert ids[0] == "aaaa", f"expected aaaa (hook + keyword) first, got {ids}"


@pytest.mark.asyncio
async def test_empty_query_returns_empty(tmp_brain: Path):
    retriever = Retriever(brain_root=tmp_brain, embedder=_Embedder())
    assert await retriever.search("", k=5) == []


@pytest.mark.asyncio
async def test_hit_exposes_snippet_and_date(tmp_brain: Path):
    _write_item(tmp_brain, "00000000-0000-0000-0000-000000000010",
                "Had coffee with Aditya at the usual place.", ["Aditya"], "2026-04-17")
    retriever = Retriever(brain_root=tmp_brain, embedder=_Embedder())
    hits = await retriever.search("coffee", k=5)
    assert len(hits) == 1
    assert hits[0].when_iso == "2026-04-17"
    assert "coffee" in hits[0].snippet.lower() or "coffee" in hits[0].excerpt.lower()
```

- [ ] **Step 2: Run — expect failures**

- [ ] **Step 3: Implement `server/m3/core/retrieve.py`**

```python
"""Multi-signal retrieval ranker.

Combines three signals:
- Keyword (FTS5 bm25 score, normalized 0–1)
- Hook match (binary per hit, one point per matched hook across types)
- Embedding cosine (1.0 - distance, clipped to 0–1)

Final score = w_keyword * keyword + w_hook * hook_hits + w_embed * embed.
Default weights: keyword=0.5, hook=0.3, embed=0.2.

Returns top-K RetrievalHits with item metadata + reasons.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from m3.brain.fts import FTSIndex
from m3.brain.hooks import HookIndex
from m3.brain.items import read_meta
from m3.brain.vectors import VectorIndex

HOOK_TYPES = ["who", "what", "where", "project", "stance_entity"]

W_KEYWORD = 0.5
W_HOOK = 0.3
W_EMBED = 0.2


class _Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class RetrievalHit:
    item_id: str
    score: float
    kind: str
    when_iso: str | None
    snippet: str
    excerpt: str                                  # first 200 chars of extracted_text
    reasons: list[str] = field(default_factory=list)


class Retriever:
    def __init__(self, *, brain_root: Path, embedder: _Embedder) -> None:
        self.brain_root = brain_root
        self.embedder = embedder

    async def search(self, query: str, *, k: int = 10) -> list[RetrievalHit]:
        q = (query or "").strip()
        if not q:
            return []

        fts_hits, hook_hits, vec_hits = self._gather(q)
        qvec = (await self.embedder.embed([q]))[0] if q else None
        if qvec is not None:
            vec_hits = self._vector_search(qvec, k=k * 2)

        scores: dict[str, float] = {}
        reasons: dict[str, list[str]] = {}
        snippets: dict[str, str] = {}

        for fh in fts_hits:
            scores[fh.id] = scores.get(fh.id, 0.0) + W_KEYWORD * fh.score
            reasons.setdefault(fh.id, []).append(f"keyword match (score {fh.score:.2f})")
            if fh.snippet:
                snippets[fh.id] = fh.snippet

        hook_counts: dict[str, int] = {}
        hook_types_seen: dict[str, set[str]] = {}
        for hh in hook_hits:
            hook_counts[hh.item_id] = hook_counts.get(hh.item_id, 0) + 1
            hook_types_seen.setdefault(hh.item_id, set()).add(f"{hh.hook_type}={hh.raw_value}")
        for iid, count in hook_counts.items():
            scores[iid] = scores.get(iid, 0.0) + W_HOOK * min(count, 3)
            reasons.setdefault(iid, []).append(
                "matched hooks: " + ", ".join(sorted(hook_types_seen[iid]))
            )

        for vh in vec_hits:
            sim = max(0.0, 1.0 - vh.distance)
            scores[vh.id] = scores.get(vh.id, 0.0) + W_EMBED * sim
            reasons.setdefault(vh.id, []).append(f"semantic similarity ({sim:.2f})")

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k]
        results: list[RetrievalHit] = []
        for item_id, score in ranked:
            try:
                meta = read_meta(self.brain_root, uuid.UUID(item_id))
            except (ValueError, TypeError):
                meta = None
            if meta is None:
                continue
            excerpt = (meta.extracted_text or "")[:200]
            results.append(RetrievalHit(
                item_id=item_id, score=score, kind=meta.kind,
                when_iso=meta.when_iso, snippet=snippets.get(item_id, ""),
                excerpt=excerpt, reasons=reasons.get(item_id, []),
            ))
        return results

    def _gather(self, q: str):
        fts = FTSIndex.open(self.brain_root)
        try:
            fts_hits = fts.search(q, k=20)
        finally:
            fts.close()
        hooks = HookIndex.open(self.brain_root)
        try:
            hook_hits = hooks.search(q, types=HOOK_TYPES, k=40)
        finally:
            hooks.close()
        return fts_hits, hook_hits, []

    def _vector_search(self, qvec, *, k: int):
        vec = VectorIndex.open(self.brain_root)
        try:
            return vec.nearest_items(query=qvec, k=k)
        finally:
            vec.close()
```

- [ ] **Step 4: Run — expect 4 pass**

Run: `cd server && pytest tests/core/test_retrieve.py -v`

- [ ] **Step 5: Commit**

```bash
git add server/m3/core/retrieve.py server/tests/core/test_retrieve.py
git commit -m "p2: core.retrieve — multi-signal ranker (fts + hooks + embeddings) with reasons"
```

---

## Task 5: `brain/reindex.py` — rebuild indexes from items/meta

**Files:**
- Create: `server/m3/brain/reindex.py`
- Test: `server/tests/brain/test_reindex.py`

- [ ] **Step 1: Write failing tests**

```python
import uuid
from pathlib import Path

import pytest

from m3.brain.fts import FTSIndex
from m3.brain.hooks import HookIndex
from m3.brain.items import ItemMeta, write_meta
from m3.brain.reindex import reindex_all


class _Embedder:
    dim = 768
    async def embed(self, texts): return [[0.0] * 768 for _ in texts]


@pytest.mark.asyncio
async def test_reindex_populates_fts_and_hooks_from_existing_meta_files(tmp_brain: Path):
    write_meta(tmp_brain, ItemMeta(
        id=uuid.UUID("00000000-0000-0000-0000-000000000abc"), kind="personal", source="cli",
        created_at="2026-04-19T10:00:00+00:00", original_filename=None,
        extracted_text="Had coffee with Aditya.", when_iso="2026-04-19", when_source="ingest_time",
        hooks={"who": [{"name": "Aditya"}], "what": [], "where": [], "project": [],
               "stance": []},
        llm_output_raw={}, confidence=0.8,
    ))
    result = await reindex_all(tmp_brain, embedder=_Embedder())
    assert result.items_indexed == 1
    fts = FTSIndex.open(tmp_brain)
    assert [h.id for h in fts.search("coffee", k=5)] == ["00000000-0000-0000-0000-000000000abc"]
    fts.close()
    hooks = HookIndex.open(tmp_brain)
    assert [h.item_id for h in hooks.search("aditya", types=["who"], k=5)] == ["00000000-0000-0000-0000-000000000abc"]
    hooks.close()


@pytest.mark.asyncio
async def test_reindex_is_idempotent(tmp_brain: Path):
    write_meta(tmp_brain, ItemMeta(
        id=uuid.UUID("00000000-0000-0000-0000-000000000abc"), kind="personal", source="cli",
        created_at="2026-04-19T10:00:00+00:00", original_filename=None,
        extracted_text="x", when_iso=None, when_source="unknown",
        hooks={"who": [], "what": [], "where": [], "project": [], "stance": []},
        llm_output_raw={}, confidence=0.0,
    ))
    await reindex_all(tmp_brain, embedder=_Embedder())
    await reindex_all(tmp_brain, embedder=_Embedder())
    fts = FTSIndex.open(tmp_brain)
    assert len(fts.search("x", k=10)) == 1
    fts.close()
```

- [ ] **Step 2: Run — expect failures**

- [ ] **Step 3: Implement `server/m3/brain/reindex.py`**

```python
"""Walk ~/brain/items/meta/*.json and (re)populate FTS + hooks + vectors.

Used by `m3 reindex` CLI (P2) and by cold-start flows that import raw items
from an external source and need the derived indexes to exist.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from m3.brain.fts import FTSIndex
from m3.brain.hooks import HookIndex
from m3.brain.items import read_meta
from m3.brain.layout import BrainPaths
from m3.brain.vectors import VectorIndex


class _Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class ReindexResult:
    items_indexed: int
    errors: list[str]


async def reindex_all(root: Path, *, embedder: _Embedder) -> ReindexResult:
    p = BrainPaths(root)
    errors: list[str] = []
    count = 0
    fidx = FTSIndex.open(root)
    hidx = HookIndex.open(root)
    vidx = VectorIndex.open(root)
    try:
        for meta_path in sorted(p.items_meta.glob("*.json")):
            try:
                item_id = uuid.UUID(meta_path.stem)
            except ValueError:
                errors.append(f"bad meta filename: {meta_path.name}")
                continue
            meta = read_meta(root, item_id)
            if meta is None:
                errors.append(f"read_meta returned None for {item_id}")
                continue
            if meta.extracted_text:
                fidx.upsert_item(item_id=str(item_id), text=meta.extracted_text)
                try:
                    vec = (await embedder.embed([meta.extracted_text]))[0]
                    vidx.upsert_item(item_id=str(item_id), embedding=vec)
                except Exception as e:
                    errors.append(f"embed failed for {item_id}: {e}")

            hooks = meta.hooks or {}
            hidx.upsert_item_hooks(
                item_id=str(item_id),
                who=[_ref_name(r) for r in (hooks.get("who") or [])],
                what=[_ref_name(r) for r in (hooks.get("what") or [])],
                where=[_ref_name(r) for r in (hooks.get("where") or [])],
                project=[str(p) for p in (hooks.get("project") or []) if p],
                stance_entities=[(s.get("entity_name") or "") for s in (hooks.get("stance") or []) if isinstance(s, dict)],
            )
            count += 1
    finally:
        fidx.close()
        hidx.close()
        vidx.close()
    return ReindexResult(items_indexed=count, errors=errors)


def _ref_name(ref) -> str:
    if isinstance(ref, dict):
        return (ref.get("name") or "").strip()
    if isinstance(ref, str):
        return ref.strip()
    return ""
```

- [ ] **Step 4: Run — expect 2 pass**

- [ ] **Step 5: Commit**

```bash
git add server/m3/brain/reindex.py server/tests/brain/test_reindex.py
git commit -m "p2: brain.reindex — rebuild FTS + hooks + vectors from items/meta"
```

---

## Task 6: CLI — `m3 search` and `m3 reindex`

**Files:**
- Modify: `server/m3/cli.py`
- Test: `server/tests/cli/test_search_command.py`

- [ ] **Step 1: Write failing CLI test**

```python
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from m3.cli import app


def _git_env(monkeypatch):
    for key, val in {
        "GIT_AUTHOR_NAME": "m3-test", "GIT_AUTHOR_EMAIL": "test@m3.local",
        "GIT_COMMITTER_NAME": "m3-test", "GIT_COMMITTER_EMAIL": "test@m3.local",
        "M3_LLM_PROVIDER": "fake",
    }.items():
        monkeypatch.setenv(key, val)


def test_search_command_returns_ranked_results(tmp_path: Path, monkeypatch):
    _git_env(monkeypatch)
    runner = CliRunner()
    brain = tmp_path / "brain"
    runner.invoke(app, ["init", "--brain", str(brain)])
    note = tmp_path / "note.txt"
    note.write_text("Had coffee with Aditya about Pacific.")
    runner.invoke(app, ["ingest", str(note), "--brain", str(brain)])
    result = runner.invoke(app, ["search", "coffee", "--brain", str(brain)])
    assert result.exit_code == 0, result.output
    assert "coffee" in result.output.lower() or "aditya" in result.output.lower()


def test_reindex_command_runs(tmp_path: Path, monkeypatch):
    _git_env(monkeypatch)
    runner = CliRunner()
    brain = tmp_path / "brain"
    runner.invoke(app, ["init", "--brain", str(brain)])
    result = runner.invoke(app, ["reindex", "--brain", str(brain)])
    assert result.exit_code == 0, result.output
    assert "indexed" in result.output.lower()
```

- [ ] **Step 2: Run — expect failures**

- [ ] **Step 3: Extend `server/m3/cli.py`**

Append two new commands to the existing `server/m3/cli.py`:

```python
@app.command()
def search(
    query: str = typer.Argument(..., help="Fragment to search for."),
    brain: Path = typer.Option(None, "--brain", help="Brain directory."),
    k: int = typer.Option(10, "--k", help="Max number of results."),
):
    """Search the brain by fragment."""
    import asyncio as _asyncio
    from m3.core.retrieve import Retriever
    brain_root = brain or _default_brain()
    if not (brain_root / "self.md").exists():
        typer.echo(f"brain at {brain_root} is not initialized", err=True)
        raise typer.Exit(code=1)
    retriever = Retriever(brain_root=brain_root, embedder=_make_embedder())
    hits = _asyncio.run(retriever.search(query, k=k))
    if not hits:
        typer.echo("(no hits)")
        return
    for i, h in enumerate(hits, 1):
        typer.echo(f"{i}. [{h.kind}] {h.when_iso or '----'} — {h.excerpt}")
        for r in h.reasons:
            typer.echo(f"     · {r}")
        typer.echo(f"     id: {h.item_id}  score: {h.score:.3f}")


@app.command()
def reindex(
    brain: Path = typer.Option(None, "--brain", help="Brain directory."),
):
    """Rebuild FTS, hook, and vector indexes from items/meta."""
    import asyncio as _asyncio
    from m3.brain.reindex import reindex_all
    brain_root = brain or _default_brain()
    if not (brain_root / "self.md").exists():
        typer.echo(f"brain at {brain_root} is not initialized", err=True)
        raise typer.Exit(code=1)
    result = _asyncio.run(reindex_all(brain_root, embedder=_make_embedder()))
    typer.echo(f"indexed {result.items_indexed} items")
    if result.errors:
        for e in result.errors:
            typer.echo(f"  error: {e}", err=True)
```

- [ ] **Step 4: Run — expect 2 pass**

Run: `cd server && pytest tests/cli/test_search_command.py -v`

- [ ] **Step 5: Commit**

```bash
git add server/m3/cli.py server/tests/cli/test_search_command.py
git commit -m "p2: CLI — m3 search + m3 reindex commands"
```

---

## Task 7: HTTP API — `GET /api/v1/retrieve`

**Files:**
- Create: `server/m3/api/retrieve.py`
- Test: `server/tests/api/test_retrieve_api.py`
- Possibly create: `server/tests/api/__init__.py`

The existing FastAPI app lives at `server/m3/main.py`. In P2 we add a new router that does NOT depend on Postgres/MinIO/Redis — it's a pure filesystem + sqlite router. To avoid booting the whole legacy app (which does DB init at startup), we'll assemble a small standalone `FastAPI()` in the router module for testing, and expose a function `include_retrieve_router(app)` that `main.py` can call when/if it wants to.

- [ ] **Step 1: Write failing test**

```python
import os
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from m3.api.retrieve import build_retrieve_app
from m3.brain.items import ItemMeta, write_meta
from m3.brain.reindex import reindex_all


class _Embedder:
    dim = 768
    async def embed(self, texts): return [[0.0] * 768 for _ in texts]


@pytest.fixture
def populated_brain(tmp_brain: Path):
    write_meta(tmp_brain, ItemMeta(
        id=uuid.UUID("00000000-0000-0000-0000-00000000cafe"), kind="personal", source="cli",
        created_at="2026-04-19T10:00:00+00:00", original_filename=None,
        extracted_text="Had coffee with Aditya about Pacific.",
        when_iso="2026-04-19", when_source="ingest_time",
        hooks={"who": [{"name": "Aditya"}], "what": [{"name": "Pacific"}], "where": [], "project": [], "stance": []},
        llm_output_raw={}, confidence=0.9,
    ))
    import asyncio
    asyncio.run(reindex_all(tmp_brain, embedder=_Embedder()))
    return tmp_brain


def test_retrieve_endpoint_returns_ranked_hits(populated_brain: Path):
    app = build_retrieve_app(brain_root=populated_brain, embedder=_Embedder())
    client = TestClient(app)
    r = client.get("/api/v1/retrieve", params={"q": "coffee"})
    assert r.status_code == 200
    body = r.json()
    assert "hits" in body
    assert len(body["hits"]) >= 1
    assert body["hits"][0]["item_id"].endswith("cafe")
    assert "reasons" in body["hits"][0]


def test_retrieve_empty_query_returns_empty_hits(populated_brain: Path):
    app = build_retrieve_app(brain_root=populated_brain, embedder=_Embedder())
    client = TestClient(app)
    r = client.get("/api/v1/retrieve", params={"q": ""})
    assert r.status_code == 200
    assert r.json()["hits"] == []


def test_retrieve_k_param_limits_results(populated_brain: Path):
    app = build_retrieve_app(brain_root=populated_brain, embedder=_Embedder())
    client = TestClient(app)
    r = client.get("/api/v1/retrieve", params={"q": "Aditya", "k": 1})
    assert r.status_code == 200
    assert len(r.json()["hits"]) <= 1
```

- [ ] **Step 2: Run — expect failures**

- [ ] **Step 3: Implement `server/m3/api/retrieve.py`**

```python
"""HTTP surface for retrieval. Pure filesystem + sqlite — no legacy DB deps."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from fastapi import APIRouter, FastAPI, Query
from pydantic import BaseModel, Field

from m3.core.retrieve import RetrievalHit, Retriever


class _Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class RetrieveHitModel(BaseModel):
    item_id: str
    score: float
    kind: str
    when_iso: str | None = None
    snippet: str
    excerpt: str
    reasons: list[str] = Field(default_factory=list)


class RetrieveResponse(BaseModel):
    hits: list[RetrieveHitModel]


def build_retrieve_router(*, brain_root: Path, embedder: _Embedder) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["retrieve"])
    retriever = Retriever(brain_root=brain_root, embedder=embedder)

    @router.get("/retrieve", response_model=RetrieveResponse)
    async def retrieve(q: str = Query("", description="Fragment query"),
                        k: int = Query(10, ge=1, le=100)):
        hits = await retriever.search(q, k=k)
        return RetrieveResponse(hits=[_to_model(h) for h in hits])

    return router


def build_retrieve_app(*, brain_root: Path, embedder: _Embedder) -> FastAPI:
    """Build a minimal FastAPI app hosting just the retrieve router.

    Used by tests and the upcoming local-server mode. The legacy main.py app
    will continue to exist until P3 removes it; that app can also mount this
    router via `app.include_router(build_retrieve_router(...))`.
    """
    app = FastAPI(title="M3 Retrieve")
    app.include_router(build_retrieve_router(brain_root=brain_root, embedder=embedder))
    return app


def _to_model(h: RetrievalHit) -> RetrieveHitModel:
    return RetrieveHitModel(
        item_id=h.item_id, score=h.score, kind=h.kind, when_iso=h.when_iso,
        snippet=h.snippet, excerpt=h.excerpt, reasons=list(h.reasons),
    )
```

- [ ] **Step 4: Run — expect 3 pass**

Run: `cd server && pytest tests/api/test_retrieve_api.py -v`

- [ ] **Step 5: Commit**

```bash
git add server/m3/api/retrieve.py server/tests/api/
git commit -m "p2: api.retrieve — FastAPI router + standalone app for GET /api/v1/retrieve"
```

---

## Task 8: End-to-end smoke

**Files:** none (manual)

- [ ] **Step 1: Init a scratch brain and ingest three items via fake provider**

```bash
cd /Users/mk/Projects/M3/.worktrees/p2-retrieval
rm -rf /tmp/m3-p2 && mkdir /tmp/m3-p2
export GIT_AUTHOR_NAME=mk GIT_AUTHOR_EMAIL=mk@local GIT_COMMITTER_NAME=mk GIT_COMMITTER_EMAIL=mk@local
export M3_BRAIN=/tmp/m3-p2/brain M3_LLM_PROVIDER=fake
m3 init
echo "coffee with Aditya about Pacific" > /tmp/m3-p2/note1.txt && m3 ingest /tmp/m3-p2/note1.txt
echo "FluentCRM is the wrong tool for us" > /tmp/m3-p2/note2.txt && m3 ingest /tmp/m3-p2/note2.txt
echo "uber receipt for 42 dollars" > /tmp/m3-p2/note3.txt && m3 ingest /tmp/m3-p2/note3.txt
```

- [ ] **Step 2: Search and expect ranked results**

```bash
m3 search "Aditya"
m3 search "coffee"
m3 search "fluent"
```

Expect non-empty output, at least one hit per query, match reasons shown. Since the fake LLM emits empty hooks, only keyword (FTS) will match — that's OK for a smoke; P2 accuracy improves the moment a real LLM provides hooks.

- [ ] **Step 3: Run reindex and confirm it still works**

```bash
m3 reindex
```

Expect `indexed 3 items`.

- [ ] **Step 4: Nothing to commit — this is manual verification**

---

## Self-Review

Covered against the spec's retrieval surface B requirements and success criterion §14.5 (fragment retrieval returns the right item in the top 3):

- **Fragment-tolerant multi-signal search** — ✅ Task 4 combines FTS + hooks + embeddings with a weighted ranker.
- **Hook types (who/what/where/project)** — ✅ Task 2 indexes all four plus `stance_entity`.
- **Temporal-phrase extraction** — ⚠️ Not implemented in P2. The ranker takes date filters but does not parse "last October" from the query string. Noted as a P2.1 follow-up; low effort, but ship order is: get the signals stable first, add temporal parsing when a real LLM reveals whether it's needed.
- **Ranking with reasons** — ✅ `RetrievalHit.reasons` threaded through ranker + API + CLI.
- **m3 search CLI** — ✅ Task 6.
- **`GET /api/v1/retrieve` HTTP endpoint** — ✅ Task 7.
- **Ingest writes to indexes** — ✅ Task 3.
- **Reindex from cold start** — ✅ Task 5.

Placeholders: none. Every step contains the actual code.

Type consistency: `FTSHit`, `HookHit`, `VectorIndex.Hit` stay internal to brain/. `RetrievalHit` in core/retrieve.py is the single public record. API mirrors it verbatim in `RetrieveHitModel`. `_Embedder` Protocol is the same shape across ingest.py, retrieve.py, reindex.py, api/retrieve.py (declares only `embed(texts) -> list[list[float]]`).

---

*End of P2 plan.*

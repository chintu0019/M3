"""Multi-signal retrieval ranker.

Combines three signals:
- Keyword (FTS5 bm25 score, already normalized 0-1 per hit by FTSIndex via
  `1 / (1 + raw_bm25)`)
- Hook match (one point per matched hook across types, capped at 3)
- Embedding cosine (1.0 - distance, clipped to 0-1)

Final score = W_KEYWORD * keyword + W_HOOK * hook_hits + W_EMBED * embed.
Default weights: keyword=0.5, hook=0.6, embed=0.2.

Hook matches weigh more than keyword matches because a hook hit is already a
structured signal (the LLM explicitly called this value out at ingest time),
while a raw keyword hit is just lexical coincidence. An item that matched via
hook should outrank one that matched only by substring.

Embeddings only re-rank items that already matched a lexical or hook signal;
they don't add net-new candidates. This keeps a fake/constant embedder
(common in tests, possible in cold-start production) from dragging in every
item in the store.

Returns top-K RetrievalHits with item metadata + human-readable reasons.
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
W_HOOK = 0.6
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
    excerpt: str = ""
    reasons: list[str] = field(default_factory=list)


class Retriever:
    def __init__(self, *, brain_root: Path, embedder: _Embedder) -> None:
        self.brain_root = brain_root
        self.embedder = embedder

    async def search(self, query: str, *, k: int = 10) -> list[RetrievalHit]:
        q = (query or "").strip()
        if not q:
            return []

        fts_hits, hook_hits = self._gather(q)
        qvec = (await self.embedder.embed([q]))[0]
        vec_hits = self._vector_search(qvec, k=k * 2)

        scores: dict[str, float] = {}
        reasons: dict[str, list[str]] = {}
        snippets: dict[str, str] = {}

        for fh in fts_hits:
            scores[fh.id] = scores.get(fh.id, 0.0) + W_KEYWORD * fh.score
            reasons.setdefault(fh.id, []).append(
                f"keyword match (score {fh.score:.2f})"
            )
            if fh.snippet:
                snippets[fh.id] = fh.snippet

        hook_counts: dict[str, int] = {}
        hook_types_seen: dict[str, set[str]] = {}
        for hh in hook_hits:
            hook_counts[hh.item_id] = hook_counts.get(hh.item_id, 0) + 1
            hook_types_seen.setdefault(hh.item_id, set()).add(
                f"{hh.hook_type}={hh.raw_value}"
            )
        for iid, count in hook_counts.items():
            scores[iid] = scores.get(iid, 0.0) + W_HOOK * min(count, 3)
            reasons.setdefault(iid, []).append(
                "matched hooks: " + ", ".join(sorted(hook_types_seen[iid]))
            )

        # Embeddings only re-rank items that already matched a lexical/hook
        # signal. Semantic similarity on its own is too noisy to surface
        # candidates on — e.g. a constant-vector fake embedder would drag in
        # every item in the store.
        for vh in vec_hits:
            if vh.id not in scores:
                continue
            sim = max(0.0, 1.0 - vh.distance)
            if sim <= 0.0:
                continue
            scores[vh.id] += W_EMBED * sim
            reasons.setdefault(vh.id, []).append(
                f"semantic similarity ({sim:.2f})"
            )

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
            results.append(
                RetrievalHit(
                    item_id=item_id,
                    score=score,
                    kind=meta.kind,
                    when_iso=meta.when_iso,
                    snippet=snippets.get(item_id, ""),
                    excerpt=excerpt,
                    reasons=reasons.get(item_id, []),
                )
            )
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
        return fts_hits, hook_hits

    def _vector_search(self, qvec, *, k: int):
        vec = VectorIndex.open(self.brain_root)
        try:
            return vec.nearest_items(query=qvec, k=k)
        finally:
            vec.close()

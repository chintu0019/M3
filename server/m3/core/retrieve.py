"""Multi-signal retrieval ranker.

Combines three signals:
- Keyword (FTS5 bm25, per-query max-normalized to 0-1)
- Hook match (one point per matched hook across types, capped at 3)
- Embedding cosine (1.0 - distance, clipped to 0-1)

Final score = W_KEYWORD * keyword_norm + W_HOOK * hook_hits + W_EMBED * embed.
Default weights: keyword=0.5, hook=0.3, embed=0.2.

Keyword hits carry the most weight because the user's raw query was a lexical
signal; hook hits add structured-signal confirmation on top; embeddings pull
in semantically-related items the user phrased differently from the stored
text. Semantic similarity has a conservative threshold (0.35) so fake or
noisy embedders can't drag in every item.
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
EMBED_SIM_THRESHOLD = 0.35


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

    async def search(
        self,
        query: str,
        *,
        k: int = 10,
        since_iso: str | None = None,
        until_iso: str | None = None,
    ) -> list[RetrievalHit]:
        q = (query or "").strip()
        if not q:
            return []

        fts_hits, hook_hits = self._gather(q)
        qvec = (await self.embedder.embed([q]))[0]
        vec_hits = self._vector_search(qvec, k=k * 2)

        scores: dict[str, float] = {}
        reasons: dict[str, list[str]] = {}
        snippets: dict[str, str] = {}

        # Per-query max-normalize FTS scores to 0-1 so W_KEYWORD composes
        # predictably with hook/embed weights regardless of absolute bm25
        # magnitude (which depends on corpus length and term frequencies).
        max_fts = max((h.score for h in fts_hits), default=0.0)
        for fh in fts_hits:
            if max_fts > 0:
                norm = fh.score / max_fts
                scores[fh.id] = scores.get(fh.id, 0.0) + W_KEYWORD * norm
                reasons.setdefault(fh.id, []).append(
                    f"keyword match (score {norm:.2f})"
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

        # Embeddings add net-new candidates above a conservative similarity
        # threshold. The threshold keeps noise (fake/constant embedders, weak
        # semantic matches) out while letting genuine paraphrase/synonym hits
        # through.
        for vh in vec_hits:
            sim = max(0.0, 1.0 - vh.distance)
            if sim < EMBED_SIM_THRESHOLD:
                continue
            scores[vh.id] = scores.get(vh.id, 0.0) + W_EMBED * sim
            reasons.setdefault(vh.id, []).append(
                f"semantic similarity ({sim:.2f})"
            )

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        results: list[RetrievalHit] = []
        for item_id, score in ranked:
            try:
                meta = read_meta(self.brain_root, uuid.UUID(item_id))
            except (ValueError, TypeError):
                meta = None
            if meta is None:
                continue
            if not _passes_time(meta.when_iso, since_iso, until_iso):
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
            if len(results) >= k:
                break
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


def _passes_time(
    when_iso: str | None, since_iso: str | None, until_iso: str | None
) -> bool:
    """Filter by when_iso window. Items without when_iso are excluded when
    any filter is set (can't know if they fall inside) and included when no
    filter is set."""
    if since_iso is None and until_iso is None:
        return True
    if not when_iso:
        return False
    if since_iso and when_iso < since_iso:
        return False
    if until_iso and when_iso > until_iso:
        return False
    return True

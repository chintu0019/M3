"""
M3 Search — hybrid semantic + keyword search over entities.

Returns entity hits ranked via Reciprocal Rank Fusion of a vector search
against ``entities.embedding`` and an FTS scan across canonical name,
aliases, description, and page_overview.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from m3.core.llm import EmbeddingProvider
from m3.storage.models import Entity

logger = logging.getLogger("m3.search")


@dataclass
class SearchResult:
    entity_id: uuid.UUID
    canonical_name: str
    entity_type: str
    snippet: str
    score: float


class SearchEngine:
    def __init__(self, db: async_sessionmaker, embedder: EmbeddingProvider):
        self.db = db
        self.embedder = embedder

    async def search(
        self,
        query: str,
        limit: int = 10,
        entity_type: str | None = None,
    ) -> list[SearchResult]:
        """Hybrid search over entities: vector similarity + FTS, merged via RRF."""
        async with self.db() as session:
            base_filter = Entity.id.isnot(None)
            if entity_type:
                base_filter = base_filter & (Entity.entity_type == entity_type)

            vector_results = []
            try:
                embeddings = await self.embedder.embed([query])
                query_embedding = embeddings[0]

                result = await session.execute(
                    select(
                        Entity.id,
                        Entity.canonical_name,
                        Entity.entity_type,
                        Entity.page_overview,
                        Entity.description,
                    )
                    .where(base_filter)
                    .where(Entity.embedding.isnot(None))
                    .order_by(Entity.embedding.cosine_distance(query_embedding))
                    .limit(limit * 2)
                )
                vector_results = list(result.all())
            except Exception:
                logger.warning("Vector search failed, using FTS only")

            fts_results = []
            try:
                tsquery = func.plainto_tsquery("english", query)
                # Include aliases in the FTS haystack so "John" finds an entity
                # canonically stored as "John Doe".
                haystack = (
                    func.coalesce(Entity.canonical_name, "")
                    + " "
                    + func.array_to_string(Entity.aliases, " ")
                    + " "
                    + func.coalesce(Entity.description, "")
                    + " "
                    + func.coalesce(Entity.page_overview, "")
                )
                tsvector = func.to_tsvector("english", haystack)
                result = await session.execute(
                    select(
                        Entity.id,
                        Entity.canonical_name,
                        Entity.entity_type,
                        Entity.page_overview,
                        Entity.description,
                    )
                    .where(base_filter)
                    .where(tsvector.bool_op("@@")(tsquery))
                    .order_by(func.ts_rank(tsvector, tsquery).desc())
                    .limit(limit * 2)
                )
                fts_results = list(result.all())
            except Exception:
                logger.warning("FTS search failed")

            scores: dict[uuid.UUID, float] = {}
            row_data: dict[uuid.UUID, tuple] = {}
            k = 60

            for rank, row in enumerate(vector_results):
                eid = row[0]
                scores[eid] = scores.get(eid, 0) + 1 / (k + rank)
                row_data[eid] = row

            for rank, row in enumerate(fts_results):
                eid = row[0]
                scores[eid] = scores.get(eid, 0) + 1 / (k + rank)
                if eid not in row_data:
                    row_data[eid] = row

            sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:limit]

            results = []
            for eid in sorted_ids:
                row = row_data[eid]
                overview = row[3] or row[4] or ""
                snippet = (
                    overview[:300].rsplit(" ", 1)[0] + "..."
                    if len(overview) > 300
                    else overview
                )
                results.append(
                    SearchResult(
                        entity_id=eid,
                        canonical_name=row[1],
                        entity_type=row[2],
                        snippet=snippet,
                        score=scores[eid],
                    )
                )

            return results

"""
M3 Search -- hybrid semantic + keyword search with Reciprocal Rank Fusion.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from m3.core.llm import EmbeddingProvider
from m3.storage.models import WikiPage

logger = logging.getLogger("m3.search")


@dataclass
class SearchResult:
    page_id: uuid.UUID
    title: str
    snippet: str
    score: float
    category: str | None


class SearchEngine:
    def __init__(self, db: async_sessionmaker, embedder: EmbeddingProvider):
        self.db = db
        self.embedder = embedder

    async def search(
        self,
        query: str,
        limit: int = 10,
        category: str | None = None,
    ) -> list[SearchResult]:
        """Hybrid search: vector similarity + FTS, merged via RRF."""
        async with self.db() as session:
            base_filter = WikiPage.page_type != "_index"
            if category:
                base_filter = base_filter & (WikiPage.category == category)

            # Vector search
            vector_results = []
            try:
                embeddings = await self.embedder.embed([query])
                query_embedding = embeddings[0]

                result = await session.execute(
                    select(
                        WikiPage.id,
                        WikiPage.title,
                        WikiPage.content,
                        WikiPage.category,
                    )
                    .where(base_filter)
                    .where(WikiPage.embedding.isnot(None))
                    .order_by(WikiPage.embedding.cosine_distance(query_embedding))
                    .limit(limit * 2)
                )
                vector_results = list(result.all())
            except Exception:
                logger.warning("Vector search failed, using FTS only")

            # Full-text search
            fts_results = []
            try:
                tsquery = func.plainto_tsquery("english", query)
                tsvector = func.to_tsvector(
                    "english",
                    func.coalesce(WikiPage.title, "") + " " + func.coalesce(WikiPage.content, ""),
                )
                result = await session.execute(
                    select(
                        WikiPage.id,
                        WikiPage.title,
                        WikiPage.content,
                        WikiPage.category,
                    )
                    .where(base_filter)
                    .where(tsvector.bool_op("@@")(tsquery))
                    .order_by(func.ts_rank(tsvector, tsquery).desc())
                    .limit(limit * 2)
                )
                fts_results = list(result.all())
            except Exception:
                logger.warning("FTS search failed")

            # Merge via Reciprocal Rank Fusion
            scores: dict[uuid.UUID, float] = {}
            page_data: dict[uuid.UUID, tuple] = {}
            k = 60

            for rank, row in enumerate(vector_results):
                page_id = row[0]
                scores[page_id] = scores.get(page_id, 0) + 1 / (k + rank)
                page_data[page_id] = row

            for rank, row in enumerate(fts_results):
                page_id = row[0]
                scores[page_id] = scores.get(page_id, 0) + 1 / (k + rank)
                if page_id not in page_data:
                    page_data[page_id] = row

            sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:limit]

            results = []
            for page_id in sorted_ids:
                row = page_data[page_id]
                content = row[2] or ""
                snippet = content[:300].rsplit(" ", 1)[0] + "..." if len(content) > 300 else content
                results.append(SearchResult(
                    page_id=page_id,
                    title=row[1],
                    snippet=snippet,
                    score=scores[page_id],
                    category=row[3],
                ))

            return results

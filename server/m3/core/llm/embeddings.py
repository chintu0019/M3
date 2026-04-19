"""
Local embedding providers.

Currently ships one: ``FastEmbedProvider`` — CPU inference via fastembed +
ONNX runtime. 768-dim nomic-embed-text-v1.5 is the default; swapping to a
different dimension requires a migration for ``wiki_pages.embedding``.
"""

import asyncio

from m3.core.llm.base import EmbeddingProvider


class FastEmbedProvider(EmbeddingProvider):
    """Local CPU-based embeddings via fastembed + ONNX runtime."""

    def __init__(self, model: str = "nomic-ai/nomic-embed-text-v1.5", dim: int = 768):
        from fastembed import TextEmbedding

        self._model_name = model
        self._dim = dim
        self._model = TextEmbedding(model_name=model)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        def _embed():
            embeddings = list(self._model.embed(texts))
            return [e.tolist() for e in embeddings]

        return await asyncio.to_thread(_embed)

    @property
    def dimensions(self) -> int:
        return self._dim

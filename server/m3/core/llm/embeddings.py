"""
Local embedding providers.

Currently ships one: ``FastEmbedProvider`` — CPU inference via fastembed +
ONNX runtime. 768-dim nomic-embed-text-v1.5 is the default; swapping to a
different dimension requires a migration for ``wiki_pages.embedding``.

Model cache lives at ``~/.m3/cache/fastembed`` (override with ``M3_MODEL_CACHE``).
The fastembed default puts the cache under ``$TMPDIR`` (``/var/folders/...`` on
macOS), which macOS periodically purges. A purge mid-download leaves an
``.incomplete`` blob and the next start crashes with ``NoSuchFile`` on the
ONNX model. Pinning the cache under ``~/.m3/`` makes it survive reboots and
keeps the ~250 MB download out of brain backups.
"""

import asyncio
import os
from pathlib import Path

from m3.core.llm.base import EmbeddingProvider


def default_model_cache_dir() -> Path:
    """Resolve the persistent fastembed cache directory.

    Resolution order: M3_MODEL_CACHE env var > ~/.m3/cache/fastembed. The
    directory is created on first call so callers can hand the path straight
    to fastembed without worrying about parents.
    """
    override = os.environ.get("M3_MODEL_CACHE")
    base = Path(override).expanduser() if override else Path.home() / ".m3" / "cache" / "fastembed"
    base.mkdir(parents=True, exist_ok=True)
    return base


class FastEmbedProvider(EmbeddingProvider):
    """Local CPU-based embeddings via fastembed + ONNX runtime."""

    def __init__(
        self,
        model: str = "nomic-ai/nomic-embed-text-v1.5",
        dim: int = 768,
        cache_dir: Path | None = None,
    ):
        from fastembed import TextEmbedding

        self._model_name = model
        self._dim = dim
        self._cache_dir = cache_dir or default_model_cache_dir()
        self._model = TextEmbedding(model_name=model, cache_dir=str(self._cache_dir))

    async def embed(self, texts: list[str]) -> list[list[float]]:
        def _embed():
            embeddings = list(self._model.embed(texts))
            return [e.tolist() for e in embeddings]

        return await asyncio.to_thread(_embed)

    @property
    def dimensions(self) -> int:
        return self._dim

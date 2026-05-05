"""HTTP surface for cluster retrieval (surface C)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from fastapi import APIRouter, Query
from pydantic import BaseModel

from m3.core.cluster import build_cluster, build_full_graph


class _Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class NodeModel(BaseModel):
    id: str
    type: str
    label: str
    score: float = 0.0
    kind: str | None = None
    entity_type: str | None = None
    when_iso: str | None = None
    excerpt: str | None = None
    item_id: str | None = None
    entity_slug: str | None = None


class EdgeModel(BaseModel):
    source: str
    target: str
    kind: str


class ClusterResponse(BaseModel):
    nodes: list[NodeModel]
    edges: list[EdgeModel]


def build_cluster_router(*, brain_root: Path, embedder: _Embedder) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["cluster"])

    @router.get("/cluster", response_model=ClusterResponse)
    async def cluster(q: str = Query("", description="Fragment query"),
                      k: int = Query(15, ge=1, le=50)):
        graph = await build_cluster(brain_root=brain_root, embedder=embedder, query=q, k=k)
        return ClusterResponse(
            nodes=[NodeModel(**n.__dict__) for n in graph.nodes],
            edges=[EdgeModel(**e.__dict__) for e in graph.edges],
        )

    @router.get("/cluster/all", response_model=ClusterResponse)
    async def cluster_all():
        """Return every item + entity in the brain with their persisted edges.
        The canvas uses this as its idle/at-rest view; chat citations highlight
        subsets of this graph rather than refetching."""
        graph = await build_full_graph(brain_root=brain_root)
        return ClusterResponse(
            nodes=[NodeModel(**n.__dict__) for n in graph.nodes],
            edges=[EdgeModel(**e.__dict__) for e in graph.edges],
        )

    return router

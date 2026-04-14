"""
M3 Wiki API -- browse pages, search, graph, changelog.
"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from m3.api.deps import get_db, verify_auth
from m3.core.search import SearchEngine
from m3.schemas.api import (
    ChangelogResponse,
    GraphEdge,
    GraphNode,
    GraphResponse,
    LinkedPageInfo,
    PaginatedResponse,
    SearchResultResponse,
    WikiPageResponse,
    WikiPageSummary,
)
from m3.storage.models import Changelog, WikiLink, WikiPage

router = APIRouter(prefix="/api/v1/wiki", tags=["wiki"])


@router.get("/pages", response_model=PaginatedResponse[WikiPageSummary])
async def list_pages(
    category: str | None = Query(None),
    page_type: str | None = Query(None),
    tags: str | None = Query(None, description="Comma-separated tags"),
    sort_by: str = Query("updated_at", regex="^(updated_at|created_at|title)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    query = select(WikiPage).where(WikiPage.page_type != "_index")
    count_query = select(func.count(WikiPage.id)).where(WikiPage.page_type != "_index")

    if category:
        query = query.where(WikiPage.category == category)
        count_query = count_query.where(WikiPage.category == category)
    if page_type:
        query = query.where(WikiPage.page_type == page_type)
        count_query = count_query.where(WikiPage.page_type == page_type)
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        for tag in tag_list:
            query = query.where(WikiPage.tags.any(tag))
            count_query = count_query.where(WikiPage.tags.any(tag))

    sort_col = getattr(WikiPage, sort_by)
    if sort_by in ("updated_at", "created_at"):
        query = query.order_by(sort_col.desc())
    else:
        query = query.order_by(sort_col)

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    pages = result.scalars().all()

    return PaginatedResponse(
        items=[
            WikiPageSummary(
                id=p.id,
                title=p.title,
                category=p.category,
                page_type=p.page_type,
                tags=p.tags or [],
                confidence=p.confidence,
                created_at=p.created_at,
                updated_at=p.updated_at,
            )
            for p in pages
        ],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/pages/{page_id}", response_model=WikiPageResponse)
async def get_page(
    page_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    import uuid

    pid = uuid.UUID(page_id)
    page = await db.get(WikiPage, pid)
    if not page:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Page not found")

    # Get linked pages
    linked = []
    outgoing = await db.execute(
        select(WikiLink.target_page_id, WikiLink.link_type, WikiPage.title)
        .join(WikiPage, WikiPage.id == WikiLink.target_page_id)
        .where(WikiLink.source_page_id == pid)
    )
    for row in outgoing.all():
        linked.append(LinkedPageInfo(id=row[0], title=row[2], link_type=row[1], direction="outgoing"))

    incoming = await db.execute(
        select(WikiLink.source_page_id, WikiLink.link_type, WikiPage.title)
        .join(WikiPage, WikiPage.id == WikiLink.source_page_id)
        .where(WikiLink.target_page_id == pid)
    )
    for row in incoming.all():
        linked.append(LinkedPageInfo(id=row[0], title=row[2], link_type=row[1], direction="incoming"))

    return WikiPageResponse(
        id=page.id,
        title=page.title,
        content=page.content,
        category=page.category,
        page_type=page.page_type,
        tags=page.tags or [],
        confidence=page.confidence,
        created_at=page.created_at,
        updated_at=page.updated_at,
        source_items=page.source_items or [],
        metadata=page.metadata_ or {},
        linked_pages=linked,
    )


@router.get("/search", response_model=list[SearchResultResponse])
async def search_wiki(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    category: str | None = Query(None),
    request: Request = None,
    _auth: str = Depends(verify_auth),
):
    search_engine = SearchEngine(
        db=request.app.state.db,
        embedder=request.app.state.embedder,
    )
    results = await search_engine.search(q, limit=limit, category=category)
    return [
        SearchResultResponse(
            page_id=r.page_id,
            title=r.title,
            snippet=r.snippet,
            score=r.score,
            category=r.category,
        )
        for r in results
    ]


@router.get("/projects", response_model=list[str])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    result = await db.execute(
        select(WikiPage.category)
        .where(WikiPage.category.isnot(None))
        .where(WikiPage.page_type != "_index")
        .distinct()
        .order_by(WikiPage.category)
    )
    return [row[0] for row in result.all()]


@router.get("/tags", response_model=list[dict])
async def list_tags(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    result = await db.execute(
        text(
            "SELECT tag, COUNT(*) as count "
            "FROM (SELECT unnest(tags) AS tag FROM wiki_pages WHERE page_type != '_index') sub "
            "GROUP BY tag ORDER BY count DESC"
        )
    )
    return [{"tag": row[0], "count": row[1]} for row in result.all()]


@router.get("/graph", response_model=GraphResponse)
async def get_graph(
    category: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    # Get nodes
    query = select(WikiPage).where(WikiPage.page_type != "_index")
    if category:
        query = query.where(WikiPage.category == category)

    result = await db.execute(query)
    pages = result.scalars().all()
    page_ids = {p.id for p in pages}

    # Get edges
    result = await db.execute(select(WikiLink))
    all_links = result.scalars().all()

    # Count connections per page
    connection_counts: dict = {}
    edges = []
    for link in all_links:
        if link.source_page_id in page_ids and link.target_page_id in page_ids:
            edges.append(GraphEdge(
                source_id=link.source_page_id,
                target_id=link.target_page_id,
                link_type=link.link_type,
                weight=link.weight,
            ))
            connection_counts[link.source_page_id] = connection_counts.get(link.source_page_id, 0) + 1
            connection_counts[link.target_page_id] = connection_counts.get(link.target_page_id, 0) + 1

    nodes = [
        GraphNode(
            id=p.id,
            title=p.title,
            category=p.category,
            page_type=p.page_type,
            tags=p.tags or [],
            connection_count=connection_counts.get(p.id, 0),
        )
        for p in pages
    ]

    return GraphResponse(nodes=nodes, edges=edges)


@router.get("/changelog", response_model=PaginatedResponse[ChangelogResponse])
async def list_changelog(
    page_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    import uuid as uuid_mod

    query = select(Changelog).order_by(Changelog.created_at.desc())
    count_query = select(func.count(Changelog.id))

    if page_id:
        pid = uuid_mod.UUID(page_id)
        query = query.where(Changelog.page_id == pid)
        count_query = count_query.where(Changelog.page_id == pid)

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    entries = result.scalars().all()

    return PaginatedResponse(
        items=[
            ChangelogResponse(
                id=e.id,
                action=e.action,
                page_id=e.page_id,
                description=e.description,
                created_at=e.created_at,
            )
            for e in entries
        ],
        total=total,
        page=page,
        per_page=per_page,
    )

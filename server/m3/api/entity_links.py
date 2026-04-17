"""
M3 Entity Links API — Phase B.

Canvas needs drag-to-link and undo. POST creates a link; DELETE
removes one. Uniqueness on (source, target, link_type) comes from
the existing uq_entity_links constraint — duplicate POSTs return 409.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from m3.api.deps import get_db, verify_auth
from m3.schemas.api import EntityLinkCreateRequest, EntityLinkResponse
from m3.storage.models import Entity, EntityLink

router = APIRouter(prefix="/api/v1/entity-links", tags=["entity-links"])


@router.post("", response_model=EntityLinkResponse, status_code=status.HTTP_201_CREATED)
async def create_link(
    body: EntityLinkCreateRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    if body.source_entity_id == body.target_entity_id:
        raise HTTPException(status_code=400, detail="Source and target must differ")

    # Verify both entities exist before inserting so we return a clean 404
    # instead of a FK violation.
    for eid in (body.source_entity_id, body.target_entity_id):
        if await db.get(Entity, eid) is None:
            raise HTTPException(status_code=404, detail=f"Entity {eid} not found")

    link = EntityLink(
        source_entity_id=body.source_entity_id,
        target_entity_id=body.target_entity_id,
        link_type=body.link_type.strip().lower(),
        weight=body.weight,
    )
    db.add(link)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Link with this (source, target, link_type) already exists",
        )
    await db.refresh(link)
    return EntityLinkResponse(
        id=link.id,
        source_entity_id=link.source_entity_id,
        target_entity_id=link.target_entity_id,
        link_type=link.link_type,
        weight=link.weight,
    )


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    link = await db.get(EntityLink, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found")
    await db.delete(link)
    await db.commit()
    return None

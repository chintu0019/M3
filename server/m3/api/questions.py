"""HTTP surface for open questions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from m3.brain.questions import list_unresolved, resolve


class QuestionEntry(BaseModel):
    question: str


class QuestionsResponse(BaseModel):
    questions: list[QuestionEntry]


class ResolveRequest(BaseModel):
    question_text: str
    answer: str


class ResolveResponse(BaseModel):
    resolved: bool


def build_questions_router(*, brain_root: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["open-questions"])

    @router.get("/open-questions", response_model=QuestionsResponse)
    async def get_questions():
        return QuestionsResponse(
            questions=[QuestionEntry(question=q) for q in list_unresolved(brain_root)]
        )

    @router.post("/open-questions/resolve", response_model=ResolveResponse)
    async def post_resolve(body: ResolveRequest):
        today = datetime.now(timezone.utc).date().isoformat()
        hit = resolve(
            brain_root,
            question_text=body.question_text,
            answer=body.answer,
            resolved_date=today,
        )
        return ResolveResponse(resolved=hit)

    return router

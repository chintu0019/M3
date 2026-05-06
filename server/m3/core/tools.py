"""Brain tools callable by the agent.

Each tool is an async method that returns a JSON-serializable result. The
agent loop passes these to the LLM as tool definitions (JSON schemas) and
invokes the matching method when the LLM emits a tool call.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from m3.brain.entity_doc import load as load_entity
from m3.brain.items import read_meta
from m3.brain.layout import BrainPaths
from m3.brain.questions import list_unresolved
from m3.core.retrieve import Retriever


class _Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class _SyntheticHit:
    """Stand-in shaped like core.retrieve.Hit so search_brain can return it without
    forcing an import of the retrieve module's dataclass. Used for the scoped-chat
    fallback when the retriever didn't surface the pinned item itself."""
    item_id: str
    score: float
    kind: str
    when_iso: str | None
    snippet: str
    excerpt: str
    reasons: tuple[str, ...]


class BrainTools:
    def __init__(
        self, *, brain_root: Path, embedder: _Embedder,
        scope_item_id: str | None = None,
    ) -> None:
        self.brain_root = brain_root
        self.embedder = embedder
        self.scope_item_id = scope_item_id
        self._retriever = Retriever(brain_root=brain_root, embedder=embedder)

    # --- tool methods ---

    async def search_brain(self, *, query: str, k: int = 10,
                           since_iso: str | None = None, until_iso: str | None = None) -> list[dict[str, Any]]:
        hits = await self._retriever.search(query, k=k, since_iso=since_iso, until_iso=until_iso)
        if self.scope_item_id:
            # Hard-filter: when chat is scoped to a single uploaded file, the
            # agent should only see hits from that file. If the retriever
            # didn't surface the scoped item (e.g. the user asked something
            # that doesn't textually match), synthesize one hit from the
            # item's meta so the agent always has it to work with.
            filtered = [h for h in hits if h.item_id == self.scope_item_id]
            if not filtered:
                meta = read_meta(self.brain_root, uuid.UUID(self.scope_item_id))
                if meta is not None:
                    excerpt = (meta.extracted_text or "")[:400]
                    filtered = [_SyntheticHit(
                        item_id=str(meta.id), score=0.5, kind=meta.kind,
                        when_iso=meta.when_iso, snippet=excerpt[:160],
                        excerpt=excerpt, reasons=("scoped_pin",),
                    )]
            hits = filtered
        return [{
            "item_id": h.item_id, "score": h.score, "kind": h.kind,
            "when_iso": h.when_iso, "snippet": h.snippet, "excerpt": h.excerpt,
            "reasons": list(h.reasons),
        } for h in hits]

    async def open_item(self, *, item_id: str) -> dict[str, Any]:
        try:
            uid = uuid.UUID(item_id)
        except ValueError:
            return {"error": f"invalid uuid: {item_id}"}
        meta = read_meta(self.brain_root, uid)
        if meta is None:
            return {"error": f"item {item_id} not found"}
        return {
            "id": str(meta.id), "kind": meta.kind, "source": meta.source,
            "created_at": meta.created_at, "extracted_text": meta.extracted_text,
            "when_iso": meta.when_iso, "hooks": meta.hooks, "confidence": meta.confidence,
        }

    async def open_entity(self, *, slug: str) -> dict[str, Any]:
        doc = load_entity(self.brain_root, slug=slug)
        if doc is None:
            return {"error": f"entity {slug!r} not found"}
        # Find items that hook to this entity (cheap: search by canonical name, take top K)
        items_hits = await self._retriever.search(doc.canonical_name, k=10)
        return {
            "slug": slug, "canonical_name": doc.canonical_name, "entity_type": doc.entity_type,
            "aliases": doc.aliases, "description": doc.description, "related": doc.related,
            "summary_external": doc.summary_external, "body": doc.body,
            "items": [{"item_id": h.item_id, "excerpt": h.excerpt, "when_iso": h.when_iso}
                      for h in items_hits],
        }

    async def list_open_questions(self) -> list[str]:
        return list_unresolved(self.brain_root)

    # --- prompt augmentation ---

    def pinned_context_block(self, *, max_chars: int = 4000) -> str | None:
        """When chat is scoped to one item, return a system-prompt block that
        carries that item's text inline. The agent loop appends this to the
        base system prompt so the LLM can answer without a tool round even if
        retrieval misses the file."""
        if not self.scope_item_id:
            return None
        try:
            uid = uuid.UUID(self.scope_item_id)
        except ValueError:
            return None
        meta = read_meta(self.brain_root, uid)
        if meta is None:
            return None
        text = (meta.extracted_text or "").strip()
        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars] + "…"
        filename = meta.original_filename or "(no filename)"
        return (
            "PINNED FILE CONTEXT\n"
            f"item_id: {meta.id}\n"
            f"filename: {filename}\n"
            "When the user asks a question, prefer this file's content. "
            f"Cite it as [^{meta.id}] whenever you use it.\n\n"
            "--- begin file ---\n"
            f"{text}\n"
            "--- end file ---"
        )

    # --- metadata for the LLM's tool schema ---

    @staticmethod
    def schemas() -> list[dict[str, Any]]:
        return [
            {
                "name": "search_brain",
                "description": "Fragment-tolerant search over the user's brain. Returns ranked items with excerpt and 'why matched' reasons.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search fragment."},
                        "k": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                        "since_iso": {"type": ["string", "null"], "description": "Filter items to when_iso >= this YYYY-MM-DD."},
                        "until_iso": {"type": ["string", "null"], "description": "Filter items to when_iso <= this YYYY-MM-DD."},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "open_item",
                "description": "Fetch a single item's full metadata + extracted text by its UUID.",
                "input_schema": {
                    "type": "object",
                    "properties": {"item_id": {"type": "string"}},
                    "required": ["item_id"],
                },
            },
            {
                "name": "open_entity",
                "description": "Fetch an entity's page (description, body, related) plus the items that hook to it.",
                "input_schema": {
                    "type": "object",
                    "properties": {"slug": {"type": "string", "description": "Entity slug (lowercase-hyphenated)."}},
                    "required": ["slug"],
                },
            },
            {
                "name": "list_open_questions",
                "description": "List all unresolved questions the user owes answers to.",
                "input_schema": {"type": "object", "properties": {}},
            },
        ]

    async def dispatch(self, name: str, args: dict[str, Any]) -> Any:
        fn = getattr(self, name, None)
        if fn is None:
            return {"error": f"unknown tool: {name}"}
        try:
            return await fn(**args)
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

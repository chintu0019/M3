"""
M3 Basic Compilation Engine — straightforward LLM-based classification, compilation, and synthesis.

Ships with M3. Gets the job done. The open-source Honda Civic of compilation engines.
"""

import json
import logging
import re

from m3.core.engines.base import (
    Classification,
    CompilationEngine,
    CompileResult,
    ContentType,
    Insight,
    LinkUpdate,
    PageUpdate,
    SynthesisResult,
)
from m3.core.llm import LLMProvider

logger = logging.getLogger("m3.engine.basic")


def _parse_json(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown fences."""
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code fences
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Last resort: find first { and last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from LLM response: {text[:200]}")


class BasicEngine(CompilationEngine):
    def __init__(self, llm: LLMProvider):
        self.llm = llm

    async def classify(
        self,
        content: str,
        content_type: ContentType,
        wiki_index: str,
        wiki_schema: str,
        existing_tags: list[str],
        existing_projects: list[str],
        user_tags: list[str] | None = None,
        user_project: str | None = None,
        user_notes: str | None = None,
    ) -> Classification:
        system = """You are the classification engine for M3, a personal knowledge system.
Your job is to analyze incoming content and classify it.

Rules:
- Prefer existing tags and projects when the content clearly fits them
- Only create new tags/projects when content is genuinely distinct
- Be specific with tags, not generic (prefer "react-hooks" over "programming")
- Identify named entities: people, companies, concepts, places
- Assign a confidence score (0.0-1.0) based on how well you understand the content
- content_type should describe what the content IS: decision, idea, meeting, receipt, reading, person, project-overview, concept, learning, bookmark, quote, etc.
- If the user has provided notes, treat them as authoritative corrections or additional context. They override conflicting information in the content.

Respond with JSON only."""

        notes_block = f"\n\nUser-provided notes (corrections and additional context):\n{user_notes}" if user_notes else ""

        user_msg = f"""Classify this content:

Content type: {content_type.value}
Content:
{content[:4000]}

Current wiki index:
{wiki_index or "(empty wiki)"}

Current wiki schema:
{wiki_schema or "(no schema yet)"}

Existing tags: {json.dumps(existing_tags) if existing_tags else "[]"}
Existing projects: {json.dumps(existing_projects) if existing_projects else "[]"}
User-provided tags: {json.dumps(user_tags) if user_tags else "[]"}
User-provided project: {user_project or "(none)"}{notes_block}

Return JSON:
{{
    "summary": "1-2 sentence summary of the content",
    "tags": ["tag1", "tag2"],
    "project": "project-name or null",
    "content_type": "the type of content (decision, idea, meeting, etc.)",
    "entities": [{{"name": "...", "type": "person|company|concept|place"}}],
    "confidence": 0.85
}}"""

        response = await self.llm.complete(
            messages=[{"role": "user", "content": user_msg}],
            system=system,
            temperature=0.3,
        )
        data = _parse_json(response)

        return Classification(
            summary=data.get("summary", ""),
            tags=data.get("tags", []),
            project=data.get("project"),
            content_type=data.get("content_type", "note"),
            entities=data.get("entities", []),
            confidence=data.get("confidence", 0.5),
        )

    async def compile(
        self,
        classified_item: Classification,
        original_content: str,
        related_pages: list[dict],
        wiki_schema: str,
        user_notes: str | None = None,
    ) -> CompileResult:
        system = """You are the wiki compilation engine for M3, a personal knowledge system.
Your job is to take classified content and produce wiki page updates.

Rules:
- If an existing related page covers this topic, UPDATE it by merging new information. Set page_id to the existing page's ID.
- Only CREATE a new page (page_id: null) if the content represents a genuinely distinct topic.
- Write wiki pages in clear markdown. Be informative but concise.
- Create meaningful cross-links between related topics.
- Each page should have a clear title, category, and type.
- Tags should be specific and useful for filtering.
- link_type can be: references, contradicts, extends, related
- If the user has provided notes, treat them as authoritative. Incorporate their corrections and context into the wiki content.

Respond with JSON only."""

        related_ctx = ""
        if related_pages:
            related_ctx = "\n\nRelated existing pages:\n"
            for p in related_pages[:5]:
                related_ctx += f"\n--- Page: {p['title']} (ID: {p['id']}) ---\n"
                related_ctx += f"Category: {p.get('category', 'none')}\n"
                related_ctx += f"Content:\n{p['content'][:2000]}\n"

        notes_block = f"\n\nUser-provided notes (corrections and additional context):\n{user_notes}" if user_notes else ""

        user_msg = f"""Compile this classified content into wiki page updates:

Classification:
- Summary: {classified_item.summary}
- Tags: {json.dumps(classified_item.tags)}
- Project: {classified_item.project or "none"}
- Content type: {classified_item.content_type}
- Entities: {json.dumps(classified_item.entities)}

Original content:
{original_content[:4000]}

Wiki schema:
{wiki_schema or "(no schema yet)"}
{related_ctx}{notes_block}

Return JSON:
{{
    "pages": [
        {{
            "page_id": "existing-uuid or null for new page",
            "title": "Page Title",
            "content": "Full markdown content",
            "category": "category-name",
            "page_type": "decision|idea|meeting|etc",
            "tags": ["tag1", "tag2"],
            "confidence": 0.85
        }}
    ],
    "links": [
        {{
            "source_title": "Source Page",
            "target_title": "Target Page",
            "link_type": "references|contradicts|extends|related",
            "weight": 1.0
        }}
    ],
    "schema_updates": "Updated schema text or null if no changes needed",
    "changelog_entry": "Brief description of what was added/updated"
}}"""

        response = await self.llm.complete(
            messages=[{"role": "user", "content": user_msg}],
            system=system,
            max_tokens=8192,
            temperature=0.4,
        )
        data = _parse_json(response)

        pages = [
            PageUpdate(
                page_id=p.get("page_id"),
                title=p["title"],
                content=p["content"],
                category=p.get("category"),
                page_type=p.get("page_type", "note"),
                tags=p.get("tags", []),
                confidence=p.get("confidence", 0.5),
            )
            for p in data.get("pages", [])
        ]

        links = [
            LinkUpdate(
                source_title=l["source_title"],
                target_title=l["target_title"],
                link_type=l.get("link_type", "references"),
                weight=l.get("weight", 1.0),
            )
            for l in data.get("links", [])
        ]

        return CompileResult(
            pages=pages,
            links=links,
            schema_updates=data.get("schema_updates"),
            changelog_entry=data.get("changelog_entry", "Content compiled"),
        )

    async def synthesize(
        self,
        wiki_index: str,
        wiki_schema: str,
        recent_changes: list[str],
        all_page_summaries: list[dict],
    ) -> SynthesisResult:
        system = """You are the synthesis engine for M3, a personal knowledge system.
Your job is to cross-reference the entire wiki and surface insights.

Look for:
- Missing cross-links between related pages
- Contradictions between pages
- Stale content that may need updating
- Orphan pages with no connections
- Emerging patterns across content
- Suggestions for new wiki sections or structure changes

Respond with JSON only."""

        summaries_text = ""
        for s in all_page_summaries[:50]:
            summaries_text += f"- {s['title']} ({s.get('category', 'uncategorized')}): {s.get('summary', '')[:150]}\n"

        user_msg = f"""Analyze the wiki and surface insights:

Wiki index:
{wiki_index or "(empty)"}

Wiki schema:
{wiki_schema or "(no schema)"}

Recent changes:
{chr(10).join(recent_changes[-20:]) if recent_changes else "(none)"}

All pages:
{summaries_text}

Return JSON:
{{
    "new_links": [
        {{
            "source_title": "Page A",
            "target_title": "Page B",
            "link_type": "related|references|contradicts|extends",
            "weight": 1.0
        }}
    ],
    "insights": [
        {{
            "type": "stale|contradiction|connection|orphan|suggestion|pattern",
            "title": "Short insight title",
            "description": "Detailed explanation",
            "related_pages": ["Page A", "Page B"]
        }}
    ],
    "schema_updates": "Updated schema text or null",
    "changelog_entries": ["Description of synthesis findings"]
}}"""

        response = await self.llm.complete(
            messages=[{"role": "user", "content": user_msg}],
            system=system,
            max_tokens=8192,
            temperature=0.5,
        )
        data = _parse_json(response)

        new_links = [
            LinkUpdate(
                source_title=l["source_title"],
                target_title=l["target_title"],
                link_type=l.get("link_type", "related"),
                weight=l.get("weight", 1.0),
            )
            for l in data.get("new_links", [])
        ]

        insights = [
            Insight(
                type=i["type"],
                title=i["title"],
                description=i["description"],
                related_pages=i.get("related_pages", []),
            )
            for i in data.get("insights", [])
        ]

        return SynthesisResult(
            new_links=new_links,
            insights=insights,
            schema_updates=data.get("schema_updates"),
            changelog_entries=data.get("changelog_entries", []),
        )

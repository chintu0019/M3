"""
M3 Basic Compilation Engine — straightforward LLM-based classification, compilation, and synthesis.

Ships with M3. Gets the job done. The open-source Honda Civic of compilation engines.
"""

import json
import logging
import re

from m3.core.engines.base import (
    AudioBlock,
    Classification,
    CompilationEngine,
    CompileResult,
    ContentBlock,
    ContentType,
    EngineCapabilities,
    EntityMention,
    ExtractedFact,
    ExtractionResult,
    ImageBlock,
    Insight,
    LinkUpdate,
    PageUpdate,
    ProposedRelationship,
    RenderedPage,
    SynthesisResult,
    TextBlock,
    content_to_text,
)
from m3.core.llm import LLMProvider, Tool

logger = logging.getLogger("m3.engine.basic")


# Suggested vocabularies. The extractor hints these to the model but never
# enforces them — migration 004 dropped all check constraints and added a
# `consolidate_types` pass for reconciling drift.
SUGGESTED_ENTITY_TYPES = [
    "person", "project", "company", "concept", "place", "event", "topic",
]
SUGGESTED_FACT_TYPES = [
    "claim", "decision", "event", "question", "preference", "definition", "attribution",
]
SUGGESTED_ROLES = [
    "subject", "mentioned", "attributed_to", "location", "time",
]


# Single-call tool schema for capable engines. The schema is permissive on
# strings so the model can invent new types; the downstream compiler keeps
# the dim tables in sync.
EXTRACT_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "description": "Every named entity the content mentions. Do not invent any.",
            "items": {
                "type": "object",
                "properties": {
                    "canonical_name": {"type": "string"},
                    "entity_type": {
                        "type": "string",
                        "description": (
                            "Suggested: person, project, company, concept, place, event, topic. "
                            "Invent a new type only if none of these fit."
                        ),
                    },
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "description": {"type": ["string", "null"]},
                    "context": {
                        "type": ["string", "null"],
                        "description": "~20 words from the content that mention this entity.",
                    },
                },
                "required": ["canonical_name", "entity_type"],
            },
        },
        "facts": {
            "type": "array",
            "description": "Atomic one-sentence claims. Each fact must ground in the content.",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "One-sentence claim."},
                    "fact_type": {
                        "type": "string",
                        "description": (
                            "Suggested: claim, decision, event, question, preference, "
                            "definition, attribution. Use 'attribution' for 'X said Y'."
                        ),
                    },
                    "entity_refs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string"},
                                "role": {
                                    "type": "string",
                                    "description": "subject, mentioned, attributed_to, location, time, or invent.",
                                },
                            },
                            "required": ["name", "type", "role"],
                        },
                    },
                    "fact_time_iso": {"type": ["string", "null"]},
                    "source_quote": {
                        "type": ["string", "null"],
                        "description": "Verbatim span <=200 chars from content if possible.",
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["content", "fact_type", "entity_refs"],
            },
        },
        "relationships": {
            "type": "array",
            "description": (
                "Semantic edges between the extracted entities (beyond bare "
                "co-occurrence). Examples: project depends_on concept, "
                "person works_on project, idea extends idea."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "source_name": {"type": "string"},
                    "source_type": {"type": "string"},
                    "target_name": {"type": "string"},
                    "target_type": {"type": "string"},
                    "link_type": {"type": "string"},
                    "rationale": {"type": ["string", "null"]},
                },
                "required": ["source_name", "source_type", "target_name", "target_type", "link_type"],
            },
        },
    },
    "required": ["entities", "facts"],
}


# --- Render tool schema (Task: Phase 3 / render_entity) ---

CONSOLIDATE_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        key: {
            "type": "array",
            "description": (
                f"Merges for {key}. Each entry: merge the row named `from` "
                "into `to`. Only propose a merge when the two names clearly "
                "refer to the same concept (synonym, plural/singular, casing "
                "drift). Prefer the more common survivor."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["from", "to"],
            },
        }
        for key in ("entity_type_merges", "fact_type_merges", "fact_role_merges")
    },
    "required": ["entity_type_merges", "fact_type_merges", "fact_role_merges"],
}


RENDER_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {
            "type": "string",
            "description": (
                "Full markdown page about the entity. Every factual claim "
                "must be followed by a footnote citation of the form "
                "[^<item_id>] where <item_id> is one of the item_ids in the "
                "facts list. Never invent an item_id. Synthesis across "
                "multiple facts is allowed but each synthetic claim still "
                "needs citations for all supporting facts."
            ),
        },
        "overview": {
            "type": "string",
            "description": (
                "One-paragraph summary (<=2 sentences) for list views. "
                "Citations optional here but must still be valid item_ids."
            ),
        },
    },
    "required": ["content", "overview"],
}


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
        self.capabilities = EngineCapabilities(
            single_call_extract=bool(llm.supports_tools),
            native_structured_output=bool(llm.supports_tools),
            multimodal=bool(llm.supports_vision),
            emits_relationships=bool(llm.supports_tools),
            inline_rendering=False,
        )

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

    # --- Entity-centric extract ---

    async def extract(
        self,
        content: str | list[ContentBlock],
        content_type: ContentType,
        user_notes: str | None = None,
    ) -> ExtractionResult:
        """Capable path (tool use, one rich call) when the provider supports
        tools; text-only two-call JSON-repair fallback otherwise.

        Both paths return the same ExtractionResult shape so the compiler is
        ignorant of which ran.
        """
        if self.llm.supports_tools:
            try:
                return await self._extract_capable(content, content_type, user_notes)
            except Exception as e:
                logger.warning(f"Capable extract failed, falling back: {e}")
                # Fall through to text-only path

        return await self._extract_fallback(content, content_type, user_notes)

    async def _extract_capable(
        self,
        content: str | list[ContentBlock],
        content_type: ContentType,
        user_notes: str | None,
    ) -> ExtractionResult:
        """One tool-use call that returns entities, facts, and relationships
        in a schema-validated JSON payload. No char cap on text; capable
        providers have enough context window to consume the full item."""

        system = (
            "You are the extraction engine for M3, a personal knowledge OS. "
            "Given a raw item (text, and possibly images or audio), extract: "
            "(a) every named entity the content mentions, "
            "(b) atomic one-sentence facts grounded in the content, "
            "(c) semantic relationships between entities where the content "
            "makes the relationship explicit (e.g. 'Kato depends on the "
            "public API', 'John works on Kato').\n\n"
            "STRICT RULES — never break these:\n"
            "- Never invent entities or facts that aren't supported by the content.\n"
            "- For 'X said Y' statements use fact_type='attribution' and set "
            "role='attributed_to' on X; don't present Y as fact.\n"
            "- source_quote should be verbatim when you can; paraphrase only "
            "when quoting would be unhelpful.\n"
            "- Types are suggestions, not walls — invent new types only when "
            "none of the suggested ones fit.\n"
            "- Call the extract_knowledge tool exactly once with your output. "
            "Do not reply with prose."
            + (
                "\n\nUser-provided notes override conflicting information in "
                "the content: " + user_notes
                if user_notes else ""
            )
        )

        user_blocks = self._content_to_message_blocks(content, content_type)

        tool = Tool(
            name="extract_knowledge",
            description=(
                "Emit the structured knowledge extracted from this item: "
                "entities, facts with entity references, and any explicit "
                "semantic relationships between entities."
            ),
            input_schema=EXTRACT_TOOL_SCHEMA,
        )
        result = await self.llm.complete_tool(
            messages=[{"role": "user", "content": user_blocks}],
            tools=[tool],
            system=system,
            tool_choice="extract_knowledge",
            max_tokens=8192,
            temperature=0.2,
        )

        data = result.input or {}
        return self._normalize_extraction(data)

    def _content_to_message_blocks(
        self, content: str | list[ContentBlock], content_type: ContentType,
    ) -> list[dict]:
        """Turn the engine's ContentBlock input into Anthropic/OpenAI-style
        message content blocks. Falls back to text if the engine is not
        multimodal."""
        import base64

        if isinstance(content, str):
            return [{"type": "text", "text": f"Content type: {content_type.value}\n\n{content}"}]

        blocks: list[dict] = [{"type": "text", "text": f"Content type: {content_type.value}"}]
        for item in content:
            if isinstance(item, TextBlock):
                blocks.append({"type": "text", "text": item.text})
            elif isinstance(item, ImageBlock) and self.capabilities.multimodal:
                blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": item.media_type,
                        "data": base64.b64encode(item.image_bytes).decode(),
                    },
                })
            elif isinstance(item, AudioBlock) and self.capabilities.multimodal:
                blocks.append({
                    "type": "audio",
                    "source": {
                        "type": "base64",
                        "media_type": item.media_type,
                        "data": base64.b64encode(item.audio_bytes).decode(),
                    },
                })
            else:
                # Block type we can't consume — note it so the model knows
                # something was dropped.
                blocks.append({"type": "text", "text": "[media omitted]"})
        return blocks

    async def _extract_fallback(
        self,
        content: str | list[ContentBlock],
        content_type: ContentType,
        user_notes: str | None,
    ) -> ExtractionResult:
        """Two short LLM calls (entities, then facts) with manual JSON repair.
        No relationships — local models are unreliable enough that keeping
        the schema tight is worth the missing information."""
        text_content = content_to_text(content)

        notes_block = (
            f"\n\nUser-provided notes (corrections and additional context):\n{user_notes}"
            if user_notes else ""
        )

        entities_system = (
            "You are the entity extractor for M3, a personal knowledge system. "
            "List every NAMED entity the content mentions. Suggested types: "
            + ", ".join(SUGGESTED_ENTITY_TYPES) + ". Never invent entities not "
            "in the text. Reply with JSON only."
        )
        entities_schema = (
            '{"entities":[{"canonical_name":"...","entity_type":"...","aliases":["..."],'
            '"description":"... or null","context":"~20 words from the content"}]}'
        )
        entities_user = (
            f"Content (content_type: {content_type.value}):\n---\n{text_content[:6000]}\n---"
            f"{notes_block}\n\nList the entities. Schema:\n{entities_schema}"
        )
        try:
            entities_data = await _llm_json_with_repair(
                self.llm, entities_system, entities_user,
                max_tokens=1500, temperature=0.2, schema_hint=entities_schema,
            )
        except Exception as e:
            logger.warning(f"Fallback entity extraction failed: {e}")
            return ExtractionResult(entities=[], facts=[])

        entities = self._normalize_entities(_unwrap(entities_data, "entities"))
        if not entities:
            return ExtractionResult(entities=[], facts=[])

        entity_list_for_prompt = "\n".join(
            f"- {em.canonical_name} ({em.entity_type})"
            + (f" aka: {', '.join(em.aliases)}" if em.aliases else "")
            for em in entities
        )
        facts_system = (
            "You are the fact extractor for M3. For each atomic claim in the "
            "content, emit one fact grounded in the source. Suggested fact_types: "
            + ", ".join(SUGGESTED_FACT_TYPES) + ". Suggested roles: "
            + ", ".join(SUGGESTED_ROLES) + ". Reply with JSON only."
        )
        facts_schema = (
            '{"facts":[{"content":"one-sentence claim","fact_type":"...",'
            '"entity_refs":[{"name":"...","type":"...","role":"..."}],'
            '"fact_time_iso":"YYYY-MM-DD or null","source_quote":"verbatim span or null",'
            '"confidence":0.0}]}'
        )
        facts_user = (
            f"KNOWN ENTITIES:\n{entity_list_for_prompt}\n\n"
            f"CONTENT (content_type: {content_type.value}):\n---\n{text_content[:6000]}\n---"
            f"{notes_block}\n\nEmit facts. Schema:\n{facts_schema}"
        )
        try:
            facts_data = await _llm_json_with_repair(
                self.llm, facts_system, facts_user,
                max_tokens=2500, temperature=0.2, schema_hint=facts_schema,
            )
        except Exception as e:
            logger.warning(f"Fallback fact extraction failed: {e}")
            return ExtractionResult(entities=entities, facts=[])

        facts = self._normalize_facts(_unwrap(facts_data, "facts"))
        return ExtractionResult(entities=entities, facts=facts, relationships=[])

    # --- Shared normalisation ---

    def _normalize_extraction(self, data: dict) -> ExtractionResult:
        entities = self._normalize_entities(_unwrap(data, "entities"))
        facts = self._normalize_facts(_unwrap(data, "facts"))
        relationships = self._normalize_relationships(_unwrap(data, "relationships"))
        return ExtractionResult(entities=entities, facts=facts, relationships=relationships)

    def _normalize_entities(self, raw: list[dict]) -> list[EntityMention]:
        out: list[EntityMention] = []
        seen: set[tuple[str, str]] = set()
        for e in raw:
            name = (e.get("canonical_name") or "").strip()
            etype = (e.get("entity_type") or "").strip().lower() or "topic"
            if not name:
                continue
            key = (name.lower(), etype)
            if key in seen:
                continue
            seen.add(key)
            aliases_raw = e.get("aliases") or []
            aliases = [a.strip() for a in aliases_raw if isinstance(a, str) and a.strip()]
            out.append(EntityMention(
                canonical_name=name,
                entity_type=etype,
                aliases=aliases,
                description=(e.get("description") or None),
                context=(e.get("context") or None),
            ))
        return out

    def _normalize_facts(self, raw: list[dict]) -> list[ExtractedFact]:
        out: list[ExtractedFact] = []
        for f in raw:
            text_val = (f.get("content") or "").strip()
            ftype = (f.get("fact_type") or "claim").strip().lower() or "claim"
            if not text_val:
                continue
            refs_raw = f.get("entity_refs") or []
            refs = []
            for r in refs_raw:
                rname = (r.get("name") or "").strip()
                rtype = (r.get("type") or "topic").strip().lower() or "topic"
                rrole = (r.get("role") or "subject").strip().lower() or "subject"
                if not rname:
                    continue
                refs.append({"name": rname, "type": rtype, "role": rrole})
            if not refs:
                continue
            try:
                conf = float(f.get("confidence") or 0.5)
            except (TypeError, ValueError):
                conf = 0.5
            out.append(ExtractedFact(
                content=text_val,
                fact_type=ftype,
                entity_refs=refs,
                fact_time_iso=(f.get("fact_time_iso") or None),
                source_quote=(f.get("source_quote") or None),
                confidence=max(0.0, min(1.0, conf)),
            ))
        return out

    def _normalize_relationships(self, raw: list[dict]) -> list[ProposedRelationship]:
        out: list[ProposedRelationship] = []
        for r in raw:
            sn = (r.get("source_name") or "").strip()
            st = (r.get("source_type") or "topic").strip().lower() or "topic"
            tn = (r.get("target_name") or "").strip()
            tt = (r.get("target_type") or "topic").strip().lower() or "topic"
            lt = (r.get("link_type") or "related").strip().lower() or "related"
            if not sn or not tn or sn.lower() == tn.lower():
                continue
            out.append(ProposedRelationship(
                source_name=sn, source_type=st,
                target_name=tn, target_type=tt,
                link_type=lt,
                rationale=(r.get("rationale") or None),
            ))
        return out

    # --- Entity rendering ---

    async def render_entity(
        self,
        entity: dict,
        facts: list[dict],
        related: list[dict] | None = None,
    ) -> RenderedPage:
        related = related or []
        if self.llm.supports_tools:
            try:
                return await self._render_capable(entity, facts, related)
            except Exception as e:
                logger.warning(f"Capable render failed, falling back: {e}")
        return await self._render_fallback(entity, facts, related)

    async def _render_capable(
        self, entity: dict, facts: list[dict], related: list[dict],
    ) -> RenderedPage:
        valid_ids = {str(f["item_id"]) for f in facts if f.get("item_id")}
        facts_block = "\n".join(
            f"{i+1}. [{f['fact_type']}] {f['content']} "
            f"(item_id: {f['item_id']}, role: {f.get('role','')}"
            + (f", source: \"{f['source_quote']}\"" if f.get('source_quote') else "")
            + ")"
            for i, f in enumerate(facts)
        )
        related_block = (
            "\n".join(
                f"- {r['name']} ({r['type']}) via {r['link_type']} [w={r.get('weight', 1)}]"
                for r in related
            ) or "(none)"
        )
        aliases = ", ".join(entity.get("aliases") or []) or "(none)"

        system = (
            "You write entity pages for M3, a personal knowledge base. This "
            "is not Wikipedia — the reader is the owner. Write a clear, useful "
            "markdown page grounded entirely in the supplied facts.\n\n"
            "STRICT RULES:\n"
            "- Every factual claim ends with a footnote citation [^<item_id>].\n"
            "- Only use item_ids from the KNOWN ITEM IDS list. Never invent one.\n"
            "- Synthesis is allowed: combine multiple facts into a sentence as "
            "long as you cite each supporting item_id.\n"
            "- If the facts don't answer something, say so; don't speculate.\n"
            "- Structure is yours to choose; common sections: Overview, "
            "Recent activity, Open questions, Related. Omit any that don't fit.\n"
            "- Call the render_entity tool exactly once with your output."
        )
        user = (
            f"Entity: {entity['canonical_name']} ({entity['entity_type']})\n"
            f"Aliases: {aliases}\n"
            f"Description: {entity.get('description') or '(none)'}\n\n"
            f"Related entities (by link weight):\n{related_block}\n\n"
            f"KNOWN ITEM IDS (use only these in [^...] citations):\n"
            + ", ".join(sorted(valid_ids))
            + f"\n\nFacts (newest first):\n{facts_block}"
        )

        tool = Tool(
            name="render_entity",
            description="Emit the rendered entity page (markdown content + short overview).",
            input_schema=RENDER_TOOL_SCHEMA,
        )
        result = await self.llm.complete_tool(
            messages=[{"role": "user", "content": user}],
            tools=[tool],
            system=system,
            tool_choice="render_entity",
            max_tokens=4096,
            temperature=0.3,
        )
        data = result.input or {}
        return RenderedPage(
            content=(data.get("content") or "").strip(),
            overview=(data.get("overview") or "").strip(),
        )

    async def _render_fallback(
        self, entity: dict, facts: list[dict], related: list[dict],
    ) -> RenderedPage:
        """Local-model-safe path. Tier the facts: older facts get one LLM
        summary paragraph, recent facts (last 30) are dumped as a raw cited
        list. Overview is derived from the summary."""
        recent = facts[:30]
        older = facts[30:]

        header = (
            f"# {entity['canonical_name']}\n\n"
            f"**Type:** {entity['entity_type']}  \n"
        )
        if entity.get("aliases"):
            header += f"**Aliases:** {', '.join(entity['aliases'])}  \n"
        if entity.get("description"):
            header += f"\n{entity['description']}\n"

        summary_md = ""
        overview = ""
        if older:
            older_block = "\n".join(
                f"- {f['content']} [^{f['item_id']}]" for f in older
            )
            prompt = (
                f"Write a 3-5 sentence summary paragraph about "
                f"'{entity['canonical_name']}' based ONLY on these facts. "
                f"Keep each [^<item_id>] citation exactly as written. Do not "
                f"invent facts or citations. Plain markdown, no headers.\n\n"
                f"{older_block}"
            )
            try:
                summary_md = (await self.llm.complete(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=400,
                    temperature=0.3,
                )).strip()
            except Exception as e:
                logger.warning(f"Fallback summary call failed: {e}")
                summary_md = ""
            # Overview = first sentence, stripped of markdown
            if summary_md:
                first = summary_md.split(".")[0].strip()
                overview = first + "." if first else ""

        if not overview and recent:
            # Derive a bare overview from the top fact.
            top = recent[0]
            overview = f"{top['content']} [^{top['item_id']}]"

        recent_block = ""
        if recent:
            recent_block = "## Recent\n\n" + "\n".join(
                f"- {f['content']} [^{f['item_id']}]" for f in recent
            ) + "\n"

        related_block = ""
        if related:
            related_block = "## Related\n\n" + "\n".join(
                f"- {r['name']} ({r['type']}) — {r['link_type']}"
                for r in related
            ) + "\n"

        summary_section = (
            f"## Summary\n\n{summary_md}\n\n" if summary_md else ""
        )
        content = header + "\n" + summary_section + recent_block + related_block
        return RenderedPage(content=content.strip(), overview=overview)

    # --- Type vocabulary consolidation ---

    async def consolidate_types(
        self,
        entity_types: list[dict],
        fact_types: list[dict],
        fact_roles: list[dict],
    ) -> dict[str, list[dict]]:
        """Propose merges across the three free-form vocabularies. Capable
        path calls the LLM via a tool; fallback returns empty lists (local
        models do this badly and silent no-op beats silent drift)."""
        empty = {"entity_types": [], "fact_types": [], "fact_roles": []}
        if not self.llm.supports_tools:
            logger.info(
                "consolidate_types skipped: active LLM does not support tools"
            )
            return empty

        def _lines(rows: list[dict]) -> str:
            if not rows:
                return "(none)"
            return "\n".join(
                f"- {r['name']} (uses={r.get('usage_count', 0)})" for r in rows
            )

        system = (
            "You consolidate free-form type vocabularies in a personal "
            "knowledge base. The user has three vocabularies: entity types "
            "(e.g. person, project), fact types (e.g. claim, decision), and "
            "fact roles (e.g. subject, attributed_to). Each has accumulated "
            "organically; some names drift (e.g. 'individual' and 'person', "
            "'projects' and 'project').\n\n"
            "STRICT RULES:\n"
            "- Only merge when two names clearly refer to the same concept: "
            "synonyms, plural/singular, casing drift.\n"
            "- Prefer the name with the higher usage_count as the survivor "
            "(the `to` field).\n"
            "- Never merge distinct concepts even if semantically related "
            "('person' and 'company' are both agents, but distinct).\n"
            "- If nothing should merge, return empty arrays.\n"
            "- Call consolidate_types exactly once."
        )
        user = (
            f"entity_types:\n{_lines(entity_types)}\n\n"
            f"fact_types:\n{_lines(fact_types)}\n\n"
            f"fact_roles:\n{_lines(fact_roles)}"
        )
        tool = Tool(
            name="consolidate_types",
            description="Emit merges across the three vocabularies.",
            input_schema=CONSOLIDATE_TOOL_SCHEMA,
        )
        try:
            result = await self.llm.complete_tool(
                messages=[{"role": "user", "content": user}],
                tools=[tool],
                system=system,
                tool_choice="consolidate_types",
                max_tokens=1024,
                temperature=0.0,
            )
        except Exception as e:
            logger.warning(f"consolidate_types tool call failed: {e}")
            return empty

        data = result.input or {}

        def _clean(key: str) -> list[dict]:
            raw = data.get(key) or []
            out = []
            for entry in raw:
                frm = (entry.get("from") or "").strip().lower()
                to = (entry.get("to") or "").strip().lower()
                if not frm or not to or frm == to:
                    continue
                out.append({"from": frm, "to": to, "reason": entry.get("reason") or ""})
            return out

        return {
            "entity_types": _clean("entity_type_merges"),
            "fact_types": _clean("fact_type_merges"),
            "fact_roles": _clean("fact_role_merges"),
        }


# --- module-level helper shared by the fallback extract path ---


def _unwrap(data, key: str) -> list:
    """Local models often return a bare JSON array when asked for
    {"<key>": [...]}. Accept both shapes so the extractor doesn't hard-fail
    on a minor schema deviation that still contains the useful payload."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        val = data.get(key)
        if isinstance(val, list):
            return val
        # Sometimes the model wraps under a different key — take the first
        # list-valued field as a last resort.
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


async def _llm_json_with_repair(
    llm: LLMProvider,
    system: str,
    user: str,
    *,
    max_tokens: int = 2048,
    temperature: float = 0.2,
    schema_hint: str = "",
) -> dict:
    """Call the LLM expecting JSON; one repair retry on parse failure.
    Used only by the small-model fallback path in BasicEngine.extract."""
    resp = await llm.complete(
        messages=[{"role": "user", "content": user}],
        system=system,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    try:
        return _parse_json(resp)
    except ValueError as e:
        logger.warning(f"JSON parse failed: {e}; requesting repair")
        repair_user = (
            "Your previous response could not be parsed as JSON. "
            f"Error: {e}\n\nPrevious response (truncated):\n{resp[:1500]}\n\n"
            f"Reply with VALID JSON ONLY, matching this shape:\n{schema_hint}\n"
            "No prose, no markdown fences, no trailing text."
        )
        resp2 = await llm.complete(
            messages=[{"role": "user", "content": repair_user}],
            system=system,
            max_tokens=max_tokens,
            temperature=0.0,
        )
        return _parse_json(resp2)

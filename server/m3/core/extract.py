"""Pydantic models + JSON schema for the process_item LLM tool. Also holds the system prompt."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["personal", "reference", "record", "signal"]
Operation = Literal["append", "replace_section", "revise"]
SelfSlot = Literal["Preferences", "People", "Projects", "Goals", "Context", "Beliefs", "Timeline"]
WhenSource = Literal["explicit_in_content", "inferred_from_metadata", "ingest_time", "unknown"]
StanceValue = Literal["positive", "negative", "uncertain", "neutral"]


class When(BaseModel):
    iso: str | None = None
    source: WhenSource = "unknown"
    note: str | None = None


class Interpretation(BaseModel):
    what_happened: str
    when: When
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class OpenQuestionOut(BaseModel):
    question: str
    context_snippet: str = ""
    blocks: list[str] = Field(default_factory=list)


class HookEntityRef(BaseModel):
    name: str
    match_existing_id: str | None = None
    merge_aliases: list[str] = Field(default_factory=list)


class StanceHook(BaseModel):
    entity_name: str
    value: StanceValue
    evidence_quote: str = ""


class Hooks(BaseModel):
    who: list[HookEntityRef] = Field(default_factory=list)
    what: list[HookEntityRef] = Field(default_factory=list)
    where: list[HookEntityRef] = Field(default_factory=list)
    when: str | None = None
    source: str | None = None
    project: list[str] = Field(default_factory=list)
    stance: list[StanceHook] = Field(default_factory=list)


class SelfUpdate(BaseModel):
    slot: SelfSlot
    operation: Operation
    section_heading: str | None = None
    new_content: str
    change_summary: str
    cites: list[str] = Field(default_factory=list)


class SectionUpdate(BaseModel):
    operation: Operation
    section_heading: str | None = None
    new_content: str
    change_summary: str


class EntityUpdate(BaseModel):
    match_existing_id: str | None = None
    merge_aliases: list[str] = Field(default_factory=list)
    canonical_name: str
    entity_type: str = "topic"
    summary_external: str | None = None
    section_update: SectionUpdate | None = None
    related_entity_names: list[str] = Field(default_factory=list)


class StructuredFields(BaseModel):
    amount: float
    currency: str
    vendor: str
    date: str
    category: str
    due_date: str | None = None
    reference_id: str | None = None


class SignalBlock(BaseModel):
    topic_entities: list[str] = Field(default_factory=list)
    one_line_takeaway: str = ""


class ExtractionOutput(BaseModel):
    kind: Kind
    interpretation: Interpretation
    open_questions: list[OpenQuestionOut] = Field(default_factory=list)
    hooks: Hooks = Field(default_factory=Hooks)
    self_updates: list[SelfUpdate] = Field(default_factory=list)
    entity_updates: list[EntityUpdate] = Field(default_factory=list)
    structured_fields: StructuredFields | None = None
    signal: SignalBlock | None = None


def process_item_tool_schema() -> dict:
    return ExtractionOutput.model_json_schema()


def build_system_prompt(*, today_iso: str, self_doc: str, candidate_entities_block: str) -> str:
    return f"""You are M3's extraction engine. Today is {today_iso}.

You produce structured output describing one raw item. You must follow three rules:

1. TEMPORAL GROUNDING. Resolve relative dates against today. Never leave `interpretation.when.iso`
   as null unless the date is truly unknowable; in that case set `when.source` to "unknown".

2. NO HALLUCINATION. If something is ambiguous (unclear name, mumbled word, unknown referent),
   emit an open_question rather than guessing. Skip any hook that depends on the unresolved piece.
   If `interpretation.confidence` is below 0.6, most of the output should be empty and the
   open_questions array should explain why.

3. DIFF-AWARE UPDATES. Before emitting a self_update or entity_update.section_update, read the
   existing content provided below. Output the *change*: use `replace_section` when revising an
   existing heading, `revise` when the stance or facts actually flipped, `append` only when the
   content is genuinely new. Blind appends are forbidden.

Route every item into one of four kinds:
- personal: user's own notes, thoughts, conversations, voice memos
- reference: articles / papers / books the user saved (neutral summary + user's perspective)
- record: receipts / bills / tickets (structured fields; no narrative page)
- signal: news / tweets / random interesting links (one-line takeaway; no entity page)

# Current self
{self_doc}

# Candidate existing entities (top 20 by vector similarity)
{candidate_entities_block}

Call the `process_item` tool exactly once. Do not reply with prose."""

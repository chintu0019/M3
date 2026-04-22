"""Pydantic models + JSON schema for the process_item LLM tool. Also holds the system prompt."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Kind = Literal["personal", "reference", "record", "signal"]
Operation = Literal["append", "replace_section", "revise"]
SelfSlot = Literal["Preferences", "People", "Projects", "Goals", "Context", "Beliefs", "Timeline"]
WhenSource = Literal["explicit_in_content", "inferred_from_metadata", "ingest_time", "unknown"]
StanceValue = Literal["positive", "negative", "uncertain", "neutral"]


_CANONICAL_SLOTS: set[str] = {"Preferences", "People", "Projects", "Goals", "Context", "Beliefs", "Timeline"}

_SLOT_ALIASES: dict[str, str] = {
    "preference": "Preferences",
    "preferences": "Preferences",
    "person": "People",
    "people": "People",
    "project": "Projects",
    "projects": "Projects",
    "goal": "Goals",
    "goals": "Goals",
    "context": "Context",
    "belief": "Beliefs",
    "beliefs": "Beliefs",
    "timeline": "Timeline",
}

_KIND_ALIASES: dict[str, str] = {
    # personal
    "personal": "personal",
    "note": "personal",
    "notes": "personal",
    "thought": "personal",
    "thoughts": "personal",
    "journal": "personal",
    # reference
    "reference": "reference",
    "article": "reference",
    "paper": "reference",
    "book": "reference",
    # record
    "record": "record",
    "receipt": "record",
    "bill": "record",
    "invoice": "record",
    # signal
    "signal": "signal",
    "news": "signal",
    "tweet": "signal",
    "link": "signal",
}


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

    @field_validator("slot", mode="before")
    @classmethod
    def _coerce_slot(cls, value: Any) -> Any:
        # Pydantic Literal validation is strict; normalise common casing / plural drifts
        # from smaller models before the Literal check runs. Anything outside the known
        # alias/canonical set raises — retry layer catches it.
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if stripped in _CANONICAL_SLOTS:
            return stripped
        mapped = _SLOT_ALIASES.get(stripped.lower())
        if mapped is not None:
            return mapped
        raise ValueError(f"unknown self-update slot: {value!r}")


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

    @field_validator("section_update", mode="before")
    @classmethod
    def _coerce_section_update(cls, value: Any) -> Any:
        # Smaller models sometimes collapse section_update into a single prose string
        # ("Added a history section") instead of the structured dict. Wrap it as an
        # append op so we don't lose the content.
        if isinstance(value, str):
            return {
                "operation": "append",
                "section_heading": None,
                "new_content": value,
                "change_summary": "added narrative",
            }
        return value


class StructuredFields(BaseModel):
    # All fields optional: the LLM may classify something as a record but only pull
    # a subset of the structured fields. ingest.py guards the records.write_record
    # call on amount/vendor/date being present; partial records are dropped rather
    # than crashing the whole ingest.
    amount: float | None = None
    currency: str | None = None
    vendor: str | None = None
    date: str | None = None
    category: str | None = None
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

    @field_validator("kind", mode="before")
    @classmethod
    def _coerce_kind(cls, value: Any) -> Any:
        # Map common synonyms from small models ("note" → "personal", "receipt" →
        # "record", etc.) down to the four canonical kinds. Unknown values fall
        # through and let the Literal check reject them.
        if not isinstance(value, str):
            return value
        mapped = _KIND_ALIASES.get(value.strip().lower())
        return mapped if mapped is not None else value

    @field_validator("signal", mode="before")
    @classmethod
    def _coerce_signal(cls, value: Any) -> Any:
        # Some models emit `signal` as a list of signal objects instead of a single
        # object. Unwrap the first element; empty list becomes None.
        if isinstance(value, list):
            return value[0] if value else None
        return value


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

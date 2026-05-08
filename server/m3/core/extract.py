"""Pydantic models + JSON schema for the process_item LLM tool. Also holds the system prompt."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Kind = Literal["personal", "reference", "record", "signal", "unknown"]
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
    # unknown — reserved for the post-retry fallback path; the LLM should never
    # emit this, but we accept it when ingest.py constructs a fallback
    # ExtractionOutput after validation failed twice.
    "unknown": "unknown",
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


def _coerce_name_or_string(value: Any) -> Any:
    """Accept either a plain string or a `{"name": str, ...}` shape and normalise
    to the string. Observed drift from qwen 7B on 2026-04-23: it emits list-of-
    object where we expect list-of-string (e.g. hooks.project: [{"name": "X"}])."""
    if isinstance(value, dict) and "name" in value:
        return value["name"]
    return value


class Hooks(BaseModel):
    who: list[HookEntityRef] = Field(default_factory=list)
    what: list[HookEntityRef] = Field(default_factory=list)
    where: list[HookEntityRef] = Field(default_factory=list)
    when: str | None = None
    source: str | None = None
    project: list[str] = Field(default_factory=list)
    stance: list[StanceHook] = Field(default_factory=list)

    @field_validator("project", mode="before")
    @classmethod
    def _coerce_project_list(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [_coerce_name_or_string(v) for v in value]
        if isinstance(value, dict):
            # Single-entry object where a list was expected — wrap it.
            return [_coerce_name_or_string(value)]
        if isinstance(value, str):
            # Comma-separated string — seen occasionally from local models.
            return [s.strip() for s in value.split(",") if s.strip()]
        return value

    @field_validator("when", "source", mode="before")
    @classmethod
    def _coerce_optional_string(cls, value: Any) -> Any:
        # Some small models emit {"iso": "..."} or {"name": "..."} where we want
        # a plain string. Pull the obvious string out.
        if isinstance(value, dict):
            for key in ("name", "value", "iso", "text"):
                inner = value.get(key)
                if isinstance(inner, str):
                    return inner
            return None
        return value


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

    @field_validator("merge_aliases", "related_entity_names", mode="before")
    @classmethod
    def _coerce_string_list(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [_coerce_name_or_string(v) for v in value]
        if isinstance(value, dict):
            return [_coerce_name_or_string(value)]
        return value

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


class ClaimOut(BaseModel):
    """One atomic, decontextualized proposition extracted from an item.

    Each claim is meant to stand alone as a single sentence ("M3 is local-first
    by design", "Aditya is leaning into the Pilot Path partnership"). Claims
    become first-class nodes on the canvas, linking the items they were
    extracted from to the entities they're about — the concept-substrate the
    user actually navigates by.
    """
    proposition: str = Field(min_length=4, max_length=400)
    confidence: float = Field(ge=0.0, le=1.0, default=0.7)
    supporting_span: str = Field(default="", max_length=400)
    entity_names: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("entity_names", mode="before")
    @classmethod
    def _coerce_entity_list(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [_coerce_name_or_string(v) for v in value]
        if isinstance(value, dict):
            return [_coerce_name_or_string(value)]
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

    @field_validator("topic_entities", mode="before")
    @classmethod
    def _coerce_topic_list(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [_coerce_name_or_string(v) for v in value]
        if isinstance(value, dict):
            return [_coerce_name_or_string(value)]
        return value


class ExtractionOutput(BaseModel):
    kind: Kind
    interpretation: Interpretation
    open_questions: list[OpenQuestionOut] = Field(default_factory=list)
    hooks: Hooks = Field(default_factory=Hooks)
    self_updates: list[SelfUpdate] = Field(default_factory=list)
    entity_updates: list[EntityUpdate] = Field(default_factory=list)
    claims: list[ClaimOut] = Field(default_factory=list)
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


FEW_SHOT_EXAMPLES: str = """# Worked examples

## Example 1 — personal, person-focused ("I met X")

Input:
"Had coffee with Aditya today. He's leaning into the Pilot Path partnership
conversation. Will loop back next week."

The user is Manoj. Manoj had the coffee; Aditya is the counterparty. The
primary content is an interaction with a person, so the self update goes
to `People`, NOT `Preferences`. Also update the entity page for Aditya.

Correct process_item output (abridged):
{
  "kind": "personal",
  "interpretation": {
    "what_happened": "Manoj met Aditya for coffee; Aditya is leaning in on the Pilot Path partnership.",
    "when": {"iso": "<today>", "source": "ingest_time"},
    "confidence": 0.9
  },
  "open_questions": [],
  "hooks": {
    "who": [{"name": "Aditya"}],
    "project": ["Pilot Path"],
    "stance": []
  },
  "self_updates": [
    {"slot": "People", "operation": "append", "section_heading": null,
     "new_content": "### Aditya\\nCoffee on <today>; leaning into the Pilot Path partnership. Follow up next week.",
     "change_summary": "logged coffee with Aditya", "cites": ["<item_id>"]}
  ],
  "entity_updates": [
    {"canonical_name": "Aditya", "entity_type": "person", "merge_aliases": [],
     "related_entity_names": ["Pilot Path"],
     "section_update": {"operation": "append", "section_heading": null,
       "new_content": "## Your history\\n\\n- <today>: coffee; leaning into Pilot Path partnership.",
       "change_summary": "coffee catch-up"}}
  ],
  "claims": [
    {"proposition": "Aditya is leaning into the Pilot Path partnership conversation.",
     "confidence": 0.9, "supporting_span": "leaning into the Pilot Path partnership conversation",
     "entity_names": ["Aditya", "Pilot Path"]},
    {"proposition": "Manoj met Aditya for coffee and plans to follow up next week.",
     "confidence": 0.85, "supporting_span": "Had coffee with Aditya today.",
     "entity_names": ["Aditya"]}
  ]
}

## Example 2 — personal, stance ("I think X is bad")

Input:
"FluentCRM is the wrong tool for our workflow. We've been burned by its
limitations before. Pushing back on it in the next Pacific sync."

Manoj has a negative stance on FluentCRM. Stance goes to `Beliefs`, not
`Preferences` (Preferences is for lightweight likes/dislikes; stances
with reasons go to Beliefs). Entity update goes on FluentCRM.

Correct process_item output (abridged):
{
  "kind": "personal",
  "interpretation": {
    "what_happened": "Manoj has a negative stance on FluentCRM; plans to push back in the next Pacific sync.",
    "when": {"iso": "<today>", "source": "ingest_time"},
    "confidence": 0.9
  },
  "hooks": {
    "what": [{"name": "FluentCRM"}],
    "project": ["Pacific"],
    "stance": [{"entity_name": "FluentCRM", "value": "negative", "evidence_quote": "wrong tool for our workflow"}]
  },
  "self_updates": [
    {"slot": "Beliefs", "operation": "append", "section_heading": null,
     "new_content": "### FluentCRM\\nWrong tool for our workflow; pushing back in the next Pacific sync.",
     "change_summary": "recorded negative stance", "cites": ["<item_id>"]}
  ],
  "entity_updates": [
    {"canonical_name": "FluentCRM", "entity_type": "tool", "merge_aliases": [],
     "related_entity_names": ["Pacific"],
     "section_update": {"operation": "append", "section_heading": null,
       "new_content": "## Your stance\\n\\n- Wrong tool for our workflow (as of <today>).",
       "change_summary": "negative stance"}}
  ]
}

## Example 3 — personal, project work ("I built/bought X")

Input:
"Bought kesavulu.com from Namecheap to build my portfolio. Working on it
this weekend."

The subject is Manoj. He bought the domain, he's building the portfolio.
This is a project the user owns; goes to `Projects`, NOT `People` and
NOT attributed to any other person. Create a `kesavulu.com portfolio`
project entity; DO NOT create or touch an entity for any name that
happens to appear in the note.

Correct process_item output (abridged):
{
  "kind": "personal",
  "interpretation": {
    "what_happened": "Manoj bought kesavulu.com to build his portfolio site; work ongoing this weekend.",
    "when": {"iso": "<today>", "source": "ingest_time"},
    "confidence": 0.9
  },
  "hooks": {
    "what": [{"name": "kesavulu.com"}, {"name": "Namecheap"}],
    "project": ["portfolio"]
  },
  "self_updates": [
    {"slot": "Projects", "operation": "append", "section_heading": null,
     "new_content": "### Portfolio site (kesavulu.com)\\nDomain purchased from Namecheap <today>. Building this weekend.",
     "change_summary": "new project: portfolio site", "cites": ["<item_id>"]}
  ],
  "entity_updates": [
    {"canonical_name": "kesavulu.com portfolio", "entity_type": "project", "merge_aliases": ["kesavulu.com"],
     "related_entity_names": [],
     "section_update": {"operation": "append", "section_heading": null,
       "new_content": "## Your history\\n\\n- <today>: bought domain from Namecheap; building this weekend.",
       "change_summary": "project kickoff"}}
  ]
}

## Example 4 — reference (article saved for learning)

Input:
"https://example.com/post/attention-is-all-you-need — great refresher on
transformer internals, bookmarked for the Pacific project kickoff."

Correct process_item output (abridged):
{
  "kind": "reference",
  "interpretation": {
    "what_happened": "Bookmarked a transformer internals article; saved for Pacific project context.",
    "when": {"iso": "<today>", "source": "ingest_time"},
    "confidence": 0.9
  },
  "hooks": {
    "what": [{"name": "transformers"}, {"name": "attention mechanisms"}],
    "project": ["Pacific"]
  },
  "entity_updates": [
    {"canonical_name": "Transformers", "entity_type": "concept",
     "summary_external": "Neural network architecture based on attention; seminal paper 'Attention Is All You Need'.",
     "section_update": {"operation": "append", "section_heading": null,
       "new_content": "## Why saved\\n\\nRefresher on internals before the Pacific project kickoff.",
       "change_summary": "saved as reference"},
     "related_entity_names": ["Pacific"]}
  ],
  "claims": [
    {"proposition": "The transformer architecture relies entirely on attention mechanisms.",
     "confidence": 0.85, "supporting_span": "great refresher on transformer internals",
     "entity_names": ["Transformers", "attention mechanisms"]}
  ]
}

## Example 5 — record (receipt)

Input:
"Uber receipt, 2026-04-15: $42.50 USD, home to office. Invoice INV-00123."

Correct process_item output (abridged):
{
  "kind": "record",
  "interpretation": {
    "what_happened": "Uber ride receipt.",
    "when": {"iso": "2026-04-15", "source": "explicit_in_content"},
    "confidence": 0.95
  },
  "hooks": {"what": [{"name": "Uber"}]},
  "structured_fields": {
    "amount": 42.50, "currency": "USD", "vendor": "Uber",
    "date": "2026-04-15", "category": "transportation",
    "due_date": null, "reference_id": "INV-00123"
  }
}

## Example 6 — signal (news link)

Input:
"Anthropic ships Claude 4.7 Sonnet today; 1M context window on Opus."

Correct process_item output (abridged):
{
  "kind": "signal",
  "interpretation": {
    "what_happened": "Anthropic released Claude 4.7 with 1M context on Opus.",
    "when": {"iso": "<today>", "source": "ingest_time"},
    "confidence": 0.95
  },
  "hooks": {"what": [{"name": "Claude"}, {"name": "Anthropic"}]},
  "signal": {
    "topic_entities": ["Anthropic", "Claude"],
    "one_line_takeaway": "Claude 4.7 ships with 1M context on Opus."
  }
}

## Example 7 — ambiguous (raises an open question)

Input:
"Meeting with J tomorrow at 3pm to discuss the Q2 roadmap."

Correct process_item output (abridged):
{
  "kind": "personal",
  "interpretation": {
    "what_happened": "Upcoming meeting about Q2 roadmap; counterparty identity ambiguous.",
    "when": {"iso": "<tomorrow>", "source": "inferred_from_metadata"},
    "confidence": 0.4
  },
  "open_questions": [
    {"question": "Who is J in the roadmap meeting note?",
     "context_snippet": "Meeting with J tomorrow at 3pm to discuss the Q2 roadmap.",
     "blocks": ["hook:who:J"]}
  ],
  "hooks": {"what": [{"name": "Q2 roadmap"}]},
  "self_updates": [],
  "entity_updates": []
}"""


def build_system_prompt(*, today_iso: str, self_doc: str, candidate_entities_block: str) -> str:
    base_prompt = f"""You are M3's extraction engine. Today is {today_iso}.

You produce structured output describing one raw item. You must follow four rules:

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

4. THE USER IS THE IMPLICIT SUBJECT. This content is the user's own. Treat first-person verbs
   ("I bought", "had coffee with", "built", "thought") as the USER'S actions. When a sentence
   says "had coffee with Aditya", the user had the coffee; Aditya is the counterparty, not the
   actor. Never attribute the user's actions to a named third party unless the content explicitly
   says so ("Aditya built X", "Sarah said Y"). A note of the form "bought X for my Y" describes
   something the user did for themselves — do NOT attribute it to any other name that happens
   to appear in the note.

Route every item into one of four kinds:
- personal: user's own notes, thoughts, conversations, voice memos
- reference: articles / papers / books the user saved (neutral summary + user's perspective)
- record: receipts / bills / tickets (structured fields; no narrative page)
- signal: news / tweets / random interesting links (one-line takeaway; no entity page)

# Claims

Emit `claims`: an array of 0–8 atomic, decontextualized propositions present
in the item. A claim is a single sentence that would still make sense out of
context, naming any entity by its canonical name (not "he"/"this"/"the project").
Claims are how the user navigates their brain — they appear as first-class
nodes on the canvas, NOT the raw item text.

Rules for claims:
- Atomic: one proposition per claim, not a paragraph.
- Decontextualized: pronouns and deixis fully resolved.
- Grounded: only emit a claim if a `supporting_span` quote (≤300 chars) from
  the item content actually supports it. Do not invent claims the item doesn't
  contain. If the item is a receipt, signal, or otherwise content-thin, emit
  zero claims — better empty than fabricated.
- Linked: list the canonical names of entities each claim is about under
  `entity_names` (≤6). Use the SAME canonical name you use elsewhere.
- Confidence: 0.5 for plausible-but-implicit, 0.8 for explicit, 0.95 for
  verbatim. Never above 0.95.

Records and signals usually emit 0 claims. Personal and reference items
typically emit 1–4.

# Self slot routing (pick the slot that fits the content's PRIMARY subject)

- Preferences — lightweight likes/dislikes and personal picks, e.g. "I prefer black coffee",
                "I use Linear for tickets". A single adjective about the user's taste.
- People      — who someone is and your relationship to them ("Aditya is a coworker"), or
                notable interactions with them ("Met Aditya for coffee", "Called Sarah about X").
                **Any note whose primary content is about a person (meeting them, talking to
                them, learning something about them) belongs here, NOT in Preferences.**
- Projects    — things the USER is actively working on ("building portfolio at kesavulu.com",
                "rewriting M3"). Not reference material. Not other people's projects.
- Goals       — what the user is trying to achieve, short or long term.
- Context     — the user's current life situation / state / location / phase.
- Beliefs     — stances, opinions, recurring principles with reasoning behind them.
                Stronger and more reasoned than Preferences.
- Timeline    — dated events worth anchoring chronologically.

# Current self
{self_doc}

# Candidate existing entities (top 20 by vector similarity)
{candidate_entities_block}"""

    tail = "Call the `process_item` tool exactly once. Do not reply with prose."

    return base_prompt + "\n\n" + FEW_SHOT_EXAMPLES + "\n\n" + tail

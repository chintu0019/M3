import pytest
from pydantic import ValidationError

from m3.core.extract import ExtractionOutput, process_item_tool_schema


def test_schema_validates_minimal_personal_item():
    data = {
        "kind": "personal",
        "interpretation": {"what_happened": "x", "when": {"iso": None, "source": "unknown"}, "confidence": 0.1},
        "open_questions": [],
        "hooks": {},
        "self_updates": [],
        "entity_updates": [],
    }
    out = ExtractionOutput.model_validate(data)
    assert out.kind == "personal"


def test_schema_rejects_unknown_kind():
    data = {
        "kind": "weirdo",
        "interpretation": {"what_happened": "x", "when": {"iso": None, "source": "unknown"}, "confidence": 0.0},
        "open_questions": [], "hooks": {}, "self_updates": [], "entity_updates": [],
    }
    with pytest.raises(ValidationError):
        ExtractionOutput.model_validate(data)


def test_schema_allows_record_with_structured_fields():
    data = {
        "kind": "record",
        "interpretation": {"what_happened": "uber receipt", "when": {"iso": "2026-04-15", "source": "explicit_in_content"}, "confidence": 0.95},
        "open_questions": [], "hooks": {}, "self_updates": [], "entity_updates": [],
        "structured_fields": {
            "amount": 42.5, "currency": "USD", "vendor": "Uber", "date": "2026-04-15",
            "category": "transportation", "due_date": None, "reference_id": None,
        },
    }
    out = ExtractionOutput.model_validate(data)
    assert out.structured_fields is not None
    assert out.structured_fields.amount == 42.5


def test_process_item_tool_schema_is_valid_json_schema():
    schema = process_item_tool_schema()
    assert schema["type"] == "object"
    assert "kind" in schema["properties"]
    assert "interpretation" in schema["properties"]


def test_system_prompt_includes_few_shot_examples():
    from m3.core.extract import build_system_prompt
    s = build_system_prompt(today_iso="2026-04-19", self_doc="(empty)", candidate_entities_block="(none)")
    assert "Worked examples" in s or "Example 1" in s
    # Should show the shape for each kind
    assert "personal" in s and "reference" in s and "record" in s and "signal" in s
    # An ambiguous example with an open question
    assert "open_questions" in s
    # An entity update shape to encourage filling
    assert "section_update" in s


def test_system_prompt_ends_with_call_instruction():
    from m3.core.extract import build_system_prompt
    s = build_system_prompt(today_iso="2026-04-19", self_doc="", candidate_entities_block="")
    # The final instruction to call the tool should be present, not buried
    assert "process_item" in s.lower()
    assert s.rstrip().endswith("Do not reply with prose.") or "Call the `process_item` tool exactly once" in s


def test_system_prompt_interpolates_today_iso():
    from m3.core.extract import build_system_prompt
    s = build_system_prompt(today_iso="2026-04-19", self_doc="", candidate_entities_block="")
    assert "2026-04-19" in s


def test_system_prompt_has_subject_attribution_rule():
    """Rule 4 guards against mis-attributing the user's actions to named third parties."""
    from m3.core.extract import build_system_prompt
    s = build_system_prompt(today_iso="2026-04-19", self_doc="", candidate_entities_block="")
    assert "THE USER IS THE IMPLICIT SUBJECT" in s
    # Must spell out the specific failure mode we've seen
    assert "coffee with Aditya" in s
    assert "attribute" in s.lower() or "counterparty" in s.lower()


def test_system_prompt_has_slot_routing_guide():
    """The slot guide disambiguates People vs Preferences vs Projects."""
    from m3.core.extract import build_system_prompt
    s = build_system_prompt(today_iso="2026-04-19", self_doc="", candidate_entities_block="")
    # Each canonical slot must appear with a clear description
    for slot in ("Preferences", "People", "Projects", "Goals", "Context", "Beliefs", "Timeline"):
        assert f"- {slot}" in s or f"{slot} " in s, f"slot {slot!r} missing from routing guide"
    # Must explicitly call out the People-vs-Preferences distinction
    assert "People" in s and "Preferences" in s
    assert "NOT in Preferences" in s or "belongs here" in s


def test_few_shots_cover_person_focused_personal_note():
    """Example 1 should model a 'met X for coffee' note landing in People, not Preferences."""
    from m3.core.extract import FEW_SHOT_EXAMPLES
    # The person-focused example must exist and must use the People slot
    assert "coffee with Aditya" in FEW_SHOT_EXAMPLES
    # Must route to People slot
    assert '"slot": "People"' in FEW_SHOT_EXAMPLES
    # Entity update for the person
    assert '"canonical_name": "Aditya"' in FEW_SHOT_EXAMPLES
    assert '"entity_type": "person"' in FEW_SHOT_EXAMPLES


def test_few_shots_cover_project_self_action():
    """Example 3 should model 'I bought/built X for my own project' landing in Projects."""
    from m3.core.extract import FEW_SHOT_EXAMPLES
    # The self-action project example (the kesavulu.com case from real Telegram use)
    assert "kesavulu.com" in FEW_SHOT_EXAMPLES or "my portfolio" in FEW_SHOT_EXAMPLES
    assert '"slot": "Projects"' in FEW_SHOT_EXAMPLES
    # Explicitly NOT attributing the user's purchase to any third-party person
    assert '"entity_type": "project"' in FEW_SHOT_EXAMPLES


def test_schema_accepts_claims_field():
    data = {
        "kind": "personal",
        "interpretation": {"what_happened": "x", "when": {"iso": None, "source": "unknown"}, "confidence": 0.5},
        "open_questions": [], "hooks": {}, "self_updates": [], "entity_updates": [],
        "claims": [
            {"proposition": "M3 is local-first.", "confidence": 0.9, "supporting_span": "M3 is local-first by design.", "entity_names": ["M3"]},
        ],
    }
    out = ExtractionOutput.model_validate(data)
    assert len(out.claims) == 1
    assert out.claims[0].proposition == "M3 is local-first."
    assert out.claims[0].entity_names == ["M3"]


def test_claims_default_to_empty_list():
    data = {
        "kind": "personal",
        "interpretation": {"what_happened": "x", "when": {"iso": None, "source": "unknown"}, "confidence": 0.5},
        "open_questions": [], "hooks": {}, "self_updates": [], "entity_updates": [],
    }
    out = ExtractionOutput.model_validate(data)
    assert out.claims == []


def test_claims_coerces_dict_entity_names():
    """Mirrors the entity_updates coercion: some models emit {"name": "X"}
    instead of "X" inside list fields."""
    data = {
        "kind": "personal",
        "interpretation": {"what_happened": "x", "when": {"iso": None, "source": "unknown"}, "confidence": 0.5},
        "open_questions": [], "hooks": {}, "self_updates": [], "entity_updates": [],
        "claims": [
            {"proposition": "Y is true.", "entity_names": [{"name": "Y"}]},
        ],
    }
    out = ExtractionOutput.model_validate(data)
    assert out.claims[0].entity_names == ["Y"]


def test_system_prompt_documents_claims():
    from m3.core.extract import build_system_prompt
    s = build_system_prompt(today_iso="2026-04-19", self_doc="", candidate_entities_block="")
    # Must explain that claims are atomic propositions
    assert "claims" in s.lower()
    assert "atomic" in s.lower()
    # Must mention the Karpathy-style shape (decontextualized + supporting span)
    assert "decontextualized" in s.lower() or "stand alone" in s.lower()
    assert "supporting_span" in s or "supporting span" in s.lower()

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

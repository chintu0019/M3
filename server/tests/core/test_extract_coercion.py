"""Coercion tests for common LLM shape drifts — see core/extract.py validators."""

import pytest
from pydantic import ValidationError

from m3.core.extract import ExtractionOutput, SelfUpdate, StructuredFields

BASE = {
    "interpretation": {"what_happened": "x", "when": {"iso": None, "source": "unknown"}, "confidence": 0.0},
    "open_questions": [], "hooks": {}, "self_updates": [], "entity_updates": [],
}


def test_signal_as_list_is_coerced():
    data = {"kind": "signal", **BASE,
            "signal": [{"topic_entities": ["X"], "one_line_takeaway": "y"}]}
    out = ExtractionOutput.model_validate(data)
    assert out.signal is not None
    assert out.signal.one_line_takeaway == "y"


def test_signal_as_empty_list_becomes_none():
    data = {"kind": "signal", **BASE, "signal": []}
    out = ExtractionOutput.model_validate(data)
    assert out.signal is None


def test_kind_synonym_note_becomes_personal():
    out = ExtractionOutput.model_validate({"kind": "note", **BASE})
    assert out.kind == "personal"


def test_kind_synonym_receipt_becomes_record():
    out = ExtractionOutput.model_validate({"kind": "receipt", **BASE})
    assert out.kind == "record"


def test_slot_lowercase_beliefs_is_coerced():
    su = SelfUpdate.model_validate({
        "slot": "beliefs", "operation": "append", "new_content": "x",
        "change_summary": "y", "section_heading": None, "cites": [],
    })
    assert su.slot == "Beliefs"


def test_slot_invalid_raises():
    with pytest.raises(ValidationError):
        SelfUpdate.model_validate({
            "slot": "record", "operation": "append", "new_content": "x",
            "change_summary": "y", "section_heading": None, "cites": [],
        })


def test_structured_fields_accept_partial():
    sf = StructuredFields.model_validate({"vendor": "Uber", "date": "2026-04-15"})
    assert sf.vendor == "Uber"
    assert sf.amount is None


def test_section_update_string_is_coerced_to_dict():
    from m3.core.extract import EntityUpdate
    data = {
        "canonical_name": "FluentCRM", "entity_type": "tool",
        "section_update": "Added a history section",
    }
    eu = EntityUpdate.model_validate(data)
    assert eu.section_update is not None
    assert eu.section_update.operation == "append"
    assert "history section" in eu.section_update.new_content

"""reprocess must NOT overwrite a good item meta with a hollow/unknown
extraction on a flaky retry. Regression for the real failure we saw on
2026-04-23 where qwen 7B's retry produced kind=personal but empty
self_updates/entity_updates, and reprocess_one overwrote the original
meta with the hollow result."""

from __future__ import annotations

import uuid as _uuid
from pathlib import Path

import pytest

from m3.brain.items import ItemMeta, read_meta, write_meta
from m3.core.ingest import (
    DegradedReprocessError,
    IngestInput,
    Ingester,
    _detect_degradation,
    _extraction_is_hollow,
)
from m3.core.reprocess import reprocess_one


class _Embedder:
    dim = 768
    async def embed(self, texts):
        return [[0.0] * 768 for _ in texts]


def _output(**over) -> dict:
    data = {
        "kind": "personal",
        "interpretation": {
            "what_happened": "x",
            "when": {"iso": "2026-04-23", "source": "ingest_time"},
            "confidence": 0.9,
        },
        "open_questions": [], "hooks": {},
        "self_updates": [], "entity_updates": [],
    }
    data.update(over)
    return data


class _CannedLLM:
    supports_tools = True
    supports_vision = False
    supports_audio = False
    def __init__(self, response: dict):
        self.response = response
    async def complete_tool(self, **kw):
        from m3.core.llm.base import ToolResult
        return ToolResult(tool_name=kw.get("tool_choice") or "process_item", input=self.response)
    async def complete(self, **kw):
        return ""


# --- pure helpers ---


def test_extraction_is_hollow_empty():
    from m3.core.extract import ExtractionOutput
    parsed = ExtractionOutput.model_validate(_output())
    assert _extraction_is_hollow(parsed) is True


def test_extraction_is_not_hollow_when_self_updates():
    from m3.core.extract import ExtractionOutput
    parsed = ExtractionOutput.model_validate(_output(self_updates=[{
        "slot": "People", "operation": "append", "section_heading": None,
        "new_content": "x", "change_summary": "y", "cites": [],
    }]))
    assert _extraction_is_hollow(parsed) is False


def test_extraction_is_not_hollow_when_hooks_have_entities():
    from m3.core.extract import ExtractionOutput
    parsed = ExtractionOutput.model_validate(_output(hooks={
        "who": [{"name": "Aditya"}], "what": [], "where": [], "project": [], "stance": [],
    }))
    assert _extraction_is_hollow(parsed) is False


def test_detect_degradation_unknown_over_useful():
    from m3.core.extract import ExtractionOutput
    # Existing meta had a real kind
    old = ItemMeta(
        id=_uuid.uuid4(), kind="personal", source="cli",
        created_at="2026-04-22T10:00:00+00:00", original_filename=None,
        extracted_text="x", when_iso=None, when_source="unknown",
        hooks={}, llm_output_raw={"self_updates": [{"slot": "People"}]},
        confidence=0.9,
    )
    # New extraction fell back to unknown
    new = ExtractionOutput.model_validate(_output(kind="unknown"))
    reason = _detect_degradation(old, new)
    assert reason is not None and "unknown" in reason


def test_detect_degradation_hollow_over_useful():
    from m3.core.extract import ExtractionOutput
    old = ItemMeta(
        id=_uuid.uuid4(), kind="personal", source="cli",
        created_at="2026-04-22T10:00:00+00:00", original_filename=None,
        extracted_text="x", when_iso=None, when_source="unknown",
        hooks={}, llm_output_raw={"self_updates": [{"slot": "People"}]},
        confidence=0.9,
    )
    new = ExtractionOutput.model_validate(_output())   # hollow
    reason = _detect_degradation(old, new)
    assert reason is not None and "hollow" in reason


def test_detect_degradation_ok_when_new_has_updates():
    from m3.core.extract import ExtractionOutput
    old = ItemMeta(
        id=_uuid.uuid4(), kind="personal", source="cli",
        created_at="2026-04-22T10:00:00+00:00", original_filename=None,
        extracted_text="x", when_iso=None, when_source="unknown",
        hooks={}, llm_output_raw={"self_updates": [{"slot": "People"}]},
        confidence=0.9,
    )
    new = ExtractionOutput.model_validate(_output(self_updates=[{
        "slot": "Projects", "operation": "append", "section_heading": None,
        "new_content": "x", "change_summary": "y", "cites": [],
    }]))
    assert _detect_degradation(old, new) is None


def test_detect_degradation_none_when_no_existing_meta():
    from m3.core.extract import ExtractionOutput
    new = ExtractionOutput.model_validate(_output())
    assert _detect_degradation(None, new) is None


def test_detect_degradation_ok_when_old_was_also_useless():
    """If the old meta was already hollow, the new one being hollow isn't a degradation."""
    from m3.core.extract import ExtractionOutput
    old = ItemMeta(
        id=_uuid.uuid4(), kind="personal", source="cli",
        created_at="2026-04-22T10:00:00+00:00", original_filename=None,
        extracted_text="x", when_iso=None, when_source="unknown",
        hooks={}, llm_output_raw={"self_updates": [], "entity_updates": [], "hooks": {}},
        confidence=0.1,
    )
    new = ExtractionOutput.model_validate(_output())
    assert _detect_degradation(old, new) is None


# --- integration: reprocess_one with a degrading LLM ---


def _commit(brain: Path, msg: str) -> None:
    import subprocess
    subprocess.run(["git", "add", "-A"], cwd=brain, check=True)
    subprocess.run(["git", "commit", "-q", "-m", msg, "--allow-empty"], cwd=brain, check=True)


@pytest.mark.asyncio
async def test_reprocess_one_refuses_to_degrade_good_meta(tmp_brain: Path):
    """End-to-end: pre-seed a good meta, run reprocess with a hollow LLM,
    verify the old meta survives."""
    item_id = _uuid.UUID("00000000-0000-0000-0000-000000000aaa")

    # Seed a "good" meta directly — self_updates populated, entities mentioned.
    seeded_raw = {
        "kind": "personal",
        "interpretation": {
            "what_happened": "Coffee with Aditya about Pilot Path",
            "when": {"iso": "2026-04-22", "source": "ingest_time"}, "confidence": 0.9,
        },
        "open_questions": [],
        "hooks": {"who": [{"name": "Aditya"}], "what": [], "where": [], "project": ["Pilot Path"], "stance": []},
        "self_updates": [{"slot": "People", "operation": "append", "section_heading": None,
                          "new_content": "Aditya — coffee", "change_summary": "", "cites": []}],
        "entity_updates": [{"canonical_name": "Aditya", "entity_type": "person",
                            "merge_aliases": [], "related_entity_names": [],
                            "section_update": None}],
    }
    write_meta(tmp_brain, ItemMeta(
        id=item_id, kind="personal", source="telegram",
        created_at="2026-04-22T10:00:00+00:00", original_filename=None,
        extracted_text="coffee with Aditya about Pilot Path",
        when_iso="2026-04-22", when_source="ingest_time",
        hooks={"who": [{"name": "Aditya"}], "what": [], "where": [], "project": ["Pilot Path"], "stance": []},
        llm_output_raw=seeded_raw, confidence=0.9,
    ))
    _commit(tmp_brain, "seed good meta")

    # Run reprocess with an LLM that returns a hollow (but valid) payload.
    hollow_llm = _CannedLLM(_output(kind="personal", interpretation={
        "what_happened": "nothing much", "when": {"iso": None, "source": "unknown"}, "confidence": 0.2,
    }))
    result = await reprocess_one(brain_root=tmp_brain, item_id=item_id, llm=hollow_llm, embedder=_Embedder())

    # Reprocess reported the skip with a clear reason
    assert result.items_processed == 0
    assert result.items_skipped == 1
    assert result.errors and "kept existing meta" in result.errors[0]

    # Old meta is preserved verbatim
    preserved = read_meta(tmp_brain, item_id)
    assert preserved is not None
    assert preserved.kind == "personal"
    assert preserved.llm_output_raw.get("self_updates")[0]["slot"] == "People"
    assert preserved.llm_output_raw.get("entity_updates")[0]["canonical_name"] == "Aditya"


@pytest.mark.asyncio
async def test_reprocess_one_applies_when_new_extraction_is_better(tmp_brain: Path):
    """If the new extraction adds content, reprocess should apply it normally."""
    item_id = _uuid.UUID("00000000-0000-0000-0000-000000000bbb")

    # Start from a hollow meta
    write_meta(tmp_brain, ItemMeta(
        id=item_id, kind="personal", source="cli",
        created_at="2026-04-22T10:00:00+00:00", original_filename=None,
        extracted_text="coffee with Aditya",
        when_iso=None, when_source="unknown", hooks={},
        llm_output_raw=_output(), confidence=0.1,
    ))
    _commit(tmp_brain, "seed hollow meta")

    rich_llm = _CannedLLM(_output(
        interpretation={"what_happened": "Coffee catchup", "when": {"iso": "2026-04-22", "source": "ingest_time"}, "confidence": 0.9},
        self_updates=[{"slot": "People", "operation": "append", "section_heading": None,
                       "new_content": "Aditya", "change_summary": "", "cites": []}],
        entity_updates=[{"canonical_name": "Aditya", "entity_type": "person",
                         "merge_aliases": [], "related_entity_names": [], "section_update": None}],
    ))
    result = await reprocess_one(brain_root=tmp_brain, item_id=item_id, llm=rich_llm, embedder=_Embedder())

    assert result.items_processed == 1
    assert result.items_skipped == 0
    # New content landed
    updated = read_meta(tmp_brain, item_id)
    assert updated.llm_output_raw["self_updates"][0]["slot"] == "People"

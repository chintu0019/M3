"""Tests for the reprocess entry points (and the CLI wrapper).

The reprocess pipeline exists so a user can re-run extraction against
already-stored items after the prompt or model has improved. The tests
here exercise:

  * :func:`reprocess_one` against a missing uuid (skipped, not a crash).
  * :func:`reprocess_one` re-writing meta with a *new* LLM output, to
    confirm the stored extraction actually changes when the LLM does.
  * :func:`reprocess_all_unknown` only touching items whose prior kind
    was the ``unknown`` fallback.
  * :func:`reprocess_all` wiping derived state and rebuilding self.md
    from the replay (and preserving items/).
  * The CLI wrapper wiring (``m3 reprocess --all --yes`` happy path).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from m3.brain.items import read_meta
from m3.brain.self_doc import read_section
from m3.cli import app
from m3.core.ingest import IngestInput, Ingester
from m3.core.reprocess import reprocess_all, reprocess_all_unknown, reprocess_one


class _Embedder:
    dim = 768

    async def embed(self, texts):
        return [[0.0] * 768 for _ in texts]


class _SequencedLLM:
    """Returns each response in ``responses`` in order, one per ``complete_tool`` call.

    Clones the conftest FakeLLM's shape but keyed by call count rather
    than message substring — this lets us simulate "LLM gives output A
    on first ingest, output B on reprocess" without juggling text keys.
    """

    supports_tools = True
    supports_vision = False
    supports_audio = False

    def __init__(self, responses: list[dict[str, Any]]):
        self._responses = responses
        self._idx = 0
        self.calls: list[dict[str, Any]] = []

    async def complete_tool(
        self,
        messages,
        tools,
        system=None,
        tool_choice=None,
        max_tokens=4096,
        temperature=0.2,
    ):
        from m3.core.llm.base import ToolResult

        self.calls.append({"messages": messages, "system": system, "tool_choice": tool_choice})
        resp = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return ToolResult(tool_name=tool_choice or "process_item", input=resp)


def _personal_output(what: str, pref_line: str) -> dict[str, Any]:
    return {
        "kind": "personal",
        "interpretation": {
            "what_happened": what,
            "when": {"iso": "2026-04-22", "source": "ingest_time"},
            "confidence": 0.9,
        },
        "open_questions": [],
        "hooks": {"who": [], "what": [], "where": [], "when": "2026-04-22",
                  "source": "cli", "project": [], "stance": []},
        "self_updates": [{
            "slot": "Preferences", "operation": "append", "section_heading": None,
            "new_content": pref_line, "change_summary": "pref", "cites": [],
        }],
        "entity_updates": [],
    }


def _unknown_output() -> dict[str, Any]:
    return {
        "kind": "unknown",
        "interpretation": {
            "what_happened": "[extraction failed] garbled",
            "when": {"iso": None, "source": "unknown"},
            "confidence": 0.0,
        },
        "open_questions": [{"question": "review", "context_snippet": "garbled", "blocks": []}],
        "hooks": {"who": [], "what": [], "where": [], "when": None,
                  "source": "cli", "project": [], "stance": []},
        "self_updates": [], "entity_updates": [],
    }


async def _ingest_with(brain_root: Path, llm, *, text: str, item_id: uuid.UUID) -> None:
    ingester = Ingester(brain_root=brain_root, llm=llm, embedder=_Embedder())
    await ingester.ingest(IngestInput(
        item_id=item_id, source="cli", original_bytes=None, original_filename=None,
        content_type="text", text=text,
    ))


# ---------------------------------------------------------------------------
# reprocess_one
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reprocess_one_missing_uuid_returns_skipped(tmp_brain: Path):
    """No meta on disk → one skipped, zero processed, one error noting the miss."""
    llm = _SequencedLLM([_personal_output("x", "### x\n- x")])
    result = await reprocess_one(
        brain_root=tmp_brain,
        item_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        llm=llm, embedder=_Embedder(),
    )
    assert result.items_processed == 0
    assert result.items_skipped == 1
    assert result.errors and "not found" in result.errors[0]


@pytest.mark.asyncio
async def test_reprocess_one_rewrites_meta_with_new_llm_output(tmp_brain: Path):
    """A second LLM response should land in llm_output_raw after reprocess.

    We ingest once with response A, then reprocess with a fresh LLM that
    returns response B. The meta's ``llm_output_raw.interpretation.what_happened``
    must reflect B, proving the pipeline actually re-extracted rather than
    just no-oping.
    """
    item_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    first = _SequencedLLM([_personal_output("first pass", "### A\n- first")])
    await _ingest_with(tmp_brain, first, text="note body", item_id=item_id)
    before = read_meta(tmp_brain, item_id)
    assert before is not None
    assert before.llm_output_raw["interpretation"]["what_happened"] == "first pass"

    second = _SequencedLLM([_personal_output("second pass", "### A\n- second")])
    result = await reprocess_one(
        brain_root=tmp_brain, item_id=item_id, llm=second, embedder=_Embedder(),
    )
    assert result.items_processed == 1
    assert result.items_skipped == 0
    assert result.errors == []

    after = read_meta(tmp_brain, item_id)
    assert after is not None
    assert after.llm_output_raw["interpretation"]["what_happened"] == "second pass"


# ---------------------------------------------------------------------------
# reprocess_all_unknown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reprocess_all_unknown_only_touches_unknown_kind(tmp_brain: Path):
    """Ingest one personal + one unknown item; reprocess-unknown should only
    run the LLM once more, for the unknown item."""
    personal_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    unknown_id = uuid.UUID("33333333-3333-3333-3333-333333333333")

    personal_llm = _SequencedLLM([_personal_output("keep me", "### K\n- keep")])
    await _ingest_with(tmp_brain, personal_llm, text="personal text", item_id=personal_id)

    unknown_llm = _SequencedLLM([_unknown_output()])
    await _ingest_with(tmp_brain, unknown_llm, text="garbled text", item_id=unknown_id)
    assert read_meta(tmp_brain, unknown_id).kind == "unknown"  # type: ignore[union-attr]

    # New LLM promotes the unknown item to personal. The personal item
    # should be untouched — its meta must still say "keep me".
    replay = _SequencedLLM([_personal_output("now extractable", "### N\n- now")])
    result = await reprocess_all_unknown(
        brain_root=tmp_brain, llm=replay, embedder=_Embedder(),
    )
    assert result.items_processed == 1
    assert result.items_skipped == 1  # the personal item skipped
    assert result.errors == []
    assert len(replay.calls) == 1  # exactly one reprocess call

    after_unknown = read_meta(tmp_brain, unknown_id)
    assert after_unknown is not None and after_unknown.kind == "personal"
    after_personal = read_meta(tmp_brain, personal_id)
    assert after_personal is not None
    assert after_personal.llm_output_raw["interpretation"]["what_happened"] == "keep me"


# ---------------------------------------------------------------------------
# reprocess_all
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reprocess_all_wipes_and_replays(tmp_brain: Path):
    """After --all, self.md must reflect the NEW extraction only."""
    item_id = uuid.UUID("44444444-4444-4444-4444-444444444444")
    old_llm = _SequencedLLM([_personal_output("old", "### OldPref\n- stale")])
    await _ingest_with(tmp_brain, old_llm, text="something", item_id=item_id)
    assert "OldPref" in read_section(tmp_brain, "Preferences")

    new_llm = _SequencedLLM([_personal_output("new", "### NewPref\n- fresh")])
    result = await reprocess_all(
        brain_root=tmp_brain, llm=new_llm, embedder=_Embedder(),
    )
    assert result.items_processed == 1
    assert result.items_skipped == 0
    assert result.errors == []

    prefs = read_section(tmp_brain, "Preferences")
    assert "NewPref" in prefs
    assert "OldPref" not in prefs  # the wipe really happened


@pytest.mark.asyncio
async def test_reprocess_all_preserves_items_directory(tmp_brain: Path):
    """items/originals + items/meta must survive the wipe."""
    item_id = uuid.UUID("55555555-5555-5555-5555-555555555555")
    llm = _SequencedLLM([_personal_output("keep", "### K\n- keep")])
    await _ingest_with(tmp_brain, llm, text="keep body", item_id=item_id)

    meta_path = tmp_brain / "items" / "meta" / f"{item_id}.json"
    assert meta_path.exists()
    meta_mtime_before = meta_path.stat().st_mtime

    replay = _SequencedLLM([_personal_output("keep2", "### K\n- keep2")])
    result = await reprocess_all(
        brain_root=tmp_brain, llm=replay, embedder=_Embedder(),
    )
    assert result.items_processed == 1
    assert meta_path.exists()
    # Meta was overwritten by the replay (so mtime may advance) but the
    # directory + file still exist. Confirm the body text is preserved.
    after = read_meta(tmp_brain, item_id)
    assert after is not None
    assert after.extracted_text == "keep body"
    _ = meta_mtime_before  # reference to keep intent explicit


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_reprocess_all_yes_happy_path(tmp_path: Path, monkeypatch):
    """End-to-end: init → ingest → `m3 reprocess --all --yes` exits cleanly."""
    for key, val in {
        "GIT_AUTHOR_NAME": "m3-test", "GIT_AUTHOR_EMAIL": "test@m3.local",
        "GIT_COMMITTER_NAME": "m3-test", "GIT_COMMITTER_EMAIL": "test@m3.local",
        "M3_LLM_PROVIDER": "fake",
    }.items():
        monkeypatch.setenv(key, val)

    runner = CliRunner()
    brain = tmp_path / "brain"
    assert runner.invoke(app, ["init", "--brain", str(brain)]).exit_code == 0

    note = tmp_path / "note.txt"
    note.write_text("hello world")
    assert runner.invoke(app, ["ingest", str(note), "--brain", str(brain)]).exit_code == 0

    result = runner.invoke(app, ["reprocess", "--all", "--yes", "--brain", str(brain)])
    assert result.exit_code == 0, result.output
    assert "processed: 1" in result.output

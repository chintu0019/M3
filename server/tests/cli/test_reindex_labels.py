import uuid as _u
from pathlib import Path

import pytest
from typer.testing import CliRunner

from m3.brain.items import ItemMeta, write_meta, read_meta
from m3.brain.claims import ClaimMeta, write_claim, read_claim
from m3.cli import app


class _FakeLLM:
    """Matches LLMProvider.complete shape; returns a canned headline."""
    async def complete(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        return "TEST HEADLINE"


def test_reindex_labels_backfills_titles_and_headlines(
    tmp_brain: Path, monkeypatch: pytest.MonkeyPatch,
):
    iid = _u.uuid4()
    cid = _u.uuid4()
    write_meta(tmp_brain, ItemMeta(
        id=iid, kind="personal", source="test", created_at="2026-01-01T00:00:00Z",
        original_filename="notes.md",
        extracted_text='---\ntitle: "Manoj Kesavulu"\n---\n\nbody',
        when_iso=None, when_source="ingest_time", hooks={},
        # title intentionally None
    ))
    write_claim(tmp_brain, ClaimMeta(
        id=cid, item_id=iid,
        proposition="A real claim about something.",
        confidence=0.8, supporting_span="...",
        entity_slugs=[], created_at="2026-01-01T00:00:00Z",
        # headline intentionally ""
    ))

    monkeypatch.setattr("m3.cli._make_llm", lambda: _FakeLLM())
    result = CliRunner().invoke(app, ["reindex", "--labels", "--brain", str(tmp_brain)])
    assert result.exit_code == 0, result.output
    assert "updated 1 item titles and 1 claim headlines" in result.output

    refreshed_item = read_meta(tmp_brain, iid)
    assert refreshed_item is not None
    assert refreshed_item.title == "Manoj Kesavulu"

    refreshed_claim = read_claim(tmp_brain, cid)
    assert refreshed_claim is not None
    assert refreshed_claim.headline == "TEST HEADLINE"


def test_reindex_labels_skips_already_populated(
    tmp_brain: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Items / claims that already have title / headline are left alone."""
    iid = _u.uuid4()
    cid = _u.uuid4()
    write_meta(tmp_brain, ItemMeta(
        id=iid, kind="personal", source="test", created_at="2026-01-01T00:00:00Z",
        original_filename=None, extracted_text="x",
        when_iso=None, when_source="ingest_time", hooks={},
        title="Already Set",
    ))
    write_claim(tmp_brain, ClaimMeta(
        id=cid, item_id=iid, proposition="x.", confidence=0.5, supporting_span="...",
        entity_slugs=[], created_at="2026-01-01T00:00:00Z",
        headline="Already Set",
    ))

    monkeypatch.setattr("m3.cli._make_llm", lambda: _FakeLLM())
    result = CliRunner().invoke(app, ["reindex", "--labels", "--brain", str(tmp_brain)])
    assert result.exit_code == 0
    assert "updated 0 item titles and 0 claim headlines" in result.output

    # Confirm nothing was overwritten.
    assert read_meta(tmp_brain, iid).title == "Already Set"
    assert read_claim(tmp_brain, cid).headline == "Already Set"

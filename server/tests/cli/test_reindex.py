"""Tests for `m3 reindex --topical` — the canvas v2 backfill command.

The plain `m3 reindex` rebuilds FTS / hooks / vectors. The `--topical`
flag instead walks every entity / item / claim / synthesis in the brain
and refreshes its topical signature, populating
~/brain/index/topical.sqlite. This is what existing brains need to run
once before canvas v2 can lay them out.
"""

from __future__ import annotations

import uuid as _uuid
from pathlib import Path

import pytest
from typer.testing import CliRunner

from m3.brain.claims import ClaimMeta, write_claim
from m3.brain.entity_doc import EntityDoc, upsert as write_entity
from m3.brain.items import ItemMeta, write_meta
from m3.brain.synthesis import SynthesisMeta, write_synthesis
from m3.brain.topical import TopicalIndex
from m3.cli import app


class _DetEmbedder:
    """768-dim deterministic embedder. Vector value scales with text length so
    different inputs produce distinguishable vectors without firing fastembed."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t)) / 1000.0] * 768 for t in texts]


def _seed_entity(brain_root: Path, *, name: str, body: str) -> None:
    write_entity(
        brain_root,
        EntityDoc(canonical_name=name, entity_type="person", body=body),
    )


def _seed_item(brain_root: Path, *, item_id: _uuid.UUID, text: str) -> None:
    write_meta(
        brain_root,
        ItemMeta(
            id=item_id,
            kind="personal",
            source="test",
            created_at="2026-01-01T00:00:00Z",
            original_filename=None,
            extracted_text=text,
            when_iso=None,
            when_source="ingest_time",
            hooks={},
        ),
    )


def test_reindex_topical_backfills_existing_brain(
    tmp_brain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre-populate one of every node type, then run `m3 reindex --topical`
    and assert each landed in the topical index keyed by its canvas node id."""
    _seed_entity(tmp_brain, name="Manoj", body="CTO at Acme.")
    item_id = _uuid.uuid4()
    _seed_item(tmp_brain, item_id=item_id, text="Had a call with Manoj.")
    claim = ClaimMeta(
        id=_uuid.uuid4(),
        item_id=item_id,
        proposition="Manoj prefers minimalism.",
        confidence=0.9,
        supporting_span="Manoj prefers minimalism.",
        entity_slugs=["manoj"],
        created_at="2026-01-01T00:00:00Z",
    )
    write_claim(tmp_brain, claim)
    synth = SynthesisMeta(
        id=_uuid.uuid4(),
        entity_slug="manoj",
        summary="Manoj is a minimalist CTO.",
    )
    write_synthesis(tmp_brain, synth)

    monkeypatch.setattr("m3.cli._make_embedder", lambda: _DetEmbedder())

    runner = CliRunner()
    result = runner.invoke(app, ["reindex", "--topical", "--brain", str(tmp_brain)])
    assert result.exit_code == 0, result.output

    idx = TopicalIndex.open(tmp_brain)
    try:
        keys = {nid for nid, _ in idx.iter_all()}
    finally:
        idx.close()
    assert "entity:manoj" in keys, f"missing entity signature: {keys}"
    assert f"item:{item_id}" in keys, f"missing item signature: {keys}"
    assert f"claim:{claim.id}" in keys, f"missing claim signature: {keys}"
    assert "synthesis:manoj" in keys, f"missing synthesis signature: {keys}"


def test_reindex_topical_reports_count(
    tmp_brain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_entity(tmp_brain, name="A", body="One.")
    _seed_entity(tmp_brain, name="B", body="Two.")
    monkeypatch.setattr("m3.cli._make_embedder", lambda: _DetEmbedder())

    runner = CliRunner()
    result = runner.invoke(app, ["reindex", "--topical", "--brain", str(tmp_brain)])
    assert result.exit_code == 0, result.output
    assert "refreshed" in result.output.lower()
    assert "2" in result.output


def test_reindex_without_topical_runs_existing_path(
    tmp_brain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sanity: the existing reindex (no --topical) still works and does NOT
    populate the topical index."""
    _seed_item(tmp_brain, item_id=_uuid.uuid4(), text="anything")
    monkeypatch.setattr("m3.cli._make_embedder", lambda: _DetEmbedder())

    runner = CliRunner()
    result = runner.invoke(app, ["reindex", "--brain", str(tmp_brain)])
    assert result.exit_code == 0, result.output

    idx = TopicalIndex.open(tmp_brain)
    try:
        rows = list(idx.iter_all())
    finally:
        idx.close()
    assert rows == []


def test_reindex_topical_continues_on_per_record_error(
    tmp_brain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One bad embedding shouldn't abort the whole backfill — the CLI should
    keep going and report the failure at the end."""
    _seed_entity(tmp_brain, name="A", body="One.")
    _seed_entity(tmp_brain, name="B", body="Two.")
    _seed_entity(tmp_brain, name="C", body="Three.")

    class _FlakyEmbedder:
        def __init__(self) -> None:
            self.calls = 0

        async def embed(self, texts: list[str]) -> list[list[float]]:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("simulated embedder hiccup")
            return [[float(len(t)) / 1000.0] * 768 for t in texts]

    flaky = _FlakyEmbedder()
    monkeypatch.setattr("m3.cli._make_embedder", lambda: flaky)

    runner = CliRunner()
    result = runner.invoke(app, ["reindex", "--topical", "--brain", str(tmp_brain)])
    assert result.exit_code == 0, result.output
    # Should report 2 refreshed (out of 3 attempted) and one error line.
    assert "refreshed 2" in result.output
    assert "simulated embedder hiccup" in result.output

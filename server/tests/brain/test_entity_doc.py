from pathlib import Path

import pytest

from m3.brain.entity_doc import EntityDoc, load, slugify, upsert


def test_slugify_handles_spaces_and_case():
    assert slugify("Pilot Path") == "pilot-path"
    assert slugify("PilotPath Group") == "pilotpath-group"
    assert slugify("Anthropic, Inc.") == "anthropic-inc"


def test_upsert_creates_new_entity_file(tmp_brain: Path):
    doc = EntityDoc(
        canonical_name="Pilot Path", entity_type="company",
        aliases=["PilotPath", "Pilot Path Group"], description="Company context",
        related=[], signal_mentions=0, summary_external=None,
        body="## Your history\n\n(nothing yet)\n",
    )
    upsert(tmp_brain, doc)
    path = tmp_brain / "entities" / "pilot-path.md"
    assert path.is_file()
    text = path.read_text()
    assert "canonical_name: Pilot Path" in text
    assert "## Your history" in text


def test_load_roundtrip(tmp_brain: Path):
    doc = EntityDoc(
        canonical_name="Aditya", entity_type="person",
        aliases=["Adi"], description="Coworker",
        related=["pilot-path"], signal_mentions=0, summary_external=None,
        body="## Your history\n\nMet 2026-04-18 [^abc].\n",
    )
    upsert(tmp_brain, doc)
    loaded = load(tmp_brain, slug="aditya")
    assert loaded == doc


def test_upsert_merges_aliases_union(tmp_brain: Path):
    upsert(tmp_brain, EntityDoc(
        canonical_name="Pilot Path", entity_type="company",
        aliases=["PilotPath"], description=None, related=[],
        signal_mentions=0, summary_external=None, body="",
    ))
    upsert(tmp_brain, EntityDoc(
        canonical_name="Pilot Path", entity_type="company",
        aliases=["Pilot Path Group"], description=None, related=[],
        signal_mentions=0, summary_external=None, body="",
    ))
    loaded = load(tmp_brain, slug="pilot-path")
    assert set(loaded.aliases) == {"PilotPath", "Pilot Path Group"}


def test_load_missing_returns_none(tmp_brain: Path):
    assert load(tmp_brain, slug="nope") is None

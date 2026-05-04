from pathlib import Path

import pytest

from m3.brain.entity_doc import EntityDoc, consolidate, load, slugify, upsert


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


def test_consolidate_renames_when_match_existing_slug_differs(tmp_brain: Path):
    upsert(tmp_brain, EntityDoc(
        canonical_name="Pilot Path", entity_type="company",
        aliases=["PilotPath"], description=None, related=[],
        signal_mentions=3, summary_external=None,
        body="## Your history\n\n- earlier note\n",
    ))
    consolidate(
        tmp_brain,
        canonical_name="Pilot Path Group",
        entity_type="company",
        merge_aliases=[],
        match_existing_slug="pilot-path",
        body="## Your history\n\n- new note\n",
    )
    assert (tmp_brain / "entities" / "pilot-path-group.md").is_file()
    assert not (tmp_brain / "entities" / "pilot-path.md").exists()
    loaded = load(tmp_brain, slug="pilot-path-group")
    assert loaded is not None
    assert "Pilot Path" in loaded.aliases
    assert "PilotPath" in loaded.aliases
    # Body from the old file folds in after a --- separator.
    assert "- new note" in loaded.body
    assert "- earlier note" in loaded.body
    assert "---" in loaded.body
    # Signal mentions carry over.
    assert loaded.signal_mentions == 3


def test_consolidate_folds_alias_files_into_canonical(tmp_brain: Path):
    upsert(tmp_brain, EntityDoc(
        canonical_name="PilotPath", entity_type="company",
        aliases=[], description=None, related=["aditya"], signal_mentions=1,
        summary_external=None, body="## Old A\n\n- from file A\n",
    ))
    upsert(tmp_brain, EntityDoc(
        canonical_name="Pilot Path Group", entity_type="company",
        aliases=[], description=None, related=[], signal_mentions=2,
        summary_external=None, body="## Old B\n\n- from file B\n",
    ))
    consolidate(
        tmp_brain,
        canonical_name="Pilot Path",
        entity_type="company",
        merge_aliases=["PilotPath", "Pilot Path Group"],
        body="## Canonical\n\n- canonical note\n",
    )
    assert (tmp_brain / "entities" / "pilot-path.md").is_file()
    assert not (tmp_brain / "entities" / "pilotpath.md").exists()
    assert not (tmp_brain / "entities" / "pilot-path-group.md").exists()
    loaded = load(tmp_brain, slug="pilot-path")
    assert loaded is not None
    assert set(loaded.aliases) >= {"PilotPath", "Pilot Path Group"}
    assert "- from file A" in loaded.body
    assert "- from file B" in loaded.body
    assert "- canonical note" in loaded.body
    # Related slugs preserved from folded files.
    assert "aditya" in loaded.related
    # signal_mentions accumulate.
    assert loaded.signal_mentions == 3


def test_consolidate_new_entity_path_is_normal_upsert(tmp_brain: Path):
    consolidate(
        tmp_brain,
        canonical_name="Mixpanel",
        entity_type="company",
        merge_aliases=["Mixpanel Inc"],   # no existing file with this slug
        body="## Context\n\n- first mention\n",
    )
    assert (tmp_brain / "entities" / "mixpanel.md").is_file()
    loaded = load(tmp_brain, slug="mixpanel")
    assert loaded is not None
    assert loaded.canonical_name == "Mixpanel"
    assert "Mixpanel Inc" in loaded.aliases
    assert "- first mention" in loaded.body

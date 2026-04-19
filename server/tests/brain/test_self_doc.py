from pathlib import Path

import pytest

from m3.brain.self_doc import SelfDocError, apply_update, read_section


def test_read_section_returns_empty_placeholder_for_fresh_slot(tmp_brain: Path):
    assert read_section(tmp_brain, "Preferences") == "_(empty)_"


def test_apply_append_adds_to_section(tmp_brain: Path):
    apply_update(tmp_brain, slot="Preferences", operation="append", new_content="- Dislikes FluentCRM.", heading=None)
    body = (tmp_brain / "self.md").read_text()
    assert "- Dislikes FluentCRM." in body
    # append preserves slot heading and order
    assert body.index("## Preferences") < body.index("- Dislikes FluentCRM.") < body.index("## People")


def test_apply_append_replaces_empty_placeholder_first_time(tmp_brain: Path):
    apply_update(tmp_brain, slot="Goals", operation="append", new_content="- Ship M3 rebuild.", heading=None)
    assert "_(empty)_" not in read_section(tmp_brain, "Goals")
    assert "- Ship M3 rebuild." in read_section(tmp_brain, "Goals")


def test_apply_replace_section_swaps_named_heading(tmp_brain: Path):
    apply_update(tmp_brain, slot="Preferences", operation="append", new_content="### FluentCRM\nNeutral.", heading=None)
    apply_update(
        tmp_brain, slot="Preferences", operation="replace_section",
        new_content="### FluentCRM\nDisliked — wrong tool for our workflow.", heading="### FluentCRM",
    )
    pref = read_section(tmp_brain, "Preferences")
    assert "Neutral." not in pref
    assert "Disliked — wrong tool for our workflow." in pref


def test_apply_revise_replaces_by_heading_and_returns_prior_content(tmp_brain: Path):
    apply_update(tmp_brain, slot="Beliefs", operation="append", new_content="### Tools\nSimple beats clever.", heading=None)
    prior = apply_update(
        tmp_brain, slot="Beliefs", operation="revise",
        new_content="### Tools\nSimple usually beats clever, but not always.", heading="### Tools",
    )
    assert "Simple beats clever." in prior
    assert "usually beats clever" in read_section(tmp_brain, "Beliefs")


def test_apply_unknown_slot_raises(tmp_brain: Path):
    with pytest.raises(SelfDocError):
        apply_update(tmp_brain, slot="NotASlot", operation="append", new_content="x", heading=None)


def test_apply_replace_section_missing_heading_raises(tmp_brain: Path):
    with pytest.raises(SelfDocError):
        apply_update(tmp_brain, slot="People", operation="replace_section", new_content="x", heading="### Nobody")

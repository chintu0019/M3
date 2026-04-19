from pathlib import Path

from m3.brain.changelog import append


def test_append_writes_dated_line(tmp_brain: Path):
    append(tmp_brain, timestamp="2026-04-19T10:00:00Z", target="self.md#Preferences", summary="Added FluentCRM stance")
    text = (tmp_brain / "changelog.md").read_text()
    assert "2026-04-19T10:00:00Z" in text
    assert "self.md#Preferences" in text
    assert "Added FluentCRM stance" in text


def test_append_preserves_history(tmp_brain: Path):
    append(tmp_brain, timestamp="2026-04-19T10:00:00Z", target="a", summary="one")
    append(tmp_brain, timestamp="2026-04-19T10:01:00Z", target="b", summary="two")
    text = (tmp_brain / "changelog.md").read_text()
    assert text.index("one") < text.index("two")

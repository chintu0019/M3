import json
import uuid
from pathlib import Path

from m3.brain.entity_doc import EntityDoc, load, upsert
from m3.brain.signals import Signal, append_signal, bump_mention_count


def test_append_signal_writes_to_month_file(tmp_brain: Path):
    sig = Signal(
        item_id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        date="2026-04-19",
        topic_entities=["Anthropic"],
        one_line_takeaway="Claude 4.7 ships with 1M context.",
    )
    append_signal(tmp_brain, sig)
    path = tmp_brain / "signals" / "2026-04.md"
    assert path.is_file()
    text = path.read_text()
    assert "Claude 4.7 ships with 1M context." in text
    assert "Anthropic" in text
    assert "2026-04-19" in text


def test_bump_mention_count_increments_entity_counter(tmp_brain: Path):
    upsert(tmp_brain, EntityDoc(
        canonical_name="Anthropic", entity_type="company",
        aliases=[], description=None, related=[], signal_mentions=0,
        summary_external=None, body="",
    ))
    bump_mention_count(tmp_brain, canonical_name="Anthropic")
    bump_mention_count(tmp_brain, canonical_name="Anthropic")
    loaded = load(tmp_brain, slug="anthropic")
    assert loaded is not None and loaded.signal_mentions == 2

    # JSON counter also tracks the mentions alongside the entity frontmatter.
    data = json.loads((tmp_brain / "index" / "signal_mentions.json").read_text())
    assert data["mentions"]["Anthropic"]["count"] == 2


def test_bump_mention_count_does_not_create_entity_when_missing(tmp_brain: Path):
    bump_mention_count(tmp_brain, canonical_name="Mixpanel")
    # No entity page must be spawned — news/signal ingests never create stubs.
    assert (tmp_brain / "entities" / "mixpanel.md").exists() is False
    # The JSON counter records the mention.
    data = json.loads((tmp_brain / "index" / "signal_mentions.json").read_text())
    assert data["mentions"]["Mixpanel"]["count"] == 1


def test_bump_mention_count_captures_takeaway_and_date(tmp_brain: Path):
    bump_mention_count(
        tmp_brain,
        canonical_name="Mixpanel",
        takeaway="Launched a new pricing tier.",
        date="2026-04-19",
    )
    data = json.loads((tmp_brain / "index" / "signal_mentions.json").read_text())
    entry = data["mentions"]["Mixpanel"]
    assert entry["count"] == 1
    assert entry["last_seen"] == "2026-04-19"
    assert entry["takeaways"] == ["Launched a new pricing tier."]

import uuid
from pathlib import Path

import pytest

from m3.brain.entity_doc import load
from m3.brain.items import read_meta
from m3.brain.questions import list_unresolved
from m3.brain.self_doc import read_section
from m3.core.ingest import Ingester, IngestInput


@pytest.fixture
def ingester(tmp_brain: Path, fake_llm):
    # Use a dummy embedder — it just returns a constant vector for tests.
    class _Embedder:
        dim = 768
        async def embed(self, texts):
            return [[0.0] * 768 for _ in texts]
    return Ingester(brain_root=tmp_brain, llm=fake_llm, embedder=_Embedder())


@pytest.mark.asyncio
async def test_personal_item_patches_self_and_entity(ingester, fake_llm):
    item_id = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    fake_llm.set_response("FluentCRM", {
        "kind": "personal",
        "interpretation": {"what_happened": "user expresses dislike of FluentCRM",
                           "when": {"iso": "2026-04-19", "source": "ingest_time"}, "confidence": 0.9},
        "open_questions": [],
        "hooks": {
            "who": [], "what": [{"name": "FluentCRM"}], "where": [],
            "when": "2026-04-19", "source": "cli", "project": ["Pacific"],
            "stance": [{"entity_name": "FluentCRM", "value": "negative", "evidence_quote": "wrong tool for us"}],
        },
        "self_updates": [{
            "slot": "Preferences", "operation": "append",
            "section_heading": None,
            "new_content": "### FluentCRM\nDisliked — wrong tool for our workflow.",
            "change_summary": "stance: negative", "cites": [str(item_id)],
        }],
        "entity_updates": [{
            "canonical_name": "FluentCRM", "entity_type": "tool",
            "merge_aliases": [], "related_entity_names": ["Pacific"],
            "section_update": {"operation": "append", "section_heading": None,
                               "new_content": "## Your history\n\n- 2026-04-19: dislikes, wrong tool. [^{}]".format(item_id),
                               "change_summary": "first mention"},
        }],
    })
    out = await ingester.ingest(IngestInput(
        item_id=item_id, source="cli", original_bytes=None, original_filename=None,
        content_type="text", text="I dislike FluentCRM. Wrong tool for us.",
    ))
    assert out.kind == "personal"
    pref = read_section(ingester.brain_root, "Preferences")
    assert "FluentCRM" in pref and "Disliked" in pref
    ent = load(ingester.brain_root, slug="fluentcrm")
    assert ent is not None and "Your history" in ent.body
    meta = read_meta(ingester.brain_root, item_id)
    assert meta is not None and meta.kind == "personal"


@pytest.mark.asyncio
async def test_ambiguous_item_writes_open_question_and_skips_dependent_hook(ingester, fake_llm):
    item_id = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
    fake_llm.set_response("call w/ J", {
        "kind": "personal",
        "interpretation": {"what_happened": "Ambiguous reference to J",
                           "when": {"iso": "2026-04-19", "source": "ingest_time"}, "confidence": 0.4},
        "open_questions": [{"question": "Who is J?", "context_snippet": "call w/ J at 3pm", "blocks": ["hook:who:J"]}],
        "hooks": {"who": [], "what": [], "where": [], "when": "2026-04-19", "source": "cli", "project": [], "stance": []},
        "self_updates": [], "entity_updates": [],
    })
    await ingester.ingest(IngestInput(
        item_id=item_id, source="cli", original_bytes=None, original_filename=None,
        content_type="text", text="call w/ J at 3pm",
    ))
    unresolved = list_unresolved(ingester.brain_root)
    assert any("Who is J?" in u for u in unresolved)


@pytest.mark.asyncio
async def test_record_item_writes_records_json_not_narrative(ingester, fake_llm, tmp_brain: Path):
    item_id = uuid.UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
    fake_llm.set_response("Uber", {
        "kind": "record",
        "interpretation": {"what_happened": "Uber receipt 2026-04-15",
                           "when": {"iso": "2026-04-15", "source": "explicit_in_content"}, "confidence": 0.95},
        "open_questions": [], "hooks": {}, "self_updates": [], "entity_updates": [],
        "structured_fields": {"amount": 42.5, "currency": "USD", "vendor": "Uber",
                              "date": "2026-04-15", "category": "transportation",
                              "due_date": None, "reference_id": None},
    })
    await ingester.ingest(IngestInput(
        item_id=item_id, source="share_sheet", original_bytes=b"PDF-bytes",
        original_filename="uber.pdf", content_type="pdf", text="Uber $42.50 2026-04-15",
    ))
    path = tmp_brain / "records" / "2026-04-15-uber.json"
    assert path.is_file()
    # No entity page spawned for a record
    assert not (tmp_brain / "entities" / "uber.md").exists()


@pytest.mark.asyncio
async def test_ingest_commits_to_git(ingester, fake_llm, tmp_brain: Path):
    import subprocess
    # init_brain now writes a baseline commit; an extra --allow-empty commit
    # keeps this test's "look for a message that starts with ingest <id>" assertion
    # robust even if skeleton-init gets its own commit message later.
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "baseline"], cwd=tmp_brain, check=True)
    item_id = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    fake_llm.set_response("burnout", {
        "kind": "personal",
        "interpretation": {"what_happened": "user mentions burnout",
                           "when": {"iso": "2026-04-19", "source": "ingest_time"}, "confidence": 0.8},
        "open_questions": [], "hooks": {}, "self_updates": [{
            "slot": "Context", "operation": "append", "section_heading": None,
            "new_content": "- Feeling burnt out recently.", "change_summary": "burnout note", "cites": [str(item_id)],
        }], "entity_updates": [],
    })
    await ingester.ingest(IngestInput(
        item_id=item_id, source="cli", original_bytes=None, original_filename=None,
        content_type="text", text="I'm burnout.",
    ))
    msg = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"], cwd=tmp_brain, check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert msg.startswith(f"ingest {item_id}:")


@pytest.mark.asyncio
async def test_ingest_rolls_back_on_failure(ingester, fake_llm, tmp_brain: Path):
    """A malformed LLM payload must not leave half-written files in the brain."""
    import subprocess

    item_id = uuid.UUID("aaaaaaaa-cccc-bbbb-dddd-eeeeeeeeeeee")
    # `kind="weirdo"` is not a valid Kind; Pydantic validation should raise.
    fake_llm.set_response("rollback test", {
        "kind": "weirdo",
        "interpretation": {
            "what_happened": "", "when": {"iso": None, "source": "unknown"}, "confidence": 0.0,
        },
        "open_questions": [], "hooks": {}, "self_updates": [], "entity_updates": [],
    })
    with pytest.raises(Exception):
        await ingester.ingest(IngestInput(
            item_id=item_id, source="cli",
            original_bytes=b"some bytes", original_filename="rollback test.txt",
            content_type="text", text="rollback test",
        ))

    # No new files should remain in items/meta or items/originals (.gitkeep is ok).
    meta_entries = [p.name for p in (tmp_brain / "items" / "meta").iterdir()]
    orig_entries = [p.name for p in (tmp_brain / "items" / "originals").iterdir()]
    assert meta_entries == [".gitkeep"] or meta_entries == []
    assert orig_entries == [".gitkeep"] or orig_entries == []

    # Working tree must be clean (nothing uncommitted, nothing untracked).
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_brain, check=True, capture_output=True, text=True,
    ).stdout
    assert status == "", f"expected clean tree, got: {status!r}"

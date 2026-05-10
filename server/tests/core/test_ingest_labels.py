"""Plan 2 Task 5: ingest must persist `title` (via extract_title) on ItemMeta
and `headline` (via ClaimOut.headline) on ClaimMeta. The cluster API will
prefer these fields when rendering canvas v2 labels."""

import uuid
from pathlib import Path

import pytest


class _Embedder:
    dim = 768

    async def embed(self, texts):
        return [[0.0] * 768 for _ in texts]


@pytest.mark.asyncio
async def test_ingest_writes_item_title_and_claim_headline(
    tmp_brain: Path, fake_llm,
):
    """One ingest produces an item with a parsed title (via extract_title)
    and at least one claim that carries the LLM-emitted headline."""
    from m3.brain.claims import iter_claims
    from m3.brain.items import iter_metas
    from m3.core.ingest import Ingester, IngestInput

    fake_llm.set_response("Pilot Path", {
        "kind": "personal",
        "interpretation": {
            "what_happened": "discussion about Pilot Path with Aditya",
            "when": {"iso": "2026-04-19", "source": "ingest_time"},
            "confidence": 0.9,
        },
        "open_questions": [],
        "hooks": {
            "who": [{"name": "Aditya"}], "what": [{"name": "Pilot Path"}],
            "where": [], "when": "2026-04-19", "source": "cli",
            "project": [], "stance": [],
        },
        "self_updates": [],
        "entity_updates": [{
            "canonical_name": "Pilot Path",
            "entity_type": "project",
            "merge_aliases": [],
            "related_entity_names": [],
            "section_update": {
                "operation": "append",
                "section_heading": None,
                "new_content": "## History\n\n- 2026-04-19: Aditya leaning in.",
                "change_summary": "first mention",
            },
        }],
        "claims": [
            {"proposition": "Aditya is leaning into the Pilot Path partnership.",
             "confidence": 0.85, "supporting_span": "leaning into the partnership",
             "entity_names": ["Pilot Path"],
             "headline": "Pilot Path partnership"},
        ],
    })

    # Body with markdown H1 so extract_title finds "Manoj's notes".
    text = (
        "# Manoj's notes\n\nCalled Aditya about Pilot Path. "
        "Aditya is leaning into the partnership."
    )

    item_id = uuid.UUID("cccc1111-2222-3333-4444-555566667777")
    ingester = Ingester(brain_root=tmp_brain, llm=fake_llm, embedder=_Embedder())
    await ingester.ingest(IngestInput(
        item_id=item_id, source="cli", original_bytes=None, original_filename=None,
        content_type="text", text=text,
    ))

    items = list(iter_metas(tmp_brain))
    titled = [m for m in items if m.title]
    assert titled, f"no item got a title (titles: {[m.title for m in items]})"

    claims = list(iter_claims(tmp_brain))
    with_headline = [c for c in claims if c.headline]
    assert with_headline, f"no claim got a headline (headlines: {[c.headline for c in claims]})"

"""Topical signatures should be refreshed at each ingest write point.

After a single ingest pass that yields an item meta, at least one entity
update, and at least one claim, the TopicalIndex should contain a signature
keyed for each. The canvas v2 force layout reads this index to drive
topical attraction between nodes; if ingest doesn't populate it, the index
stays empty until someone runs `m3 reindex --topical`.
"""

import uuid
from pathlib import Path

import pytest

from m3.brain.topical import TopicalIndex
from m3.core.ingest import Ingester, IngestInput


@pytest.fixture
def ingester(tmp_brain: Path, fake_llm):
    class _Embedder:
        dim = 768
        async def embed(self, texts):
            return [[0.0] * 768 for _ in texts]
    return Ingester(brain_root=tmp_brain, llm=fake_llm, embedder=_Embedder())


@pytest.mark.asyncio
async def test_ingest_populates_topical_signatures(ingester, fake_llm, tmp_brain: Path):
    item_id = uuid.UUID("aaaa1111-2222-3333-4444-555566667777")
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
                "new_content": "## History\n\n- 2026-04-19: Aditya wants to delay.",
                "change_summary": "first mention",
            },
        }],
        "claims": [
            {"proposition": "Aditya wants to delay Pilot Path by two weeks.",
             "confidence": 0.85, "supporting_span": "delay by two weeks",
             "entity_names": ["Pilot Path"]},
        ],
    })

    await ingester.ingest(IngestInput(
        item_id=item_id, source="cli", original_bytes=None, original_filename=None,
        content_type="text",
        text="Had a call with Aditya about Pilot Path. He thinks we should delay.",
    ))

    idx = TopicalIndex.open(tmp_brain)
    try:
        keys = {nid for nid, _ in idx.iter_all()}
    finally:
        idx.close()

    item_keys = {k for k in keys if k.startswith("item:")}
    entity_keys = {k for k in keys if k.startswith("entity:")}
    claim_keys = {k for k in keys if k.startswith("claim:")}
    assert item_keys, f"no item signatures in {keys}"
    assert entity_keys, f"no entity signatures in {keys}"
    assert claim_keys, f"no claim signatures in {keys}"


@pytest.mark.asyncio
async def test_reingest_does_not_leak_orphan_claim_signatures(
    ingester, fake_llm, tmp_brain: Path,
):
    """Re-ingesting the same item must not accumulate ghost claim rows in the
    topical index. delete_claims_for_item wipes the markdown; the topical
    index must be cleaned in the same step."""
    item_id = uuid.UUID("bbbb1111-2222-3333-4444-555566667777")
    response = {
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
                "new_content": "## History\n\n- 2026-04-19: Aditya wants to delay.",
                "change_summary": "first mention",
            },
        }],
        "claims": [
            {"proposition": "Aditya wants to delay Pilot Path by two weeks.",
             "confidence": 0.85, "supporting_span": "delay by two weeks",
             "entity_names": ["Pilot Path"]},
        ],
    }
    fake_llm.set_response("Pilot Path", response)

    inp = IngestInput(
        item_id=item_id, source="cli", original_bytes=None, original_filename=None,
        content_type="text",
        text="Had a call with Aditya about Pilot Path. He thinks we should delay.",
    )

    await ingester.ingest(inp)

    idx = TopicalIndex.open(tmp_brain)
    try:
        first_pass_claim_keys = {
            nid for nid, _ in idx.iter_all() if nid.startswith("claim:")
        }
    finally:
        idx.close()
    assert first_pass_claim_keys, "first ingest should have produced claim signatures"

    # Re-set the response (FakeLLM may consume responses) and ingest again.
    fake_llm.set_response("Pilot Path", response)
    await ingester.ingest(inp)

    idx = TopicalIndex.open(tmp_brain)
    try:
        second_pass_claim_keys = {
            nid for nid, _ in idx.iter_all() if nid.startswith("claim:")
        }
    finally:
        idx.close()

    # The second pass writes one fresh claim and wipes the prior one. Both
    # passes should leave exactly the same number of claim rows; if the cleanup
    # is missing, second_pass would be 2x first_pass.
    assert len(second_pass_claim_keys) == len(first_pass_claim_keys), (
        f"orphan claim rows leaked: first={first_pass_claim_keys}, "
        f"second={second_pass_claim_keys}"
    )

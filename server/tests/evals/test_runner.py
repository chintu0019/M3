"""Tests for the eval runner. We don't hit a real LLM — we canned responses
per case to assert the scoring math is right."""

from __future__ import annotations

import pytest

from m3.evals.corpus import CORPUS, EvalCase, Expected
from m3.evals.runner import run_suite


class _CannedLLM:
    """Returns a pre-baked response for each case keyed by the case name."""

    supports_tools = True
    supports_vision = False
    supports_audio = False

    def __init__(self, responses: dict[str, dict]):
        self._responses = responses

    async def complete_tool(self, *, messages, tools, system, tool_choice, max_tokens, temperature):
        from m3.core.llm.base import ToolResult
        # Look up by substring of the user message (since the eval runner
        # sends `case.text` as the user content).
        text = messages[-1]["content"]
        for key, resp in self._responses.items():
            if key in text:
                return ToolResult(tool_name=tool_choice, input=resp)
        # Default: valid-but-empty extraction.
        return ToolResult(tool_name=tool_choice, input={
            "kind": "personal",
            "interpretation": {"what_happened": "x",
                               "when": {"iso": None, "source": "unknown"}, "confidence": 0.0},
            "open_questions": [], "hooks": {},
            "self_updates": [], "entity_updates": [],
        })


def _base_output(**over) -> dict:
    data = {
        "kind": "personal",
        "interpretation": {
            "what_happened": "x",
            "when": {"iso": "2026-04-23", "source": "ingest_time"},
            "confidence": 0.9,
        },
        "open_questions": [], "hooks": {},
        "self_updates": [], "entity_updates": [],
    }
    data.update(over)
    return data


@pytest.mark.asyncio
async def test_coffee_case_passes_when_output_correct():
    """Correct output: routed to People, Aditya entity, no Preferences."""
    llm = _CannedLLM({"coffee with Aditya": _base_output(
        self_updates=[{
            "slot": "People", "operation": "append", "section_heading": None,
            "new_content": "### Aditya\nCoffee today.",
            "change_summary": "logged coffee", "cites": [],
        }],
        entity_updates=[{
            "canonical_name": "Aditya", "entity_type": "person",
            "merge_aliases": [], "related_entity_names": [], "section_update": None,
        }],
    )})
    case = next(c for c in CORPUS if c.name == "coffee-with-person")
    suite = await run_suite(llm=llm, cases=[case])
    assert suite.cases[0].passed, suite.cases[0].failures


@pytest.mark.asyncio
async def test_coffee_case_fails_when_misrouted_to_preferences():
    """Output routes coffee meeting to Preferences → must fail the case."""
    llm = _CannedLLM({"coffee with Aditya": _base_output(
        self_updates=[{
            "slot": "Preferences", "operation": "append", "section_heading": None,
            "new_content": "### Coffee\n- with Aditya today",
            "change_summary": "", "cites": [],
        }],
    )})
    case = next(c for c in CORPUS if c.name == "coffee-with-person")
    suite = await run_suite(llm=llm, cases=[case])
    assert not suite.cases[0].passed
    failures = " ".join(suite.cases[0].failures)
    assert "People" in failures
    assert "Preferences" in failures


@pytest.mark.asyncio
async def test_subject_attribution_case_fails_on_hallucinated_entity():
    """kesavulu.com case: LLM wrongly creates an Aditya entity → must fail."""
    llm = _CannedLLM({"Bought kesavulu.com": _base_output(
        self_updates=[{
            "slot": "Projects", "operation": "append", "section_heading": None,
            "new_content": "portfolio",
            "change_summary": "", "cites": [],
        }],
        entity_updates=[{
            "canonical_name": "Aditya", "entity_type": "person",
            "merge_aliases": [], "related_entity_names": [], "section_update": None,
        }],
    )})
    case = next(c for c in CORPUS if c.name == "user-bought-own-domain")
    suite = await run_suite(llm=llm, cases=[case])
    assert not suite.cases[0].passed
    assert any("Aditya" in f for f in suite.cases[0].failures)


@pytest.mark.asyncio
async def test_ambiguous_case_requires_open_question():
    case = next(c for c in CORPUS if c.name == "ambiguous-name")
    # Without an open_question: fail
    llm_no_q = _CannedLLM({"Meeting with J": _base_output(
        entity_updates=[{
            "canonical_name": "J", "entity_type": "person",
            "merge_aliases": [], "related_entity_names": [], "section_update": None,
        }],
    )})
    suite = await run_suite(llm=llm_no_q, cases=[case])
    assert not suite.cases[0].passed

    # With an open_question and no hallucinated "J" entity: pass
    llm_ok = _CannedLLM({"Meeting with J": _base_output(
        open_questions=[{
            "question": "Who is J?", "context_snippet": "Meeting with J", "blocks": [],
        }],
    )})
    suite_ok = await run_suite(llm=llm_ok, cases=[case])
    assert suite_ok.cases[0].passed, suite_ok.cases[0].failures


@pytest.mark.asyncio
async def test_stance_case_checks_hook_population():
    """Stance must land in hooks.stance AND route to Beliefs."""
    case = next(c for c in CORPUS if c.name == "stance-with-reasoning")
    # Missing stance hook: fail
    llm_missing = _CannedLLM({"FluentCRM is the wrong tool": _base_output(
        self_updates=[{
            "slot": "Beliefs", "operation": "append", "section_heading": None,
            "new_content": "wrong tool", "change_summary": "", "cites": [],
        }],
        entity_updates=[{
            "canonical_name": "FluentCRM", "entity_type": "tool",
            "merge_aliases": [], "related_entity_names": [], "section_update": None,
        }],
    )})
    suite = await run_suite(llm=llm_missing, cases=[case])
    assert not suite.cases[0].passed
    assert any("stance" in f.lower() for f in suite.cases[0].failures)


@pytest.mark.asyncio
async def test_invalid_extraction_output_counts_as_failure():
    """When the LLM emits garbage, the case records a validation failure, not a crash."""
    class _GarbageLLM:
        supports_tools = True
        supports_vision = False
        supports_audio = False
        async def complete_tool(self, **kw):
            from m3.core.llm.base import ToolResult
            return ToolResult(tool_name="process_item", input={"kind": "personal"})  # missing required fields

    case = next(c for c in CORPUS if c.name == "coffee-with-person")
    suite = await run_suite(llm=_GarbageLLM(), cases=[case])
    assert not suite.cases[0].passed
    assert any("did not validate" in f for f in suite.cases[0].failures)


@pytest.mark.asyncio
async def test_suite_aggregates_pass_rate():
    """pass_rate = passed / total; mean_score averages per-case scores."""
    llm = _CannedLLM({})  # all cases fall through to the empty default
    cases = [c for c in CORPUS if c.name in ("coffee-with-person", "taste-preference")]
    suite = await run_suite(llm=llm, cases=cases)
    # Both fail because the empty default doesn't match either case's expectations
    assert suite.pass_rate == 0.0
    assert suite.mean_score < 1.0

"""Run the eval corpus against the configured LLM and score the output."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from m3.core.extract import (
    ExtractionOutput,
    build_system_prompt,
    process_item_tool_schema,
)
from m3.core.llm import LLMProvider, Tool
from m3.evals.corpus import CORPUS, EvalCase, Expected


@dataclass
class CaseResult:
    name: str
    passed: bool
    score: float                          # 0.0 to 1.0
    checks_total: int
    checks_passed: int
    failures: list[str] = field(default_factory=list)
    raw_output: dict | None = None
    elapsed_secs: float = 0.0


@dataclass
class SuiteResult:
    cases: list[CaseResult]

    @property
    def pass_rate(self) -> float:
        if not self.cases:
            return 0.0
        return sum(1 for c in self.cases if c.passed) / len(self.cases)

    @property
    def mean_score(self) -> float:
        if not self.cases:
            return 0.0
        return sum(c.score for c in self.cases) / len(self.cases)


async def run_suite(
    *,
    llm: LLMProvider,
    today_iso: str = "2026-04-23",
    cases: list[EvalCase] | None = None,
) -> SuiteResult:
    cases = cases or CORPUS
    tool = Tool(
        name="process_item",
        description="Emit M3's structured extraction for this item.",
        input_schema=process_item_tool_schema(),
    )
    results: list[CaseResult] = []
    for case in cases:
        started = time.monotonic()
        system = build_system_prompt(
            today_iso=today_iso,
            self_doc="(empty)",
            candidate_entities_block="(no candidate entities yet)",
        )
        try:
            result = await llm.complete_tool(
                messages=[{"role": "user", "content": case.text}],
                tools=[tool], system=system, tool_choice="process_item",
                max_tokens=8192, temperature=0.2,
            )
            try:
                parsed = ExtractionOutput.model_validate(result.input or {})
            except Exception as validate_err:
                # Surface validation failures as a single failure for this case
                case_result = CaseResult(
                    name=case.name, passed=False, score=0.0,
                    checks_total=1, checks_passed=0,
                    failures=[f"extraction did not validate: {validate_err}"],
                    raw_output=result.input,
                    elapsed_secs=time.monotonic() - started,
                )
                results.append(case_result)
                continue
        except Exception as e:
            case_result = CaseResult(
                name=case.name, passed=False, score=0.0,
                checks_total=1, checks_passed=0,
                failures=[f"llm call failed: {e}"],
                elapsed_secs=time.monotonic() - started,
            )
            results.append(case_result)
            continue

        case_result = _score(case, parsed, elapsed=time.monotonic() - started)
        results.append(case_result)

    return SuiteResult(cases=results)


def _score(case: EvalCase, parsed: ExtractionOutput, *, elapsed: float) -> CaseResult:
    checks: list[tuple[str, bool]] = []
    exp = case.expected

    if exp.kind is not None:
        checks.append((f"kind == {exp.kind!r} (got {parsed.kind!r})", parsed.kind == exp.kind))

    slot_names = {u.slot for u in parsed.self_updates}
    for must in exp.slots_must_contain:
        checks.append((f"slots must contain {must!r} (got {sorted(slot_names)})", must in slot_names))
    for must_not in exp.slots_must_not_contain:
        checks.append((
            f"slots must NOT contain {must_not!r} (got {sorted(slot_names)})",
            must_not not in slot_names,
        ))

    entity_names = {u.canonical_name for u in parsed.entity_updates}
    # Case-insensitive match; real LLMs capitalize inconsistently.
    entity_names_ci = {n.lower() for n in entity_names}
    for must in exp.entities_must_contain:
        checks.append((
            f"entities must contain {must!r} (got {sorted(entity_names)})",
            must.lower() in entity_names_ci,
        ))
    for must_not in exp.entities_must_not_contain:
        checks.append((
            f"entities must NOT contain {must_not!r} (got {sorted(entity_names)})",
            must_not.lower() not in entity_names_ci,
        ))

    if exp.stance_must_contain:
        stances = {(s.entity_name.lower(), s.value) for s in parsed.hooks.stance}
        for ent, val in exp.stance_must_contain:
            checks.append((
                f"stance must contain ({ent!r}, {val!r}) (got {sorted(stances)})",
                (ent.lower(), val) in stances,
            ))

    if exp.open_question_expected is True:
        checks.append(("open_question was raised", len(parsed.open_questions) >= 1))
    elif exp.open_question_expected is False:
        checks.append(("no open_question", len(parsed.open_questions) == 0))

    if exp.confidence_at_least is not None:
        checks.append((
            f"confidence >= {exp.confidence_at_least} (got {parsed.interpretation.confidence:.2f})",
            parsed.interpretation.confidence >= exp.confidence_at_least,
        ))

    if exp.structured_fields_expected is True:
        checks.append(("structured_fields populated", parsed.structured_fields is not None))
    elif exp.structured_fields_expected is False:
        checks.append(("structured_fields empty", parsed.structured_fields is None))

    if exp.signal_expected is True:
        checks.append(("signal populated", parsed.signal is not None))
    elif exp.signal_expected is False:
        checks.append(("signal empty", parsed.signal is None))

    total = len(checks)
    passed = sum(1 for _, ok in checks if ok)
    failures = [desc for desc, ok in checks if not ok]
    score = passed / total if total else 0.0
    return CaseResult(
        name=case.name, passed=(passed == total), score=score,
        checks_total=total, checks_passed=passed, failures=failures,
        raw_output=parsed.model_dump(), elapsed_secs=elapsed,
    )


# --- CLI reporting ---


def format_report(suite: SuiteResult, *, verbose: bool = False) -> str:
    lines: list[str] = []
    lines.append("")
    lines.append(f"M3 extraction eval  —  {len(suite.cases)} cases")
    lines.append("=" * 60)
    for c in suite.cases:
        status = "✓" if c.passed else "✗"
        lines.append(
            f"  {status}  {c.name:<32} {c.checks_passed:>2}/{c.checks_total:<2}  "
            f"({c.score*100:5.1f}%)   {c.elapsed_secs:>5.1f}s"
        )
        if not c.passed:
            for f in c.failures:
                lines.append(f"       · {f}")
        if verbose and c.raw_output:
            lines.append(f"       kind={c.raw_output.get('kind')}, "
                         f"slots={sorted(u.get('slot') for u in c.raw_output.get('self_updates') or [])}, "
                         f"entities={sorted(u.get('canonical_name') for u in c.raw_output.get('entity_updates') or [])}")
    lines.append("=" * 60)
    lines.append(f"  pass rate: {suite.pass_rate*100:5.1f}%   mean score: {suite.mean_score*100:5.1f}%")
    lines.append("")
    return "\n".join(lines)


def export_json(suite: SuiteResult, path: Path) -> None:
    payload = {
        "pass_rate": suite.pass_rate,
        "mean_score": suite.mean_score,
        "cases": [
            {
                "name": c.name, "passed": c.passed, "score": c.score,
                "checks_total": c.checks_total, "checks_passed": c.checks_passed,
                "failures": c.failures, "elapsed_secs": c.elapsed_secs,
                "raw_output": c.raw_output,
            }
            for c in suite.cases
        ],
    }
    path.write_text(json.dumps(payload, indent=2, default=str))

"""Pinned corpus of real-ish notes with expected extraction behavior.

Each case exercises a specific capability or guards against a specific
failure mode we've seen in production. Keep the corpus small and
high-signal — every case should have a clear story.

Adding a case: write the `text`, fill in the `expected` fields that
actually matter for THAT case (the scorer only checks fields you set),
and add a one-line `why` explaining what this case catches.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Expected:
    kind: str | None = None
    # Slots that MUST appear in self_updates.
    slots_must_contain: list[str] = field(default_factory=list)
    # Slots that MUST NOT appear in self_updates (the misrouting guard).
    slots_must_not_contain: list[str] = field(default_factory=list)
    # Entity canonical_names that MUST be created/referenced.
    entities_must_contain: list[str] = field(default_factory=list)
    # Entity canonical_names that MUST NOT be created (hallucination guard).
    entities_must_not_contain: list[str] = field(default_factory=list)
    # Stance entity names we expect to see (each tuple: (entity, value)).
    stance_must_contain: list[tuple[str, str]] = field(default_factory=list)
    # Did we expect an open_question to be raised?
    open_question_expected: bool | None = None
    # Confidence bounds. Lower bound only — we care that it's high enough,
    # not that it's not too high.
    confidence_at_least: float | None = None
    # Did we expect a record (structured_fields populated)?
    structured_fields_expected: bool | None = None
    # Did we expect a signal (signal block populated)?
    signal_expected: bool | None = None


@dataclass
class EvalCase:
    name: str
    text: str
    why: str
    expected: Expected


CORPUS: list[EvalCase] = [

    # --- subject attribution ---

    EvalCase(
        name="user-bought-own-domain",
        text=(
            "Bought kesavulu.com from Namecheap to build my portfolio. "
            "Working on it this weekend."
        ),
        why="User's own purchase for own project must not be attributed to a named third party. Observed failure 2026-04-22.",
        expected=Expected(
            kind="personal",
            slots_must_contain=["Projects"],
            slots_must_not_contain=["People", "Preferences"],
            entities_must_contain=[],  # at least a project-type entity
            entities_must_not_contain=["Aditya", "Sarah"],  # names that have been in prior context
        ),
    ),

    # --- slot routing ---

    EvalCase(
        name="coffee-with-person",
        text=(
            "Had coffee with Aditya today. He's leaning into the Pilot Path "
            "partnership conversation. Will loop back next week."
        ),
        why="Meeting with a person goes to People, NOT Preferences. Observed failure 2026-04-22.",
        expected=Expected(
            kind="personal",
            slots_must_contain=["People"],
            slots_must_not_contain=["Preferences"],
            entities_must_contain=["Aditya"],
        ),
    ),

    EvalCase(
        name="stance-with-reasoning",
        text=(
            "FluentCRM is the wrong tool for our workflow. We've been burned "
            "by its limitations before. Pushing back in the next Pacific sync."
        ),
        why="Reasoned stance goes to Beliefs. Also tests stance hook population.",
        expected=Expected(
            kind="personal",
            slots_must_contain=["Beliefs"],
            entities_must_contain=["FluentCRM"],
            stance_must_contain=[("FluentCRM", "negative")],
        ),
    ),

    EvalCase(
        name="taste-preference",
        text="I prefer Linear to Jira. Lighter-weight, faster.",
        why="Tool taste goes to Preferences (the one case that actually is Preferences).",
        expected=Expected(
            kind="personal",
            slots_must_contain=["Preferences"],
            entities_must_contain=["Linear"],
        ),
    ),

    # --- item kinds ---

    EvalCase(
        name="receipt-kind",
        text=(
            "Uber receipt, 2026-04-15: $42.50 USD, trip from home to office. "
            "Transaction INV-00123."
        ),
        why="Structured record must be classified as record kind with structured_fields populated.",
        expected=Expected(
            kind="record",
            structured_fields_expected=True,
            # Records should not spawn a narrative wiki page.
            entities_must_not_contain=["Uber ride 2026-04-15", "trip receipt"],
        ),
    ),

    EvalCase(
        name="news-signal",
        text="Anthropic ships Claude 4.7 Sonnet today. 1M context on Opus.",
        why="News item classified as signal, not as entity-worthy content.",
        expected=Expected(
            kind="signal",
            signal_expected=True,
            slots_must_not_contain=["Projects", "Goals", "Beliefs"],
        ),
    ),

    EvalCase(
        name="reference-article",
        text=(
            "https://example.com/attention-is-all-you-need — great refresher "
            "on transformer internals, bookmarked for the Pacific project kickoff."
        ),
        why="Article bookmark is reference kind; should produce an entity with summary_external context.",
        expected=Expected(
            kind="reference",
            slots_must_not_contain=["Beliefs"],
        ),
    ),

    # --- hardening rules ---

    EvalCase(
        name="ambiguous-name",
        text="Meeting with J tomorrow at 3pm to discuss the Q2 roadmap.",
        why="Ambiguous referent must raise an open question rather than fabricate an entity.",
        expected=Expected(
            kind="personal",
            open_question_expected=True,
            entities_must_not_contain=["J"],
            confidence_at_least=0.0,  # confidence should be LOW; we only assert it's not null
        ),
    ),

    EvalCase(
        name="multiple-people-single-user",
        text=(
            "Standup with Sarah, Jamal, and Priya. Sarah flagged a blocker on "
            "the Pacific API; Jamal owns it."
        ),
        why="Multiple people mentioned — all three should land in People; user's own actions not attributed to them.",
        expected=Expected(
            kind="personal",
            slots_must_contain=["People"],
            entities_must_contain=["Sarah", "Jamal", "Priya"],
        ),
    ),

    EvalCase(
        name="project-with-person",
        text=(
            "Aditya and I talked about launching Pilot Path in Q3. He'll handle "
            "the customer list; I'll cover the engineering side."
        ),
        why="Project mentioned alongside a person. Both People AND Projects should update.",
        expected=Expected(
            kind="personal",
            slots_must_contain=["People", "Projects"],
            entities_must_contain=["Aditya", "Pilot Path"],
        ),
    ),
]

from __future__ import annotations

from datetime import date

from m3.core.temporal import parse


# A pinned "today" so all phrase math is deterministic.
# 2026-04-22 is a Wednesday (weekday()==2).
TODAY = date(2026, 4, 22)


def test_today():
    r = parse("meeting today with Sarah", today=TODAY)
    assert r.query == "meeting with Sarah"
    assert r.since_iso == "2026-04-22"
    assert r.until_iso == "2026-04-22"


def test_yesterday():
    r = parse("Sarah yesterday", today=TODAY)
    assert r.query == "Sarah"
    assert r.since_iso == "2026-04-21"
    assert r.until_iso == "2026-04-21"


def test_this_week():
    # Monday of week containing 2026-04-22 (Wed) is 2026-04-20.
    r = parse("stuff this week", today=TODAY)
    assert r.query == "stuff"
    assert r.since_iso == "2026-04-20"
    assert r.until_iso == "2026-04-26"


def test_last_week():
    # Last week: Mon 2026-04-13 → Sun 2026-04-19.
    r = parse("Sarah last week", today=TODAY)
    assert r.query == "Sarah"
    assert r.since_iso == "2026-04-13"
    assert r.until_iso == "2026-04-19"


def test_this_month():
    r = parse("notes this month", today=TODAY)
    assert r.query == "notes"
    assert r.since_iso == "2026-04-01"
    assert r.until_iso == "2026-04-30"


def test_last_month():
    r = parse("notes last month", today=TODAY)
    assert r.query == "notes"
    assert r.since_iso == "2026-03-01"
    assert r.until_iso == "2026-03-31"


def test_this_year():
    r = parse("plans this year", today=TODAY)
    assert r.query == "plans"
    assert r.since_iso == "2026-01-01"
    assert r.until_iso == "2026-12-31"


def test_last_year():
    r = parse("Aditya last year", today=TODAY)
    assert r.query == "Aditya"
    assert r.since_iso == "2025-01-01"
    assert r.until_iso == "2025-12-31"


def test_n_days_ago():
    r = parse("Sarah 3 days ago", today=TODAY)
    assert r.query == "Sarah"
    assert r.since_iso == "2026-04-19"
    assert r.until_iso == "2026-04-19"


def test_n_weeks_ago():
    r = parse("meeting 2 weeks ago", today=TODAY)
    assert r.query == "meeting"
    assert r.since_iso == "2026-04-08"
    assert r.until_iso == "2026-04-08"


def test_past_n_days():
    r = parse("Sarah past 7 days", today=TODAY)
    assert r.query == "Sarah"
    assert r.since_iso == "2026-04-15"
    assert r.until_iso == "2026-04-22"


def test_past_n_months():
    r = parse("projects past 3 months", today=TODAY)
    assert r.query == "projects"
    # 90 days back from 2026-04-22 is 2026-01-22.
    assert r.since_iso == "2026-01-22"
    assert r.until_iso == "2026-04-22"


def test_no_match_leaves_query_alone():
    r = parse("random coffee ideas", today=TODAY)
    assert r.query == "random coffee ideas"
    assert r.since_iso is None
    assert r.until_iso is None


def test_case_insensitive():
    r = parse("Sarah LAST WEEK", today=TODAY)
    assert r.query == "Sarah"
    assert r.since_iso == "2026-04-13"


def test_phrase_in_middle():
    r = parse("Sarah yesterday at noon", today=TODAY)
    # Strip + collapse => "Sarah at noon".
    assert r.query == "Sarah at noon"
    assert r.since_iso == "2026-04-21"

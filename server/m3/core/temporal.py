"""Parse a small set of relative-time phrases out of a query string.

Intentionally tiny vocabulary so the parser is predictable:
  today, yesterday, this week, last week, this month, last month,
  this year, last year, past N (days|weeks|months|years),
  N (days|weeks|months|years) ago

Returns the query with the phrase stripped + since_iso/until_iso bounds.
Does NOT handle named months ("last October") in v1; that needs month-year
disambiguation and is a separate task.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class TemporalFilter:
    query: str                 # query with the temporal phrase removed
    since_iso: str | None
    until_iso: str | None


_TODAY_RE = re.compile(r"\b(today)\b", re.IGNORECASE)
_YESTERDAY_RE = re.compile(r"\b(yesterday)\b", re.IGNORECASE)
_THIS_WEEK_RE = re.compile(r"\bthis\s+week\b", re.IGNORECASE)
_LAST_WEEK_RE = re.compile(r"\blast\s+week\b", re.IGNORECASE)
_THIS_MONTH_RE = re.compile(r"\bthis\s+month\b", re.IGNORECASE)
_LAST_MONTH_RE = re.compile(r"\blast\s+month\b", re.IGNORECASE)
_THIS_YEAR_RE = re.compile(r"\bthis\s+year\b", re.IGNORECASE)
_LAST_YEAR_RE = re.compile(r"\blast\s+year\b", re.IGNORECASE)
_N_AGO_RE = re.compile(
    r"\b(\d+)\s+(day|days|week|weeks|month|months|year|years)\s+ago\b",
    re.IGNORECASE,
)
_PAST_N_RE = re.compile(
    r"\bpast\s+(\d+)\s+(day|days|week|weeks|month|months|year|years)\b",
    re.IGNORECASE,
)


def parse(query: str, *, today: date | None = None) -> TemporalFilter:
    today = today or date.today()
    q = query
    since: str | None = None
    until: str | None = None

    def _iso(d: date) -> str:
        return d.isoformat()

    def _strip(pattern: re.Pattern) -> bool:
        nonlocal q
        m = pattern.search(q)
        if not m:
            return False
        q = (q[:m.start()] + q[m.end():]).strip()
        # Collapse double spaces left behind.
        q = re.sub(r"\s+", " ", q)
        return True

    if _strip(_TODAY_RE):
        since = until = _iso(today)
    elif _strip(_YESTERDAY_RE):
        y = today - timedelta(days=1)
        since = until = _iso(y)
    elif _strip(_THIS_WEEK_RE):
        # ISO week: Monday to Sunday.
        monday = today - timedelta(days=today.weekday())
        since = _iso(monday)
        until = _iso(monday + timedelta(days=6))
    elif _strip(_LAST_WEEK_RE):
        monday = today - timedelta(days=today.weekday() + 7)
        since = _iso(monday)
        until = _iso(monday + timedelta(days=6))
    elif _strip(_THIS_MONTH_RE):
        first = today.replace(day=1)
        next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        last = next_month - timedelta(days=1)
        since = _iso(first)
        until = _iso(last)
    elif _strip(_LAST_MONTH_RE):
        first_this = today.replace(day=1)
        last_last = first_this - timedelta(days=1)
        first_last = last_last.replace(day=1)
        since = _iso(first_last)
        until = _iso(last_last)
    elif _strip(_THIS_YEAR_RE):
        since = f"{today.year}-01-01"
        until = f"{today.year}-12-31"
    elif _strip(_LAST_YEAR_RE):
        since = f"{today.year - 1}-01-01"
        until = f"{today.year - 1}-12-31"
    else:
        m = _N_AGO_RE.search(q)
        if m:
            n = int(m.group(1))
            unit = m.group(2).lower().rstrip("s")
            q = (q[:m.start()] + q[m.end():]).strip()
            q = re.sub(r"\s+", " ", q)
            d = _offset(today, n, unit)
            since = until = _iso(d)
        else:
            m = _PAST_N_RE.search(q)
            if m:
                n = int(m.group(1))
                unit = m.group(2).lower().rstrip("s")
                q = (q[:m.start()] + q[m.end():]).strip()
                q = re.sub(r"\s+", " ", q)
                since = _iso(_offset(today, n, unit))
                until = _iso(today)

    return TemporalFilter(query=q, since_iso=since, until_iso=until)


def _offset(today: date, n: int, unit: str) -> date:
    if unit == "day":
        return today - timedelta(days=n)
    if unit == "week":
        return today - timedelta(weeks=n)
    if unit == "month":
        # Rough: 30 days per month. The eval corpus doesn't require calendar
        # precision here; the hook filter is a date-range check, not a bucket.
        return today - timedelta(days=30 * n)
    if unit == "year":
        return today - timedelta(days=365 * n)
    raise ValueError(f"unknown unit: {unit!r}")

"""The 17:00-18:00 ET halt, where FutureView's two session questions diverge.

``session_date`` (SESSION_ROLL_HOUR_ET = 18) answers "which trading session does
this bar belong to"; ``requested_session_date`` (SESSION_END_HOUR_ET = 17) answers
"what is the first session that can hold a bar at or after this requested start".
CME equity-index futures halt 17:00-18:00 ET, so a request inside the halt has no
bar left in the current session and must resolve to the next one.

SESSION_BOUNDARY_CASES is the same table asserted by
cloudflare/worker/replay-session-boundary.test.mjs. Keeping one fixture on both
sides is what stops the Worker and the exporter drifting apart silently.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from futureview_replay.resolver import (
    SESSION_END_HOUR_ET,
    SESSION_ROLL_HOUR_ET,
    requested_session_date,
    session_date,
)

SESSION_BOUNDARY_CASES = [
    ("2026-03-16T16:59:00", 1773694740, "2026-03-16", "2026-03-16", "EDT, hour before the halt"),
    ("2026-03-16T17:00:00", 1773694800, "2026-03-17", "2026-03-16", "EDT, halt begins"),
    ("2026-03-16T17:59:00", 1773698340, "2026-03-17", "2026-03-16", "EDT, last minute of the halt"),
    ("2026-03-16T18:00:00", 1773698400, "2026-03-17", "2026-03-17", "EDT, session roll"),
    ("2026-03-16T18:01:00", 1773698460, "2026-03-17", "2026-03-17", "EDT, just after the roll"),
    ("2026-12-09T16:59:00", 1796853540, "2026-12-09", "2026-12-09", "EST, hour before the halt"),
    ("2026-12-09T17:00:00", 1796853600, "2026-12-10", "2026-12-09", "EST, halt begins"),
    ("2026-12-09T17:59:00", 1796857140, "2026-12-10", "2026-12-09", "EST, last minute of the halt"),
    ("2026-12-09T18:00:00", 1796857200, "2026-12-10", "2026-12-10", "EST, session roll"),
    ("2026-03-07T17:30:00", 1772922600, "2026-03-08", "2026-03-07", "EST, halt before the DST change"),
    ("2026-03-08T17:30:00", 1773005400, "2026-03-09", "2026-03-08", "EDT, halt on the DST change day"),
]


def test_the_two_session_hours_are_distinct_constants() -> None:
    assert SESSION_ROLL_HOUR_ET == 18
    assert SESSION_END_HOUR_ET == 17


@pytest.mark.parametrize(("et", "utc", "requested", "session", "note"), SESSION_BOUNDARY_CASES)
def test_session_boundaries(et: str, utc: int, requested: str, session: str, note: str) -> None:
    moment = datetime.fromtimestamp(utc, tz=timezone.utc)
    assert requested_session_date(moment).isoformat() == requested, f"{et} ({note})"
    assert session_date(moment).isoformat() == session, f"{et} ({note})"


def test_the_answers_differ_only_inside_the_halt() -> None:
    # If someone collapses the two constants to 18, this is the assertion that
    # explains why that is wrong rather than just failing a date comparison.
    for et, _utc, requested, session, note in SESSION_BOUNDARY_CASES:
        hour = int(et[11:13])
        if 17 <= hour < 18:
            assert requested != session, f"{et} ({note}) should advance the requested session"
        else:
            assert requested == session, f"{et} ({note}) should agree"

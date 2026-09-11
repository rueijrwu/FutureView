from __future__ import annotations

from datetime import date, datetime, timezone

from futureview_replay.resolver import build_selection_calendar, requested_session_date, resolve_from_calendar, session_date


def test_session_date_rolls_at_1800_et() -> None:
    assert session_date(datetime(2024, 6, 10, 21, 59, tzinfo=timezone.utc)) == date(2024, 6, 10)
    assert session_date(datetime(2024, 6, 10, 22, 0, tzinfo=timezone.utc)) == date(2024, 6, 11)
    assert requested_session_date(datetime(2024, 6, 10, 21, 0, tzinfo=timezone.utc)) == date(2024, 6, 11)


def test_calendar_uses_only_prior_session_and_never_rolls_backward() -> None:
    volumes = {
        date(2024, 6, 10): {"MESM24": 100, "MESU24": 10},
        date(2024, 6, 11): {"MESM24": 80, "MESU24": 120},
        date(2024, 6, 12): {"MESM24": 500, "MESU24": 100},
    }
    calendar = build_selection_calendar(volumes)
    assert [item["contract"] for item in calendar] == ["MESM24", "MESM24", "MESU24"]
    assert calendar[1]["source_session"] == "2024-06-10"
    assert calendar[2]["reason"] == "prior_session_volume_roll"


def test_resolve_weekend_uses_next_available_session() -> None:
    calendar = [
        {"session": "2024-06-14", "contract": "MESM24"},
        {"session": "2024-06-17", "contract": "MESU24"},
    ]
    selection = resolve_from_calendar(calendar, datetime(2024, 6, 15, 12, tzinfo=timezone.utc))
    assert selection["contract"] == "MESU24"

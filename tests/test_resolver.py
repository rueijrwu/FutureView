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


def test_calendar_rolls_across_decade_boundary_with_single_digit_years() -> None:
    volumes = {
        date(2019, 12, 10): {"ESZ9": 1000, "ESH0": 100},
        date(2019, 12, 11): {"ESZ9": 200, "ESH0": 1500},
        date(2020, 3, 10): {"ESH0": 1000, "ESM0": 100},
        date(2020, 3, 11): {"ESH0": 100, "ESM0": 2000},
        date(2020, 3, 12): {"ESH0": 50, "ESM0": 3000},
    }
    calendar = build_selection_calendar(volumes)
    contracts = [item["contract"] for item in calendar]
    assert contracts == ["ESZ9", "ESZ9", "ESH0", "ESH0", "ESM0"]


def test_third_friday_calculation() -> None:
    from futureview_replay.resolver import third_friday

    assert third_friday(2024, 3) == date(2024, 3, 15)
    assert third_friday(2024, 6) == date(2024, 6, 21)
    assert third_friday(2024, 9) == date(2024, 9, 20)
    assert third_friday(2024, 12) == date(2024, 12, 20)


def test_roll_window_and_hard_expiry() -> None:
    # 2024-06-21 is the 3rd Friday of June 2024 (MESM24 expiry)
    # Roll window starts 14 days prior: 2024-06-07
    volumes = {
        date(2024, 6, 3): {"MESM24": 1000, "MESU24": 10},
        # 2024-06-04: Prior session MESU24 was small. Holds MESM24.
        # But today MESU24 has volume 200 vs MESM24 100.
        date(2024, 6, 4): {"MESM24": 100, "MESU24": 200},
        # 2024-06-05: Outside 14-day roll window (expiry is 2024-06-21, window starts 2024-06-07).
        # Even though prior session candidate volume (200) > incumbent (100), no roll!
        date(2024, 6, 5): {"MESM24": 100, "MESU24": 200},
        # 2024-06-07: Inside 14-day roll window. Prior session MESU24 > MESM24. Rolls to MESU24!
        date(2024, 6, 7): {"MESM24": 100, "MESU24": 200},
    }
    calendar = build_selection_calendar(volumes)
    assert [item["contract"] for item in calendar] == ["MESM24", "MESM24", "MESM24", "MESU24"]
    assert calendar[2]["reason"] == "prior_session_volume_hold"
    assert calendar[3]["reason"] == "prior_session_volume_roll"


def test_forced_roll_on_contract_expiry() -> None:
    # If a contract reaches 3rd Friday expiration without a prior volume crossover,
    # it must forcibly roll so replay never trades an expired contract.
    volumes = {
        date(2024, 6, 18): {"MESM24": 1000, "MESU24": 100},
        date(2024, 6, 19): {"MESM24": 1000, "MESU24": 100},
        date(2024, 6, 20): {"MESM24": 1000, "MESU24": 100},
        # 2024-06-21 is 3rd Friday (expiry). Even if MESM24 had higher prior volume, forcibly roll.
        date(2024, 6, 21): {"MESM24": 1000, "MESU24": 100},
    }
    calendar = build_selection_calendar(volumes)
    assert calendar[0]["contract"] == "MESM24"
    assert calendar[1]["contract"] == "MESM24"
    assert calendar[2]["contract"] == "MESM24"
    assert calendar[3]["contract"] == "MESU24"
    assert calendar[3]["reason"] == "contract_expired_roll"



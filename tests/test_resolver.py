from __future__ import annotations

from datetime import date, datetime, timezone

from futureview_replay.resolver import (
    contract_expiry_datetime,
    requested_session_date,
    resolve_contract_at_time,
    session_date,
    third_friday,
)


def test_session_date_rolls_at_1800_et() -> None:
    assert session_date(datetime(2024, 6, 10, 21, 59, tzinfo=timezone.utc)) == date(2024, 6, 10)
    assert session_date(datetime(2024, 6, 10, 22, 0, tzinfo=timezone.utc)) == date(2024, 6, 11)
    assert requested_session_date(datetime(2024, 6, 10, 21, 0, tzinfo=timezone.utc)) == date(2024, 6, 11)


def test_runtime_selection_uses_only_previous_completed_session() -> None:
    volumes = {
        date(2024, 6, 10): {"MESM24": 100, "MESU24": 10},
        date(2024, 6, 11): {"MESM24": 80, "MESU24": 120},
        date(2024, 6, 12): {"MESM24": 500, "MESU24": 100},
    }
    selection = resolve_contract_at_time(volumes, datetime(2024, 6, 12, 12, 30, tzinfo=timezone.utc))
    assert selection["session"] == "2024-06-12"
    assert selection["contract"] == "MESU24"
    assert selection["source_session"] == "2024-06-11"
    assert selection["reason"] == "prior_session_max_volume"
    assert selection["candidate_volumes"]["MESU24"] == 120.0


def test_weekend_request_resolves_next_actual_session() -> None:
    volumes = {
        date(2024, 6, 14): {"MESM24": 100, "MESU24": 200},
        date(2024, 6, 17): {"MESM24": 50, "MESU24": 300},
    }
    selection = resolve_contract_at_time(volumes, datetime(2024, 6, 15, 12, tzinfo=timezone.utc))
    assert selection["session"] == "2024-06-17"
    assert selection["source_session"] == "2024-06-14"
    assert selection["contract"] == "MESU24"


def test_third_friday_calculation() -> None:
    assert third_friday(2024, 3) == date(2024, 3, 15)
    assert third_friday(2024, 6) == date(2024, 6, 21)
    assert third_friday(2024, 9) == date(2024, 9, 20)
    assert third_friday(2024, 12) == date(2024, 12, 20)


def test_expiring_contract_is_valid_before_0930_et() -> None:
    volumes = {
        date(2024, 6, 20): {"MESM24": 1000, "MESU24": 100},
        date(2024, 6, 21): {"MESM24": 1000, "MESU24": 100},
    }
    # 08:30 ET = 12:30 UTC in June. The June contract is still eligible.
    selection = resolve_contract_at_time(volumes, datetime(2024, 6, 21, 12, 30, tzinfo=timezone.utc))
    assert selection["contract"] == "MESM24"
    assert selection["reason"] == "prior_session_max_volume"


def test_expiring_contract_is_excluded_at_0930_et() -> None:
    volumes = {
        date(2024, 6, 20): {"MESM24": 1000, "MESU24": 100},
        date(2024, 6, 21): {"MESM24": 1000, "MESU24": 100},
    }
    # 09:30 ET = 13:30 UTC in June. The June contract is no longer eligible.
    selection = resolve_contract_at_time(volumes, datetime(2024, 6, 21, 13, 30, tzinfo=timezone.utc))
    assert selection["contract"] == "MESU24"


def test_single_digit_contract_year_maps_across_decade() -> None:
    expiry = contract_expiry_datetime("ESH0", 2020)
    assert expiry.year == 2020
    assert expiry.month == 3

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

from futureview_replay.models import Bar

DISPLAY_TIME_ZONE = ZoneInfo("America/New_York")
SESSION_ROLL_HOUR_ET = 18
SESSION_END_HOUR_ET = 17
EXPIRY_HOUR_ET = 9
EXPIRY_MINUTE_ET = 30
MONTH_NUMBER = {code: month for month, code in enumerate("FGHJKMNQUVXZ", start=1)}
CONTRACT_RE = re.compile(r"^(.+?)([FGHJKMNQUVXZ])(\d{1,2})$")


def session_date(value: datetime) -> date:
    """Return the CME equity-index trading date for a timestamp."""
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    local = value.astimezone(DISPLAY_TIME_ZONE)
    result = local.date()
    if local.hour >= SESSION_ROLL_HOUR_ET:
        result += timedelta(days=1)
    return result


def requested_session_date(value: datetime) -> date:
    """Return the first trading session that can contain a bar at/after value."""
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    local = value.astimezone(DISPLAY_TIME_ZONE)
    result = local.date()
    if local.hour >= SESSION_END_HOUR_ET:
        result += timedelta(days=1)
    return result


def _contract_expiry(contract: str, reference_year: int) -> tuple[int, int]:
    match = CONTRACT_RE.fullmatch(contract)
    if not match:
        raise ValueError(f"Unsupported outright futures symbol {contract}")
    month = MONTH_NUMBER[match.group(2)]
    digits = match.group(3)
    if len(digits) == 2:
        year = 2000 + int(digits)
    else:
        digit = int(digits)
        candidates = [year for year in range(reference_year - 1, reference_year + 10) if year % 10 == digit]
        year = min(candidates, key=lambda value: abs(value - reference_year))
    return year, month


def third_friday(year: int, month: int) -> date:
    first_day = date(year, month, 1)
    first_friday = 1 + (4 - first_day.weekday()) % 7
    return date(year, month, first_friday + 14)


def contract_expiry_date(contract: str, reference_year: int) -> date:
    year, month = _contract_expiry(contract, reference_year)
    return third_friday(year, month)


def contract_expiry_datetime(contract: str, reference_year: int) -> datetime:
    expiry = contract_expiry_date(contract, reference_year)
    return datetime.combine(expiry, time(EXPIRY_HOUR_ET, EXPIRY_MINUTE_ET), tzinfo=DISPLAY_TIME_ZONE)


def session_volumes_from_bars(bars_by_contract: Mapping[str, Iterable[Bar]]) -> dict[date, dict[str, float]]:
    result: dict[date, dict[str, float]] = {}
    for contract, bars in bars_by_contract.items():
        for bar in bars:
            volumes = result.setdefault(session_date(bar.timestamp), {})
            volumes[contract] = volumes.get(contract, 0.0) + float(bar.volume)
    return result


def resolve_contract_at_time(
    session_volumes: Mapping[date, Mapping[str, float]],
    start: datetime,
    available_contracts: Iterable[str] | None = None,
) -> dict[str, object]:
    """Resolve the replay contract at request time using only completed-session data.

    The requested timestamp is the input and the contract is the result. For any normal
    session, selection uses the immediately preceding *available completed* session and
    chooses the highest-volume non-expired contract. The expiring quarterly contract
    remains eligible until 09:30 ET on its third-Friday expiration day. No future/same-
    session volume is consulted.
    """
    start = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start.astimezone(timezone.utc)
    sessions = sorted(session_volumes)
    if not sessions:
        raise ValueError("No replay sessions are available")

    target = requested_session_date(start)
    session_index = next((i for i, current in enumerate(sessions) if current >= target), None)
    if session_index is None:
        raise ValueError(f"No replay session at or after {start.isoformat()}")

    resolved_session = sessions[session_index]
    all_contracts = set(available_contracts or ())
    for volumes in session_volumes.values():
        all_contracts.update(volumes)
    if not all_contracts:
        raise ValueError("No replay contracts are available")

    local_start = start.astimezone(DISPLAY_TIME_ZONE)
    reference_year = resolved_session.year

    def eligible(contract: str) -> bool:
        try:
            return local_start < contract_expiry_datetime(contract, reference_year)
        except ValueError:
            return False

    source_session = sessions[session_index - 1] if session_index > 0 else None
    if source_session is not None:
        prior = session_volumes[source_session]
        candidates = [
            (contract, float(volume))
            for contract, volume in prior.items()
            if contract in all_contracts and eligible(contract) and float(volume) > 0.0
        ]
        if candidates:
            candidates.sort(
                key=lambda item: (
                    item[1],
                    -contract_expiry_datetime(item[0], reference_year).timestamp(),
                ),
                reverse=True,
            )
            contract, volume = candidates[0]
            return {
                "session": resolved_session.isoformat(),
                "contract": contract,
                "reason": "prior_session_max_volume",
                "source_session": source_session.isoformat(),
                "source_volume": volume,
                "candidate_volumes": {name: value for name, value in sorted(candidates, key=lambda x: x[1], reverse=True)},
                "expiry_cutoff_et": contract_expiry_datetime(contract, reference_year).isoformat(),
            }

    valid = [contract for contract in all_contracts if eligible(contract)]
    if not valid:
        raise ValueError(f"No non-expired replay contract at or after {start.isoformat()}")
    contract = min(valid, key=lambda value: contract_expiry_datetime(value, reference_year))
    return {
        "session": resolved_session.isoformat(),
        "contract": contract,
        "reason": "nearest_expiry_fallback",
        "source_session": source_session.isoformat() if source_session else None,
        "source_volume": None,
        "candidate_volumes": {},
        "expiry_cutoff_et": contract_expiry_datetime(contract, reference_year).isoformat(),
    }


def build_selection_calendar(session_volumes: Mapping[date, Mapping[str, float]]) -> list[dict[str, object]]:
    """Compatibility/diagnostic view only; runtime code must call resolve_contract_at_time."""
    sessions = sorted(session_volumes)
    if not sessions:
        return []
    result: list[dict[str, object]] = []
    for current in sessions:
        local = datetime.combine(current, time(8, 30), tzinfo=DISPLAY_TIME_ZONE)
        result.append(resolve_contract_at_time(session_volumes, local.astimezone(timezone.utc)))
    return result


def resolve_from_calendar(calendar: list[dict[str, object]], start: datetime) -> dict[str, object]:
    """Backward-compatible reader for old manifests. New manifests resolve at runtime."""
    target = requested_session_date(start).isoformat()
    for selection in calendar:
        if str(selection["session"]) >= target:
            return selection
    raise ValueError(f"No replay session at or after {start.isoformat()}")

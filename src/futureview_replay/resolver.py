from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

from futureview_replay.models import Bar

DISPLAY_TIME_ZONE = ZoneInfo("America/New_York")
SESSION_ROLL_HOUR_ET = 18
SESSION_END_HOUR_ET = 17
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


def build_selection_calendar(
    session_volumes: Mapping[date, Mapping[str, float]],
) -> list[dict[str, object]]:
    """Build a causal, monotonic quarterly-contract calendar.

    The first observed session uses the nearest listed expiry as a metadata-only
    fallback. Every later session uses only the immediately preceding completed
    session's volume and may hold the current contract or roll once to the next
    listed quarterly contract. It never rolls backward or skips a contract.
    """
    sessions = sorted(session_volumes)
    if not sessions:
        return []
    symbols = sorted(
        {symbol for volumes in session_volumes.values() for symbol in volumes},
        key=lambda symbol: _contract_expiry(symbol, sessions[0].year),
    )
    first_symbols = set(session_volumes[sessions[0]])
    active_index = next((index for index, symbol in enumerate(symbols) if symbol in first_symbols), 0)
    calendar: list[dict[str, object]] = []

    for index, current_session in enumerate(sessions):
        if index == 0:
            reason = "nearest_expiry_fallback"
            source_session = None
            incumbent_contract = None
            candidate_contract = symbols[active_index]
            incumbent_volume = None
            candidate_volume = None
        else:
            source = sessions[index - 1]
            prior = session_volumes[source]
            active = symbols[active_index]
            next_symbol = symbols[active_index + 1] if active_index + 1 < len(symbols) else None
            incumbent_contract = active
            candidate_contract = next_symbol
            incumbent_volume = float(prior.get(active, 0.0))
            candidate_volume = float(prior.get(next_symbol, 0.0)) if next_symbol else None
            if next_symbol is not None and float(candidate_volume) > incumbent_volume:
                active_index += 1
                reason = "prior_session_volume_roll"
            else:
                reason = "prior_session_volume_hold"
            source_session = source.isoformat()

        calendar.append(
            {
                "session": current_session.isoformat(),
                "contract": symbols[active_index],
                "reason": reason,
                "source_session": source_session,
                "incumbent_contract": incumbent_contract,
                "candidate_contract": candidate_contract,
                "incumbent_volume": incumbent_volume,
                "candidate_volume": candidate_volume,
            }
        )
    return calendar


def session_volumes_from_bars(bars_by_contract: Mapping[str, Iterable[Bar]]) -> dict[date, dict[str, float]]:
    result: dict[date, dict[str, float]] = {}
    for contract, bars in bars_by_contract.items():
        for bar in bars:
            volumes = result.setdefault(session_date(bar.timestamp), {})
            volumes[contract] = volumes.get(contract, 0.0) + float(bar.volume)
    return result


def resolve_from_calendar(calendar: list[dict[str, object]], start: datetime) -> dict[str, object]:
    target = requested_session_date(start).isoformat()
    for selection in calendar:
        if str(selection["session"]) >= target:
            return selection
    raise ValueError(f"No replay session at or after {start.isoformat()}")

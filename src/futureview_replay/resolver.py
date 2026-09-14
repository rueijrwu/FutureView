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


QUARTERLY_MONTHS = ["H", "M", "U", "Z"]


def next_quarterly_contract(contract: str) -> str:
    match = CONTRACT_RE.fullmatch(contract)
    if not match:
        raise ValueError(f"Unsupported outright futures symbol {contract}")
    prefix, month, digits = match.group(1), match.group(2), match.group(3)
    if month not in QUARTERLY_MONTHS:
        idx = "FGHJKMNQUVXZ".index(month)
        next_q = next((q for q in QUARTERLY_MONTHS if "FGHJKMNQUVXZ".index(q) > idx), None)
        if next_q:
            return f"{prefix}{next_q}{digits}"
        next_digits = str((int(digits) + 1) % 10) if len(digits) == 1 else f"{(int(digits) + 1) % 100:02d}"
        return f"{prefix}H{next_digits}"

    idx = QUARTERLY_MONTHS.index(month)
    if idx < 3:
        next_month = QUARTERLY_MONTHS[idx + 1]
        next_digits = digits
    else:
        next_month = "H"
        if len(digits) == 1:
            next_digits = str((int(digits) + 1) % 10)
        else:
            next_digits = f"{(int(digits) + 1) % 100:02d}"
    return f"{prefix}{next_month}{next_digits}"


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

    first_vols = session_volumes[sessions[0]]
    if first_vols:
        active_contract = max(
            first_vols.keys(),
            key=lambda k: (first_vols[k], -abs(_contract_expiry(k, sessions[0].year)[0] - sessions[0].year)),
        )
    else:
        all_symbols = {symbol for vols in session_volumes.values() for symbol in vols}
        active_contract = min(all_symbols, key=lambda s: _contract_expiry(s, sessions[0].year))

    calendar: list[dict[str, object]] = []

    for index, current_session in enumerate(sessions):
        if index == 0:
            reason = "nearest_expiry_fallback"
            source_session = None
            incumbent_contract = None
            candidate_contract = active_contract
            incumbent_volume = None
            candidate_volume = None
        else:
            source = sessions[index - 1]
            prior = session_volumes[source]
            candidate_contract = next_quarterly_contract(active_contract)
            incumbent_contract = active_contract
            incumbent_volume = float(prior.get(active_contract, 0.0))
            candidate_volume = float(prior.get(candidate_contract, 0.0))

            if candidate_volume > incumbent_volume:
                active_contract = candidate_contract
                reason = "prior_session_volume_roll"
            elif incumbent_volume == 0.0:
                rolled = False
                curr = candidate_contract
                for _ in range(3):
                    curr_vol = float(prior.get(curr, 0.0))
                    if curr_vol > 0.0:
                        candidate_contract = curr
                        candidate_volume = curr_vol
                        active_contract = curr
                        reason = "prior_session_volume_roll"
                        rolled = True
                        break
                    curr = next_quarterly_contract(curr)
                if not rolled:
                    reason = "prior_session_volume_hold"
            else:
                reason = "prior_session_volume_hold"
            source_session = source.isoformat()

        calendar.append(
            {
                "session": current_session.isoformat(),
                "contract": active_contract,
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

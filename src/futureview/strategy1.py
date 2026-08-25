from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

STRATEGY1_HORIZONS = (15, 30, 45, 60)
ENTRY_WEIGHTS = (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)
COOLDOWN_SESSIONS = 3


@dataclass(frozen=True)
class Strategy1Action:
    index: int
    action: str
    price: float
    fraction: float


@dataclass(frozen=True)
class Strategy1Run:
    final_return: float
    start_index: int | None
    entries_used: int
    campaigns_used: int
    partial_exit_used: bool
    full_exit_used: bool
    horizon_exit_used: bool
    partial_exit_count: int = 0
    full_exit_count: int = 0
    actions: tuple[Strategy1Action, ...] = ()


def add_strategy1_events(df: pd.DataFrame) -> pd.DataFrame:
    """Add causal Strategy 1 indicators and discrete candidate events."""
    out = df.copy()
    close = out["close"].astype(float)

    out["ma5"] = close.rolling(5, min_periods=5).mean()
    out["ma10"] = close.rolling(10, min_periods=10).mean()
    out["ma20"] = close.rolling(20, min_periods=20).mean()

    stack = (
        (close > out["ma5"])
        & (close > out["ma10"])
        & (close > out["ma20"])
        & (out["ma5"] > out["ma10"])
        & (out["ma10"] > out["ma20"])
    )
    out["entry1_event"] = stack & ~stack.shift(1, fill_value=False)

    prior20_high = close.shift(1).rolling(20, min_periods=20).max()
    above_prior20 = close > prior20_high
    out["breakout20_event"] = above_prior20 & ~above_prior20.shift(1, fill_value=False)

    below5 = close < out["ma5"]
    below10 = close < out["ma10"]
    out["exit5_event"] = below5 & ~below5.shift(1, fill_value=False)
    out["exit10_event"] = below10 & ~below10.shift(1, fill_value=False)

    return out


def _simulate_from_start(events: pd.DataFrame, start: int, end: int) -> Strategy1Run:
    """Simulate one fixed Strategy 1 campaign from a legal first-entry event.

    The campaign allows at most three total entries. After any entry/add-on, MA5
    and MA10 exits are blocked for the next three trading sessions. After an MA5
    partial exit, add-ons are blocked for the next three trading sessions. An
    MA10 full exit terminates the campaign; no second campaign may start in the
    same Oracle window. Horizon liquidation is mandatory and is exempt from the
    three-session spacing rule because it is the label boundary, not a strategy
    signal.
    """
    cash = 1.0
    shares = 0.0
    entries_used = 0
    partial_exit_used = False
    full_exit_used = False
    horizon_exit_used = False
    last_entry_index: int | None = None
    last_partial_exit_index: int | None = None
    actions: list[Strategy1Action] = []

    def buy(index: int) -> None:
        nonlocal cash, shares, entries_used, last_entry_index
        if entries_used >= len(ENTRY_WEIGHTS):
            raise RuntimeError("Strategy 1 attempted more than three entries")
        amount = ENTRY_WEIGHTS[entries_used]
        price = float(events.at[index, "close"])
        if cash + 1e-12 < amount:
            raise RuntimeError("Strategy 1 attempted to exceed its fixed capital budget")
        shares += amount / price
        cash -= amount
        entries_used += 1
        last_entry_index = index
        action = "entry1" if entries_used == 1 else f"addon{entries_used - 1}"
        actions.append(Strategy1Action(index=index, action=action, price=price, fraction=amount))

    buy(start)

    for i in range(start + 1, end + 1):
        price = float(events.at[i, "close"])
        exit_eligible = last_entry_index is None or (i - last_entry_index > COOLDOWN_SESSIONS)

        # MA10 full exit has priority when an exit is eligible and both exit
        # events coincide. A full exit permanently ends this one campaign.
        if exit_eligible and bool(events.at[i, "exit10_event"]):
            cash += shares * price
            shares = 0.0
            full_exit_used = True
            actions.append(Strategy1Action(index=i, action="exit10_full", price=price, fraction=1.0))
            break

        if (
            exit_eligible
            and bool(events.at[i, "exit5_event"])
            and not partial_exit_used
            and shares > 0.0
        ):
            sold = 0.5 * shares
            cash += sold * price
            shares -= sold
            partial_exit_used = True
            last_partial_exit_index = i
            actions.append(Strategy1Action(index=i, action="exit5_half", price=price, fraction=0.5))
            continue

        addon_eligible = (
            last_partial_exit_index is None
            or i - last_partial_exit_index > COOLDOWN_SESSIONS
        )
        if (
            addon_eligible
            and entries_used < len(ENTRY_WEIGHTS)
            and bool(events.at[i, "breakout20_event"])
        ):
            buy(i)

    if shares > 0.0:
        price = float(events.at[end, "close"])
        cash += shares * price
        shares = 0.0
        horizon_exit_used = True
        actions.append(Strategy1Action(index=end, action="horizon_exit", price=price, fraction=1.0))

    return Strategy1Run(
        final_return=float(cash - 1.0),
        start_index=start,
        entries_used=entries_used,
        campaigns_used=1,
        partial_exit_used=partial_exit_used,
        full_exit_used=full_exit_used,
        horizon_exit_used=horizon_exit_used,
        partial_exit_count=int(partial_exit_used),
        full_exit_count=int(full_exit_used),
        actions=tuple(actions),
    )


def oracle_value_for_window(events: pd.DataFrame, start_exclusive: int, end_inclusive: int) -> Strategy1Run:
    """Return the best legal single-campaign Strategy 1 path in a future window.

    The Oracle may choose which legal first-entry candidate starts the campaign,
    or choose no trade. Once started, add-ons, exits, and spacing rules are
    deterministic. A full exit ends the only allowed campaign.
    """
    best = Strategy1Run(0.0, None, 0, 0, False, False, False)

    first = start_exclusive + 1
    for i in range(first, end_inclusive + 1):
        if not bool(events.at[i, "entry1_event"]):
            continue
        run = _simulate_from_start(events, i, end_inclusive)
        if run.final_return > best.final_return:
            best = run

    return best


def make_strategy1_oracle_labels(
    df: pd.DataFrame,
    horizons: tuple[int, ...] = STRATEGY1_HORIZONS,
) -> pd.DataFrame:
    """Build Strategy 1 Oracle Value labels and action metadata for each future horizon."""
    if not horizons:
        raise ValueError("At least one horizon is required")
    if any(h <= 0 for h in horizons):
        raise ValueError("Horizons must be positive")

    events = add_strategy1_events(df).reset_index(drop=True)
    max_h = max(horizons)
    rows: list[dict[str, float | int | bool | object]] = []

    for t in range(len(events) - max_h):
        row: dict[str, float | int | bool | object] = {"date": pd.to_datetime(events.at[t, "date"])}
        for h in horizons:
            run = oracle_value_for_window(events, t, t + h)
            row[f"oracle_value_{h}"] = float(run.final_return)
            row[f"oracle_entries_{h}"] = int(run.entries_used)
            row[f"oracle_campaigns_{h}"] = int(run.campaigns_used)
            row[f"oracle_start_offset_{h}"] = -1 if run.start_index is None else int(run.start_index - t)
            row[f"oracle_partial_exit_{h}"] = bool(run.partial_exit_used)
            row[f"oracle_full_exit_{h}"] = bool(run.full_exit_used)
            row[f"oracle_horizon_exit_{h}"] = bool(run.horizon_exit_used)
            row[f"oracle_partial_exit_count_{h}"] = int(run.partial_exit_count)
            row[f"oracle_full_exit_count_{h}"] = int(run.full_exit_count)
        rows.append(row)

    out = pd.DataFrame(rows)
    value_columns = [f"oracle_value_{h}" for h in horizons]
    if not np.isfinite(out[value_columns].to_numpy(dtype=float)).all():
        raise ValueError("Non-finite Strategy 1 Oracle Value found")
    if (out[value_columns] < -1e-12).any().any():
        raise ValueError("Strategy 1 Oracle Value must be non-negative because no-trade is allowed")
    return out

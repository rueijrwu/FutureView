from __future__ import annotations

import os
import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import build_representation_a_table
from .strategy1_cq_90d_rank_audit import build_window_q
from .strategy1_layer1_forward_w_audit import _classify

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", f"strategy1-layer1-transition-audit-w{W}.csv")


def build_row_level_transitions(classified: pd.DataFrame) -> pd.DataFrame:
    """Measure persistence and first opposite-state passage from every High/Low row."""
    x = classified.sort_values("start_index").reset_index(drop=True)
    rows: list[dict[str, object]] = []

    for i, r in x.iterrows():
        state = str(r.state)
        if state not in ("high", "low"):
            continue
        opposite = "low" if state == "high" else "high"
        start = int(r.start_index)

        leave_idx = None
        for j in range(i + 1, len(x)):
            if str(x.at[j, "state"]) != state:
                leave_idx = j
                break

        if leave_idx is None:
            days_until_leave = np.nan
            future_same_days = np.nan
        else:
            leave_start = int(x.at[leave_idx, "start_index"])
            days_until_leave = leave_start - start
            future_same_days = max(days_until_leave - 1, 0)

        opposite_idx = None
        for j in range(i + 1, len(x)):
            if str(x.at[j, "state"]) == opposite:
                opposite_idx = j
                break

        if opposite_idx is None:
            days_to_opposite = np.nan
            neutral_days_before_opposite = np.nan
            same_state_days_before_opposite = np.nan
        else:
            opposite_start = int(x.at[opposite_idx, "start_index"])
            days_to_opposite = opposite_start - start
            between = x.iloc[i + 1:opposite_idx]
            neutral_days_before_opposite = int((between.state == "neutral").sum())
            same_state_days_before_opposite = int((between.state == state).sum())

        rows.append({
            "start_index": start,
            "state": state,
            "past_C": float(r.past_C),
            "past_Q": float(r.past_Q),
            "past_entries": int(r.past_entries),
            "days_until_leave": days_until_leave,
            "future_same_days": future_same_days,
            "leave_censored": leave_idx is None,
            "opposite_state": opposite,
            "days_to_opposite": days_to_opposite,
            "neutral_days_before_opposite": neutral_days_before_opposite,
            "same_state_days_before_opposite": same_state_days_before_opposite,
            "opposite_censored": opposite_idx is None,
        })

    return pd.DataFrame(rows)


def _dist(name: str, values: pd.Series) -> None:
    a = values.dropna().to_numpy(dtype=float)
    if len(a) == 0:
        print(f"S1 L1TRANS DIST W={W} metric={name} n=0")
        return
    q = np.quantile(a, [0.10, 0.25, 0.50, 0.75, 0.90])
    print(
        f"S1 L1TRANS DIST W={W} metric={name} n={len(a)} mean={a.mean():.3f} "
        f"p10={q[0]:.3f} p25={q[1]:.3f} median={q[2]:.3f} "
        f"p75={q[3]:.3f} p90={q[4]:.3f} max={a.max():.3f}"
    )


def main() -> None:
    if W not in (15, 30, 60):
        raise ValueError("transition audit supports W in {15,30,60}")

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    windows = build_representation_a_table(
        df, paths, window=W, stride=1, random_samples=20, random_seed=SEED
    )
    wq = build_window_q(windows, paths).sort_values("start_index").reset_index(drop=True)
    classified = _classify(wq).sort_values("start_index").reset_index(drop=True)
    out = build_row_level_transitions(classified)
    out.to_csv(OUTPUT, index=False)

    print(
        f"S1 L1TRANS START W={W} ticker={TICKER} rows={audit.rows} "
        f"classified={len(classified)} extreme_rows={len(out)}"
    )

    for state, opposite in (("high", "low"), ("low", "high")):
        g = out.loc[out.state == state]
        leave_valid = g.loc[~g.leave_censored]
        opp_valid = g.loc[~g.opposite_censored]
        print(
            f"S1 L1TRANS STATE W={W} state={state} n={len(g)} "
            f"leave_valid={len(leave_valid)} leave_censored={int(g.leave_censored.sum())} "
            f"opposite={opposite} opposite_valid={len(opp_valid)} "
            f"opposite_censored={int(g.opposite_censored.sum())}"
        )
        _dist(f"{state}_days_until_leave", leave_valid.days_until_leave)
        _dist(f"{state}_future_same_days", leave_valid.future_same_days)
        _dist(f"{state}_to_{opposite}_days", opp_valid.days_to_opposite)
        _dist(f"{state}_to_{opposite}_neutral_days", opp_valid.neutral_days_before_opposite)
        _dist(
            f"{state}_to_{opposite}_same_state_days_before_opposite",
            opp_valid.same_state_days_before_opposite,
        )

    print(f"S1 L1TRANS OUTPUT W={W} file={OUTPUT} rows={len(out)}")
    print(f"S1 L1TRANS COMPLETE W={W}")


if __name__ == "__main__":
    main()

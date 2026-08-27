from __future__ import annotations

from pathlib import Path
import os

import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import build_representation_a_table
from .strategy1_layer1_state import build_samples
from .strategy1_layer1_threshold_audit import build_outcome_table

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
WINDOW = int(os.environ.get("FUTUREVIEW_LAYER1_WINDOW", "30"))
REFERENCE_DAYS = int(os.environ.get("FUTUREVIEW_LAYER1_REFERENCE_DAYS", "60"))
LOW_Q = float(os.environ.get("FUTUREVIEW_LAYER1_LOW_Q", "0.40"))
HIGH_Q = float(os.environ.get("FUTUREVIEW_LAYER1_HIGH_Q", "0.60"))
RANDOM_SAMPLES = int(os.environ.get("FUTUREVIEW_A_RANDOM_SAMPLES", "20"))
RANDOM_SEED = int(os.environ.get("FUTUREVIEW_A_RANDOM_SEED", "20260827"))
OUTPUT = Path(os.environ.get("FUTUREVIEW_CQ_AUDIT_OUTPUT", "strategy1-cq-target-audit.csv"))
EPS = float(os.environ.get("FUTUREVIEW_CQ_EPS", "1e-12"))


def gate_at_anchor(outcomes: pd.DataFrame, anchor: int) -> dict[str, float | int] | None:
    """Compute the known historical gate at anchor from completed outcomes only."""
    completed = outcomes.loc[outcomes["dependency_end"] <= anchor].copy()
    if completed.empty:
        return None

    current = completed.sort_values(["dependency_end", "start_index"]).iloc[-1]
    current_dep = int(current["dependency_end"])
    ref = completed.loc[
        (completed["dependency_end"] >= current_dep - REFERENCE_DAYS)
        & (completed["dependency_end"] < current_dep)
    ]
    if len(ref) < max(10, REFERENCE_DAYS // 3):
        return None

    c_low = float(ref["C"].quantile(LOW_Q))
    c_high = float(ref["C"].quantile(HIGH_Q))
    u_low = float(ref["U"].quantile(LOW_Q))
    u_high = float(ref["U"].quantile(HIGH_Q))
    c = float(current["C"])
    u = float(current["U"])

    state = 0
    if c > c_high and u > u_high:
        state = 1
    elif c < c_low and u < u_low:
        state = -1

    return {
        "gate_state": state,
        "gate_source_start_index": int(current["start_index"]),
        "gate_source_dependency_end": current_dep,
        "gate_C": c,
        "gate_U": u,
        "gate_C_low": c_low,
        "gate_C_high": c_high,
        "gate_U_low": u_low,
        "gate_U_high": u_high,
        "gate_reference_count": int(len(ref)),
    }


def build_cq_target_pairs(
    df: pd.DataFrame,
    windows: pd.DataFrame,
    paths: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Build future (C,Q) pairs for anchors whose known historical gate is High or Low."""
    input_meta, _ = build_samples(df, windows)
    valid_starts = set(input_meta["start_index"].astype(int).tolist())
    outcomes = build_outcome_table(df, windows)
    path_by_entry = paths.set_index("entry_index")["campaign_return"]

    rows: list[dict[str, float | int | str]] = []
    counters = {
        "candidate_anchors": 0,
        "gate_available": 0,
        "gate_high": 0,
        "gate_neutral": 0,
        "gate_low": 0,
        "gate_pass": 0,
        "future_no_entry": 0,
        "future_c_zero": 0,
    }

    for w in windows.sort_values("start_index").itertuples(index=False):
        start = int(w.start_index)
        if start not in valid_starts:
            continue
        counters["candidate_anchors"] += 1
        anchor = start - 1
        gate = gate_at_anchor(outcomes, anchor)
        if gate is None:
            continue
        counters["gate_available"] += 1
        state = int(gate["gate_state"])
        if state == 1:
            counters["gate_high"] += 1
        elif state == -1:
            counters["gate_low"] += 1
        else:
            counters["gate_neutral"] += 1

        # Deterministic gate: High and Low pass; Neutral is filtered.
        if state == 0:
            continue
        counters["gate_pass"] += 1

        end = int(w.end_index)
        entries = paths.loc[
            (paths["entry_index"].astype(int) >= start)
            & (paths["entry_index"].astype(int) <= end),
            "entry_index",
        ].astype(int).to_numpy()
        if len(entries) == 0:
            counters["future_no_entry"] += 1
            continue

        future_u = float(w.U)
        future_c = float(w.U - w.B_periodic)
        if not np.isfinite(future_c):
            continue
        if abs(future_c) <= EPS:
            counters["future_c_zero"] += 1

        for entry in entries:
            pe = float(path_by_entry.loc[int(entry)])
            q = future_u - pe
            if not np.isfinite(q):
                continue
            if q < -EPS:
                raise RuntimeError(
                    f"Q invariant violated: U={future_u:.12f} P_E={pe:.12f} Q={q:.12f} entry={entry}"
                )
            if abs(q) <= EPS:
                q = 0.0
            rows.append(
                {
                    "ticker": TICKER,
                    "anchor_index": anchor,
                    "future_start_index": start,
                    "future_end_index": end,
                    "future_start_date": w.start_date,
                    "future_end_date": w.end_date,
                    "future_entry_index": int(entry),
                    "future_U": future_u,
                    "future_B_periodic": float(w.B_periodic),
                    "future_C": future_c,
                    "future_P_E": pe,
                    "future_Q": float(q),
                    **gate,
                }
            )

    if not rows:
        raise RuntimeError("no gate-passed future C/Q target pairs were produced")
    return pd.DataFrame(rows), counters


def _pct(v: pd.Series, q: float) -> float:
    return float(v.quantile(q))


def _print_group(name: str, pairs: pd.DataFrame) -> None:
    anchors = pairs["anchor_index"].nunique()
    c = pairs.drop_duplicates("anchor_index")["future_C"]
    q = pairs["future_Q"]
    print(
        f"S1 CQ AUDIT GROUP gate={name} anchors={anchors} pairs={len(pairs)} "
        f"pairs_per_anchor_mean={len(pairs)/anchors:.3f} pairs_per_anchor_median={pairs.groupby('anchor_index').size().median():.1f}"
    )
    print(
        f"S1 CQ AUDIT C gate={name} mean={c.mean():.6f} "
        f"p10={_pct(c,0.10):.6f} p25={_pct(c,0.25):.6f} median={_pct(c,0.50):.6f} "
        f"p75={_pct(c,0.75):.6f} p90={_pct(c,0.90):.6f}"
    )
    print(
        f"S1 CQ AUDIT Q gate={name} mean={q.mean():.6f} min={q.min():.6f} "
        f"p10={_pct(q,0.10):.6f} p25={_pct(q,0.25):.6f} median={_pct(q,0.50):.6f} "
        f"p75={_pct(q,0.75):.6f} p90={_pct(q,0.90):.6f} max={q.max():.6f} zero_rate={(q == 0.0).mean():.6f}"
    )


def main() -> None:
    if WINDOW != 30 or REFERENCE_DAYS != 60:
        raise ValueError("C/Q audit is currently locked to W=30 and gate reference=60")
    if not (np.isclose(LOW_Q, 0.40) and np.isclose(HIGH_Q, 0.60)):
        raise ValueError("C/Q audit is currently locked to 40/60 gate percentiles")

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    windows = build_representation_a_table(
        df,
        paths,
        window=WINDOW,
        stride=1,
        random_samples=RANDOM_SAMPLES,
        random_seed=RANDOM_SEED,
    )
    pairs, counters = build_cq_target_pairs(df, windows, paths)

    print(
        f"S1 CQ AUDIT START ticker={TICKER} rows={audit.rows} first={audit.start} last={audit.end} "
        f"W={WINDOW} gate_reference={REFERENCE_DAYS} gate_percentiles={LOW_Q:.2f},{HIGH_Q:.2f}"
    )
    print(
        "S1 CQ AUDIT DEFINITION gate=known_completed_history_high_or_low_pass_neutral_filter "
        "target=future_joint_distribution_p(C,Q|X,gate_state) Q=U-P_E"
    )
    print("S1 CQ AUDIT GATE " + " ".join(f"{k}={v}" for k, v in counters.items()))

    for state, name in ((1, "high"), (-1, "low")):
        group = pairs.loc[pairs["gate_state"] == state].copy()
        if group.empty:
            print(f"S1 CQ AUDIT GROUP gate={name} anchors=0 pairs=0")
            continue
        _print_group(name, group)

    if pairs["future_Q"].min() < -EPS:
        raise RuntimeError("Q must be non-negative under Q=U-P_E")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pairs.to_csv(OUTPUT, index=False)
    print(f"S1 CQ AUDIT OUTPUT file={OUTPUT} rows={len(pairs)}")
    print("S1 CQ AUDIT COMPLETE")


if __name__ == "__main__":
    main()

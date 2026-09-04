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
from .strategy1_layer2_price_distribution import HORIZON, SEED, W
from .strategy1_layer2_price_distribution_causal import build_causal_layer1_wq

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer1-asof-vs-final.csv")


def _pct(num: int, den: int) -> float:
    return float(num / den) if den else float("nan")


def main() -> None:
    if W != 30 or HORIZON != 3:
        raise ValueError("audit locked to W30/future3")

    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    audit = validate_daily_ohlcv(df, minimum_rows=1800)
    events = add_strategy1_events(df).reset_index(drop=True)

    # Final/retrospective Layer1: build each W from completed deterministic paths.
    final_paths = build_deterministic_path_table(events)
    final_windows = build_representation_a_table(
        df, final_paths, window=W, stride=1, random_samples=20, random_seed=SEED
    )
    final_wq = build_window_q(final_windows, final_paths).sort_values("start_index").reset_index(drop=True)
    final_cls = _classify(final_wq)[["start_index", "end_index", "state", "past_C", "past_Q"]].copy()
    final_cls = final_cls.rename(
        columns={"state": "final_state", "past_C": "final_C", "past_Q": "final_Q"}
    )

    # As-of Layer1: each W ending at t is rebuilt using only rows <= t and open paths are closed at t.
    asof_wq = build_causal_layer1_wq(df, events)
    asof_cls = _classify(asof_wq)[["start_index", "end_index", "state", "past_C", "past_Q"]].copy()
    asof_cls = asof_cls.rename(
        columns={"state": "asof_state", "past_C": "asof_C", "past_Q": "asof_Q"}
    )

    out = asof_cls.merge(final_cls, on=["start_index", "end_index"], how="inner", validate="one_to_one")
    if out.empty:
        raise RuntimeError("no overlapping classified W between as-of and final Layer1")

    out["asof_non_neutral"] = out["asof_state"] != "neutral"
    out["final_non_neutral"] = out["final_state"] != "neutral"
    out["same_state"] = out["asof_state"] == out["final_state"]
    out["contamination"] = out["asof_non_neutral"] & ~out["final_non_neutral"]
    out["missed_signal"] = ~out["asof_non_neutral"] & out["final_non_neutral"]

    close = df["close"].to_numpy(dtype=float)
    actual_r3 = np.full(len(out), np.nan, dtype=float)
    for i, end in enumerate(out["end_index"].astype(int).to_numpy()):
        if end + HORIZON < len(close):
            actual_r3[i] = float(np.log(close[end + HORIZON] / close[end]))
    out["actual_r3"] = actual_r3
    out.to_csv(OUTPUT, index=False)

    n = len(out)
    same = int(out["same_state"].sum())
    asof_nn = int(out["asof_non_neutral"].sum())
    final_nn = int(out["final_non_neutral"].sum())
    contam = int(out["contamination"].sum())
    missed = int(out["missed_signal"].sum())
    stable_nn = int((out["asof_non_neutral"] & out["final_non_neutral"]).sum())

    print(
        f"S1 L1AVF START ticker={TICKER} rows={audit.rows} matched={n} "
        f"asof_non_neutral={asof_nn} final_non_neutral={final_nn}"
    )
    print(
        f"S1 L1AVF SUMMARY same_state={same} same_rate={_pct(same,n):.6f} "
        f"contamination={contam} contamination_rate_given_asof_non_neutral={_pct(contam,asof_nn):.6f} "
        f"missed_signal={missed} missed_rate_given_final_non_neutral={_pct(missed,final_nn):.6f} "
        f"stable_non_neutral={stable_nn}"
    )

    for a in ("high", "neutral", "low"):
        row_total = int((out["asof_state"] == a).sum())
        for f in ("high", "neutral", "low"):
            count = int(((out["asof_state"] == a) & (out["final_state"] == f)).sum())
            print(
                f"S1 L1AVF CONFUSION asof={a} final={f} n={count} "
                f"p_given_asof={_pct(count,row_total):.6f}"
            )

    groups = {
        "stable_non_neutral": out["asof_non_neutral"] & out["final_non_neutral"],
        "contamination": out["contamination"],
        "missed_signal": out["missed_signal"],
        "stable_neutral": ~out["asof_non_neutral"] & ~out["final_non_neutral"],
    }
    for name, mask in groups.items():
        r = out.loc[mask, "actual_r3"].dropna().to_numpy(dtype=float)
        if len(r):
            print(
                f"S1 L1AVF R3 group={name} n={len(r)} mean={r.mean():.6f} "
                f"median={np.median(r):.6f} p_up={(r > 0).mean():.6f}"
            )

    print(f"S1 L1AVF OUTPUT file={OUTPUT} rows={n}")
    print("S1 L1AVF COMPLETE")


if __name__ == "__main__":
    main()

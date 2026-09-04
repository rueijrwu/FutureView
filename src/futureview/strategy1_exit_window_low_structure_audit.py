from __future__ import annotations

import os
import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_exit_window_cq_audit import final_exit_index, classify_causal
from .strategy1_representation_a import _periodic_baseline

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-exit-window-low-structure-audit.csv")


def build_windows(df: pd.DataFrame, paths: pd.DataFrame) -> pd.DataFrame:
    close = df["close"].to_numpy(dtype=float)
    p = paths.copy()
    p["final_exit_index"] = final_exit_index(p)
    rows: list[dict[str, object]] = []
    for start in range(0, len(df) - W + 1):
        end = start + W - 1
        g = p.loc[(p.final_exit_index >= start) & (p.final_exit_index <= end)]
        if g.empty:
            continue
        r = g["campaign_return"].to_numpy(dtype=float)
        b = float(_periodic_baseline(close, start, end))
        u = float(np.max(r))
        rows.append({
            "start_index": start,
            "end_index": end,
            "start_date": str(pd.Timestamp(df.at[start, "date"]).date()),
            "end_date": str(pd.Timestamp(df.at[end, "date"]).date()),
            "U": u,
            "B_periodic": b,
            "C": u - b,
            "Q": float(np.std(r, ddof=0)),
            "P_mean": float(np.mean(r)),
            "P_median": float(np.median(r)),
            "P_min": float(np.min(r)),
            "P_p25": float(np.quantile(r, 0.25)),
            "P_p75": float(np.quantile(r, 0.75)),
            "path_count": int(len(r)),
            "share_below_B": float(np.mean(r < b)),
            "share_above_B": float(np.mean(r > b)),
        })
    return pd.DataFrame(rows)


def _q(g: pd.DataFrame, col: str, p: float) -> float:
    return float(g[col].quantile(p))


def main() -> None:
    if W != 30:
        raise ValueError("audit locked to W30")
    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    audit = validate_daily_ohlcv(df, minimum_rows=1800)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    w = build_windows(df, paths)
    classified = classify_causal(w)

    print(f"S1 LOWSTRUCT START ticker={TICKER} rows={audit.rows} paths={len(paths)} windows={len(w)} classified={len(classified)}")
    print("S1 LOWSTRUCT DEFINITION membership=final_exit_in_W Q=population_std(path_returns) Layer1_role=filter_neutral_not_directional_signal")

    for state in ("high", "neutral", "low"):
        g = classified[classified.state == state].copy()
        if g.empty:
            continue
        print(
            f"S1 LOWSTRUCT STATE state={state} n={len(g)} "
            f"U_mean={g.U.mean():.6f} U_median={g.U.median():.6f} "
            f"B_mean={g.B_periodic.mean():.6f} C_mean={g.C.mean():.6f} Q_mean={g.Q.mean():.6f} "
            f"P_mean={g.P_mean.mean():.6f} P_median={g.P_median.mean():.6f} P_min={g.P_min.mean():.6f} "
            f"paths_mean={g.path_count.mean():.3f} share_below_B_mean={g.share_below_B.mean():.6f}"
        )
        print(
            f"S1 LOWSTRUCT QUANTILES state={state} "
            f"C20={_q(g,'C',.2):.6f} C50={_q(g,'C',.5):.6f} C80={_q(g,'C',.8):.6f} "
            f"U20={_q(g,'U',.2):.6f} U50={_q(g,'U',.5):.6f} U80={_q(g,'U',.8):.6f} "
            f"B20={_q(g,'B_periodic',.2):.6f} B50={_q(g,'B_periodic',.5):.6f} B80={_q(g,'B_periodic',.8):.6f} "
            f"Q20={_q(g,'Q',.2):.6f} Q50={_q(g,'Q',.5):.6f} Q80={_q(g,'Q',.8):.6f}"
        )
        print(
            f"S1 LOWSTRUCT CONDITIONS state={state} "
            f"U_gt_B={(g.U > g.B_periodic).mean():.6f} "
            f"Pmean_lt_B={(g.P_mean < g.B_periodic).mean():.6f} "
            f"Pmedian_lt_B={(g.P_median < g.B_periodic).mean():.6f} "
            f"Pmin_lt_B={(g.P_min < g.B_periodic).mean():.6f} "
            f"U_positive={(g.U > 0).mean():.6f}"
        )

    low = classified[classified.state == "low"].copy()
    if len(low):
        print(
            f"S1 LOWSTRUCT LOW_GAPS n={len(low)} "
            f"U_minus_Pmean={(low.U-low.P_mean).mean():.6f} "
            f"U_minus_Pmedian={(low.U-low.P_median).mean():.6f} "
            f"U_minus_Pmin={(low.U-low.P_min).mean():.6f} "
            f"B_minus_Pmean={(low.B_periodic-low.P_mean).mean():.6f} "
            f"B_minus_Pmedian={(low.B_periodic-low.P_median).mean():.6f}"
        )

    classified.to_csv(OUTPUT, index=False)
    print(f"S1 LOWSTRUCT OUTPUT file={OUTPUT} rows={len(classified)}")
    print("S1 LOWSTRUCT COMPLETE")


if __name__ == "__main__":
    main()

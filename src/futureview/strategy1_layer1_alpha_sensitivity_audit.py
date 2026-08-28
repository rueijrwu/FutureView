"""Descriptive sensitivity audit for simple Layer1 sample weights.

High=1, Low=1, Neutral=alpha. No Layer2 training is performed here.
"""

from __future__ import annotations

import os
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
SHORT_REF = int(os.environ.get("FUTUREVIEW_SHORT_REF", "90"))
LONG_REF = int(os.environ.get("FUTUREVIEW_LONG_REF", "756"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
ALPHAS = tuple(float(x) for x in os.environ.get("FUTUREVIEW_NEUTRAL_ALPHAS", "0,0.1,0.2,0.5,1.0").split(","))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer1-alpha-sensitivity-audit.csv")


def summarize_alpha(classified: pd.DataFrame, alpha: float) -> dict[str, float]:
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha must be in [0,1]")
    n_high = int((classified.state == "high").sum())
    n_neutral = int((classified.state == "neutral").sum())
    n_low = int((classified.state == "low").sum())
    extreme_mass = float(n_high + n_low)
    neutral_mass = float(alpha * n_neutral)
    total_mass = extreme_mass + neutral_mass
    return {
        "alpha": alpha,
        "n_high": n_high,
        "n_neutral": n_neutral,
        "n_low": n_low,
        "raw_n": len(classified),
        "high_weight_mass": float(n_high),
        "neutral_weight_mass": neutral_mass,
        "low_weight_mass": float(n_low),
        "total_weight_mass": total_mass,
        "neutral_weight_share": neutral_mass / total_mass if total_mass else float("nan"),
        "extreme_weight_share": extreme_mass / total_mass if total_mass else float("nan"),
        "effective_mass_fraction_vs_alpha1": total_mass / len(classified) if len(classified) else float("nan"),
    }


def main() -> None:
    if W != 30 or SHORT_REF != 90 or LONG_REF != 756:
        raise ValueError("initial alpha sensitivity audit is locked to W30 / short90 / long756")

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    windows = build_representation_a_table(df, paths, window=W, stride=1, random_samples=20, random_seed=SEED)
    wq = build_window_q(windows, paths).sort_values("start_index").reset_index(drop=True)
    classified = _classify(wq).sort_values("start_index").reset_index(drop=True)

    rows = [summarize_alpha(classified, alpha) for alpha in ALPHAS]
    out = pd.DataFrame(rows)
    out.to_csv(OUTPUT, index=False)

    counts = classified.state.value_counts().to_dict()
    print(
        f"S1 L1ALPHA START ticker={TICKER} rows={audit.rows} W={W} classified={len(classified)} "
        f"high={counts.get('high',0)} neutral={counts.get('neutral',0)} low={counts.get('low',0)}"
    )
    print("S1 L1ALPHA DEFINITION high_weight=1 low_weight=1 neutral_weight=alpha")
    for r in out.itertuples(index=False):
        print(
            f"S1 L1ALPHA RESULT alpha={r.alpha:.3f} total_mass={r.total_weight_mass:.3f} "
            f"effective_mass_fraction={r.effective_mass_fraction_vs_alpha1:.6f} "
            f"neutral_share={r.neutral_weight_share:.6f} extreme_share={r.extreme_weight_share:.6f}"
        )
    print(f"S1 L1ALPHA OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 L1ALPHA COMPLETE")


if __name__ == "__main__":
    main()

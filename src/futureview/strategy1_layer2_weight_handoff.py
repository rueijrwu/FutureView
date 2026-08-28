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
MODEL_HISTORY = int(os.environ.get("FUTUREVIEW_MODEL_HISTORY", "90"))
NEUTRAL_ALPHA = float(os.environ.get("FUTUREVIEW_NEUTRAL_ALPHA", "0.2"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer2-weight-handoff.csv")


def state_weight(state: str, neutral_alpha: float = 0.2) -> float:
    state = str(state).lower()
    if not 0.0 <= neutral_alpha <= 1.0:
        raise ValueError("neutral_alpha must be in [0,1]")
    if state in ("high", "low"):
        return 1.0
    if state == "neutral":
        return float(neutral_alpha)
    raise ValueError(f"invalid Layer1 state: {state}")


def weighted_mean_loss(per_sample_loss: np.ndarray, weights: np.ndarray) -> float:
    """Weighted reduction for future Layer2 loss.

    `per_sample_loss` is already reduced across model outputs for each sample.
    The reduction is sum(w_i * loss_i) / sum(w_i), so changing alpha changes
    relative sample importance without changing the nominal loss scale.
    """
    losses = np.asarray(per_sample_loss, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    if losses.ndim != 1 or w.ndim != 1 or len(losses) != len(w) or len(w) == 0:
        raise ValueError("losses and weights must be non-empty 1D arrays of equal length")
    if not np.isfinite(losses).all() or not np.isfinite(w).all() or (w < 0).any():
        raise ValueError("losses/weights must be finite and weights non-negative")
    denom = float(w.sum())
    if denom <= 0:
        raise ValueError("sum of weights must be positive")
    return float(np.dot(losses, w) / denom)


def build_handoff_table(
    classified: pd.DataFrame,
    n_market_rows: int,
    model_history: int = 90,
    neutral_alpha: float = 0.2,
) -> pd.DataFrame:
    """Align each retrospective Layer1 W-state to a strictly prior Layer2 input.

    For Layer1 interval [start_index, end_index], the Layer2 price/volume input is
    [start_index-model_history, start_index-1]. The labeled W interval itself is
    therefore excluded from the model input.
    """
    required = {"start_index", "end_index", "state", "past_C", "past_Q"}
    missing = required.difference(classified.columns)
    if missing:
        raise ValueError(f"classified missing columns: {sorted(missing)}")
    if model_history <= 0:
        raise ValueError("model_history must be positive")

    rows: list[dict[str, object]] = []
    for r in classified.sort_values("start_index").itertuples(index=False):
        label_start = int(r.start_index)
        label_end = int(r.end_index)
        input_start = label_start - model_history
        input_end = label_start - 1
        if input_start < 0 or input_end >= n_market_rows:
            continue
        state = str(r.state).lower()
        rows.append(
            {
                "input_start": input_start,
                "input_end": input_end,
                "input_length": model_history,
                "layer1_start": label_start,
                "layer1_end": label_end,
                "state": state,
                "sample_weight": state_weight(state, neutral_alpha),
                "C": float(r.past_C),
                "Q": float(r.past_Q),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    if W != 30:
        raise ValueError("initial Layer2 weight handoff audit is locked to W=30")
    if MODEL_HISTORY != 90:
        raise ValueError("initial Layer2 weight handoff audit is locked to 90-session model history")
    if abs(NEUTRAL_ALPHA - 0.2) > 1e-12:
        raise ValueError("working baseline neutral alpha is locked to 0.2 for this audit")

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    windows = build_representation_a_table(
        df, paths, window=W, stride=1, random_samples=20, random_seed=SEED
    )
    wq = build_window_q(windows, paths).sort_values("start_index").reset_index(drop=True)
    classified = _classify(wq).sort_values("start_index").reset_index(drop=True)
    handoff = build_handoff_table(classified, len(df), MODEL_HISTORY, NEUTRAL_ALPHA)
    handoff.to_csv(OUTPUT, index=False)

    if handoff.empty:
        raise RuntimeError("no aligned Layer2 samples")

    bad_len = int((handoff.input_length != MODEL_HISTORY).sum())
    overlap = int((handoff.input_end >= handoff.layer1_start).sum())
    bad_weights = int(
        (~handoff.apply(
            lambda r: np.isclose(r.sample_weight, state_weight(r.state, NEUTRAL_ALPHA)), axis=1
        )).sum()
    )

    print(
        f"S1 L2WEIGHT START ticker={TICKER} rows={audit.rows} W={W} model_history={MODEL_HISTORY} "
        f"classified={len(classified)} aligned={len(handoff)} alpha={NEUTRAL_ALPHA:.3f}"
    )
    print(
        "S1 L2WEIGHT ALIGNMENT "
        f"bad_length={bad_len} input_label_overlap={overlap} bad_weights={bad_weights} "
        "rule=input_end=layer1_start-1"
    )
    for state in ("high", "neutral", "low"):
        g = handoff.loc[handoff.state == state]
        print(
            f"S1 L2WEIGHT STATE state={state} n={len(g)} "
            f"weight={(state_weight(state, NEUTRAL_ALPHA)):.3f} "
            f"mass={g.sample_weight.sum():.3f}"
        )
    total_mass = float(handoff.sample_weight.sum())
    neutral_mass = float(handoff.loc[handoff.state == "neutral", "sample_weight"].sum())
    print(
        f"S1 L2WEIGHT MASS total={total_mass:.3f} neutral_share={neutral_mass/total_mass:.6f} "
        f"extreme_share={1.0-neutral_mass/total_mass:.6f}"
    )

    # Deterministic smoke check of the exact weighted reduction intended for Layer2.
    probe_loss = np.array([1.0, 1.0, 1.0], dtype=float)
    probe_w = np.array([1.0, NEUTRAL_ALPHA, 1.0], dtype=float)
    probe = weighted_mean_loss(probe_loss, probe_w)
    print(f"S1 L2WEIGHT LOSS_SMOKE value={probe:.6f} expected=1.000000")
    print(f"S1 L2WEIGHT OUTPUT file={OUTPUT} rows={len(handoff)}")
    print("S1 L2WEIGHT COMPLETE")


if __name__ == "__main__":
    main()

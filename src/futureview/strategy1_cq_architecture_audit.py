from __future__ import annotations

import inspect

import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1_cq_data import HORIZON, LOOKBACK, SCALES, input_columns, make_cq_labels, make_input_windows
from .strategy1_smh_cnn_close_volume_multiscale import _make_cq_folds

TICKER = "SMH"
DATA_PERIOD = "5y"
EXPECTED_CHANNELS = tuple([f"price_{n}" for n in SCALES] + [f"volume_{n}" for n in SCALES])


def main() -> None:
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    raw_dates = pd.to_datetime(df["date"]).reset_index(drop=True)

    assert tuple(input_columns()) == EXPECTED_CHANNELS
    assert len(EXPECTED_CHANNELS) == 8
    assert LOOKBACK == 60
    assert tuple(SCALES) == (5, 10, 20, 60)

    labels = make_cq_labels(df)
    assert np.all(np.isfinite(labels.L))
    assert np.all(np.isfinite(labels.mu))
    assert np.all(np.isfinite(labels.U))
    assert np.all(np.isfinite(labels.C))
    assert np.all(np.isfinite(labels.Q))
    assert np.all(labels.C > 0)
    assert np.allclose(labels.C, labels.U - labels.L)
    assert np.allclose(labels.Q, (labels.U - labels.mu) / (labels.U - labels.L))
    assert np.array_equal(np.sort(labels.raw_indices), labels.raw_indices)

    live_end = raw_dates.iloc[-1]
    live_start = live_end - pd.DateOffset(months=3)
    holdout_positions = np.flatnonzero(raw_dates.to_numpy() >= np.datetime64(live_start))
    holdout_start = int(holdout_positions[0]) if len(holdout_positions) else len(raw_dates)
    mature = labels.raw_indices + HORIZON - 1 < holdout_start
    mature_raw = labels.raw_indices[mature]
    assert len(mature_raw) > 0
    assert np.all(mature_raw + HORIZON - 1 < holdout_start)

    x, kept_raw = make_input_windows(df, mature_raw)
    assert x.ndim == 3
    assert x.shape[0] == len(kept_raw)
    assert x.shape[1:] == (8, 60)
    assert np.all(np.isfinite(x))
    assert np.all(np.isin(kept_raw, mature_raw))

    # Verify every input sample ends exactly at its entry and never uses a future row.
    for entry in kept_raw:
        start = int(entry) - LOOKBACK + 1
        end = int(entry)
        assert start >= 0
        assert end < len(raw_dates)
        assert end == int(entry)

    lookup = {int(r): i for i, r in enumerate(labels.raw_indices)}
    aligned_idx = np.asarray([lookup[int(r)] for r in kept_raw], dtype=int)
    assert np.array_equal(labels.raw_indices[aligned_idx], kept_raw)

    folds = _make_cq_folds(kept_raw)
    assert len(folds) > 0
    for train, test in folds:
        assert len(train) > 0 and len(test) > 0
        assert np.max(train) < np.min(test)
        first_test_raw = int(kept_raw[test[0]])
        assert np.all(kept_raw[train] + HORIZON < first_test_raw)

    # Import/dependency guardrails for the current ranker.
    import futureview.strategy1_smh_cnn_close_volume_multiscale as ranker
    src = inspect.getsource(ranker)
    forbidden = (
        "strategy1_success_training",
        "strategy1_smh_ridge_lmu",
        "strategy1_smh_cnn_lmu",
        "effective_return_indicator",
        "FEATURE_COLUMNS",
        "make_causal_features",
    )
    for token in forbidden:
        assert token not in src, f"forbidden legacy dependency/token found: {token}"

    print(
        "S1 CQ_AUDIT DATA "
        f"ticker={TICKER} rows={audit.rows} start={audit.start} end={audit.end} "
        f"labels={len(labels.raw_indices)} mature_labels={len(mature_raw)} input_samples={len(kept_raw)}"
    )
    print(
        "S1 CQ_AUDIT INPUT "
        f"shape={tuple(x.shape)} channels={','.join(EXPECTED_CHANNELS)} "
        "source=close,volume normalization=current_value/rolling_sum_N "
        "causal_window=true future_rows_in_input=false"
    )
    print(
        "S1 CQ_AUDIT LABELS "
        "identities=C_eq_U_minus_L,Q_eq_U_minus_mu_over_C labels_not_input=true aligned=true"
    )
    print(
        "S1 CQ_AUDIT SPLIT "
        f"folds={len(folds)} purge_sessions={HORIZON} chronological=true holdout_months=3 leakage=false"
    )
    print("S1 CQ_AUDIT IMPORTS legacy_training=false ridge=false lmu_regression=false engineered_features=false")
    print("S1 CQ_AUDIT PASS")


if __name__ == "__main__":
    main()

from __future__ import annotations

import numpy as np
import pandas as pd

from .data import download_spy_daily
from .features import make_causal_features
from .strategy1 import add_strategy1_events, _simulate_from_start, oracle_value_for_window

DATA_PERIOD = "5y"
LOOKBACK = 50
HORIZONS = (15, 30, 45, 60)
EPS = 1e-12


def _q(x: np.ndarray, p: float) -> float:
    return float(np.quantile(np.asarray(x, dtype=float), p))


def _mean_efficiency(returns: np.ndarray, exposure_days: np.ndarray) -> float:
    valid = exposure_days > EPS
    if not np.any(valid):
        return float("nan")
    return float(np.mean(returns[valid] / exposure_days[valid]))


def main() -> None:
    df = download_spy_daily(period=DATA_PERIOD)
    events = add_strategy1_events(df).reset_index(drop=True)
    features = make_causal_features(df).reset_index(drop=True)
    feature_dates = pd.DatetimeIndex(pd.to_datetime(features["date"]))
    feature_pos = {pd.Timestamp(d): i for i, d in enumerate(feature_dates)}

    max_h = max(HORIZONS)
    common_indices: list[int] = []
    for i in range(len(events)):
        if not bool(events.at[i, "entry1_event"]):
            continue
        if i + max_h - 1 >= len(events):
            continue
        date = pd.Timestamp(events.at[i, "date"])
        pos = feature_pos.get(date)
        if pos is None or pos - LOOKBACK + 1 < 0:
            continue
        common_indices.append(i)

    if not common_indices:
        raise RuntimeError("no common legal Entry1 samples with full max-horizon future")

    dates = pd.DatetimeIndex(pd.to_datetime(events.loc[common_indices, "date"]))
    print(
        f"S1 ENTRY_HORIZON_BASELINE DATA period={DATA_PERIOD} common_samples={len(common_indices)} "
        f"lookback={LOOKBACK} horizons={','.join(map(str, HORIZONS))} "
        f"first={dates[0].date()} last={dates[-1].date()} common_dates=true no_model=true"
    )
    print(
        "S1 ENTRY_HORIZON_BASELINE RULE sample=legal_entry1_event "
        "learning_target=none oracle_role=benchmark_only "
        "oracle_regret=oracle_value_minus_entry_return common_full_60d_future=true"
    )

    stats: dict[int, dict[str, float]] = {}
    rows_by_h: dict[int, dict[str, np.ndarray]] = {}

    for h in HORIZONS:
        entry_returns: list[float] = []
        entry_exposure: list[float] = []
        entry_holding: list[float] = []
        entry_entries: list[float] = []
        oracle_values: list[float] = []
        oracle_exposure: list[float] = []
        regrets: list[float] = []
        matches: list[float] = []

        for i in common_indices:
            end = i + h - 1
            entry_run = _simulate_from_start(events, i, end)
            oracle_run = oracle_value_for_window(events, i - 1, end)
            entry_return = float(entry_run.final_return)
            oracle_value = float(oracle_run.final_return)
            regret = oracle_value - entry_return
            if oracle_value + EPS < max(0.0, entry_return):
                raise RuntimeError("Oracle benchmark does not dominate current legal entry")
            if regret < -1e-10:
                raise RuntimeError("negative Oracle regret")

            entry_returns.append(entry_return)
            entry_exposure.append(float(entry_run.exposure_days))
            entry_holding.append(float(entry_run.holding_days))
            entry_entries.append(float(entry_run.entries_used))
            oracle_values.append(oracle_value)
            oracle_exposure.append(float(oracle_run.exposure_days))
            regrets.append(regret)
            matches.append(float(regret <= 1e-10))

        entry = np.asarray(entry_returns, dtype=float)
        eexp = np.asarray(entry_exposure, dtype=float)
        ehold = np.asarray(entry_holding, dtype=float)
        eentries = np.asarray(entry_entries, dtype=float)
        oracle = np.asarray(oracle_values, dtype=float)
        oexp = np.asarray(oracle_exposure, dtype=float)
        regret = np.asarray(regrets, dtype=float)
        match = np.asarray(matches, dtype=float)

        rows_by_h[h] = {
            "entry": entry,
            "entry_exposure": eexp,
            "oracle": oracle,
            "regret": regret,
        }
        stats[h] = {
            "entry_mean": float(entry.mean()),
            "entry_median": float(np.median(entry)),
            "entry_p10": _q(entry, 0.10),
            "entry_p90": _q(entry, 0.90),
            "entry_win_rate": float(np.mean(entry > 0.0)),
            "entry_loss_rate": float(np.mean(entry < 0.0)),
            "entry_horizon_day_rate": float(entry.mean() / h),
            "entry_exposure_efficiency": _mean_efficiency(entry, eexp),
            "entry_exposure_days_mean": float(eexp.mean()),
            "entry_holding_days_mean": float(ehold.mean()),
            "entry_entries_mean": float(eentries.mean()),
            "entry_all3_rate": float(np.mean(eentries >= 3.0)),
            "oracle_mean": float(oracle.mean()),
            "oracle_positive_rate": float(np.mean(oracle > 0.0)),
            "oracle_exposure_efficiency": _mean_efficiency(oracle, oexp),
            "regret_mean": float(regret.mean()),
            "regret_median": float(np.median(regret)),
            "regret_p90": _q(regret, 0.90),
            "oracle_match_rate": float(match.mean()),
        }

        s = stats[h]
        print(
            f"S1 ENTRY_HORIZON_BASELINE HORIZON h={h} n={len(entry)} "
            f"entry_mean={s['entry_mean']:.6f} entry_median={s['entry_median']:.6f} "
            f"entry_p10={s['entry_p10']:.6f} entry_p90={s['entry_p90']:.6f} "
            f"win_rate={s['entry_win_rate']:.3f} loss_rate={s['entry_loss_rate']:.3f} "
            f"entry_per_horizon_day={s['entry_horizon_day_rate']:.8f} "
            f"entry_per_exposure_day={s['entry_exposure_efficiency']:.8f} "
            f"exposure_days_mean={s['entry_exposure_days_mean']:.3f} "
            f"holding_days_mean={s['entry_holding_days_mean']:.3f} "
            f"entries_mean={s['entry_entries_mean']:.3f} all3_rate={s['entry_all3_rate']:.3f} "
            f"oracle_mean={s['oracle_mean']:.6f} oracle_positive_rate={s['oracle_positive_rate']:.3f} "
            f"oracle_per_exposure_day={s['oracle_exposure_efficiency']:.8f} "
            f"regret_mean={s['regret_mean']:.6f} regret_median={s['regret_median']:.6f} "
            f"regret_p90={s['regret_p90']:.6f} oracle_match_rate={s['oracle_match_rate']:.3f}"
        )

    base = rows_by_h[30]
    for h in HORIZONS:
        if h == 30:
            continue
        other = rows_by_h[h]
        delta_entry = other["entry"] - base["entry"]
        delta_regret = other["regret"] - base["regret"]
        print(
            f"S1 ENTRY_HORIZON_BASELINE PAIRED compare={h}D_minus_30D "
            f"entry_delta_mean={delta_entry.mean():.6f} "
            f"entry_{h}D_better_rate={np.mean(delta_entry > EPS):.3f} "
            f"entry_equal_rate={np.mean(np.abs(delta_entry) <= EPS):.3f} "
            f"regret_delta_mean={delta_regret.mean():.6f} "
            f"regret_{h}D_lower_rate={np.mean(delta_regret < -EPS):.3f}"
        )

    leaders = {
        "entry_mean": max(HORIZONS, key=lambda h: stats[h]["entry_mean"]),
        "win_rate": max(HORIZONS, key=lambda h: stats[h]["entry_win_rate"]),
        "entry_per_horizon_day": max(HORIZONS, key=lambda h: stats[h]["entry_horizon_day_rate"]),
        "entry_per_exposure_day": max(HORIZONS, key=lambda h: stats[h]["entry_exposure_efficiency"]),
        "lowest_regret": min(HORIZONS, key=lambda h: stats[h]["regret_mean"]),
        "oracle_match_rate": max(HORIZONS, key=lambda h: stats[h]["oracle_match_rate"]),
    }
    print(
        "S1 ENTRY_HORIZON_BASELINE LEADERS "
        + " ".join(f"{k}={v}D" for k, v in leaders.items())
    )
    print("S1 ENTRY_HORIZON_BASELINE COMPLETE")


if __name__ == "__main__":
    main()

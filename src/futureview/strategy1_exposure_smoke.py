from __future__ import annotations

import numpy as np

from .data import download_spy_daily
from .strategy1 import STRATEGY1_HORIZONS, make_strategy1_oracle_labels


def main() -> None:
    df = download_spy_daily(period="3y")
    labels = make_strategy1_oracle_labels(df)
    if labels.empty:
        raise RuntimeError("Strategy 1 Oracle exposure labels are empty")

    for h in STRATEGY1_HORIZONS:
        values = labels[f"oracle_value_{h}"].to_numpy(dtype=float)
        exposure = labels[f"oracle_exposure_days_{h}"].to_numpy(dtype=float)
        holding = labels[f"oracle_holding_days_{h}"].to_numpy(dtype=int)
        efficiency = labels[f"oracle_return_per_exposure_day_{h}"].to_numpy(dtype=float)
        campaigns = labels[f"oracle_campaigns_{h}"].to_numpy(dtype=int)

        if not np.isfinite(values).all() or not np.isfinite(exposure).all() or not np.isfinite(efficiency).all():
            raise RuntimeError(f"Non-finite Strategy 1 exposure metric for {h}D")
        if (exposure < -1e-12).any() or (exposure > h + 1e-12).any():
            raise RuntimeError(f"Exposure days outside [0, horizon] for {h}D")
        if (holding < 0).any() or (holding > h).any():
            raise RuntimeError(f"Holding days outside [0, horizon] for {h}D")
        if (exposure - holding > 1e-12).any():
            raise RuntimeError(f"Capital-weighted exposure exceeds holding days for {h}D")

        no_trade = campaigns == 0
        if (np.abs(exposure[no_trade]) > 1e-12).any():
            raise RuntimeError(f"No-trade case has exposure for {h}D")
        if (holding[no_trade] != 0).any():
            raise RuntimeError(f"No-trade case has holding days for {h}D")
        if (np.abs(efficiency[no_trade]) > 1e-12).any():
            raise RuntimeError(f"No-trade case has non-zero efficiency for {h}D")

        traded = campaigns > 0
        positive = values > 0.0
        if positive.any() and (exposure[positive] <= 0.0).any():
            raise RuntimeError(f"Positive Oracle Value without exposure for {h}D")
        if positive.any() and not np.allclose(
            efficiency[positive], values[positive] / exposure[positive], rtol=1e-10, atol=1e-12
        ):
            raise RuntimeError(f"Exposure efficiency identity failed for {h}D")

        traded_n = int(traded.sum())
        positive_n = int(positive.sum())
        print(
            f"STRATEGY1 EXPOSURE {h}D n={len(values)} traded={traded_n} positive={positive_n} "
            f"oracle_mean={values.mean():.6f} "
            f"exposure_days_mean_all={exposure.mean():.6f} "
            f"holding_days_mean_all={holding.mean():.6f} "
            f"return_per_exposure_day_mean_all={efficiency.mean():.6f}"
        )
        if traded_n:
            print(
                f"STRATEGY1 EXPOSURE_CONDITIONAL {h}D "
                f"oracle_mean={values[traded].mean():.6f} "
                f"exposure_days_mean={exposure[traded].mean():.6f} "
                f"holding_days_mean={holding[traded].mean():.6f} "
                f"return_per_exposure_day_mean={efficiency[traded].mean():.6f} "
                f"median={np.median(efficiency[traded]):.6f} "
                f"p90={np.quantile(efficiency[traded], 0.90):.6f}"
            )

    print("STRATEGY1 EXPOSURE SMOKE PASS")


if __name__ == "__main__":
    main()

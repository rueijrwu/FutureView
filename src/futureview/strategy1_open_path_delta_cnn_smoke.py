from __future__ import annotations

import os

import numpy as np
import pandas as pd
import torch
from torch import nn

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import (
    MERGE_GAP,
    build_deterministic_path_table,
    build_extrema_sets,
    preprocess_legal_points,
)
from .strategy1_deterministic_paths_asof import simulate_deterministic_path_asof

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
LOOKBACK = int(os.environ.get("FUTUREVIEW_LOOKBACK", "30"))
SNAPSHOT_STRIDE = int(os.environ.get("FUTUREVIEW_SNAPSHOT_STRIDE", "5"))
EPOCHS = int(os.environ.get("FUTUREVIEW_EPOCHS", "160"))
MIN_TRAIN = int(os.environ.get("FUTUREVIEW_MIN_TRAIN", "120"))
MIN_VALID = int(os.environ.get("FUTUREVIEW_MIN_VALID", "30"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260904"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-open-path-delta-cnn-smoke.csv")


class DeltaCNN(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv1d(2, 12, kernel_size=5, padding=2),
            nn.GELU(),
            nn.Conv1d(12, 20, kernel_size=5, padding=2),
            nn.GELU(),
            nn.AdaptiveAvgPool1d(1),
            nn.Flatten(),
            nn.Linear(20, 16),
            nn.GELU(),
            nn.Linear(16, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


def _norm_window(df: pd.DataFrame, end: int) -> np.ndarray | None:
    start = end - LOOKBACK + 1
    if start < 0:
        return None
    close = df.loc[start:end, "close"].to_numpy(dtype=np.float64)
    volume = df.loc[start:end, "volume"].to_numpy(dtype=np.float64)
    if len(close) != LOOKBACK or not np.all(np.isfinite(close)) or np.any(close <= 0):
        return None
    if not np.all(np.isfinite(volume)) or np.any(volume <= 0):
        return None
    p = np.log(close) - np.log(close[-1])
    lv = np.log(volume)
    sd = float(lv.std())
    v = (lv - float(lv.mean())) / (sd if sd > 1e-12 else 1.0)
    return np.stack([p, v], axis=0).astype(np.float32)


def _final_exit_index(r: pd.Series) -> int:
    x10 = int(r.exit10_index)
    return x10 if x10 >= 0 else int(r.horizon_exit_index)


def build_snapshots(df: pd.DataFrame, events: pd.DataFrame) -> tuple[np.ndarray, pd.DataFrame]:
    final_paths = build_deterministic_path_table(events)
    rows: list[dict[str, object]] = []
    xs: list[np.ndarray] = []

    # Cache prefix preparation by cutoff because many entries share the same cutoff.
    prefix_cache: dict[int, tuple[pd.DataFrame, np.ndarray, np.ndarray]] = {}

    for fr in final_paths.itertuples(index=False):
        entry = int(fr.entry_index)
        final_exit = int(fr.exit10_index) if int(fr.exit10_index) >= 0 else int(fr.horizon_exit_index)
        final_r = float(fr.campaign_return)
        first_cut = max(entry + 5, LOOKBACK - 1)
        if final_exit <= first_cut:
            continue

        for cutoff in range(first_cut, final_exit, SNAPSHOT_STRIDE):
            x = _norm_window(df, cutoff)
            if x is None:
                continue
            if cutoff not in prefix_cache:
                prefix = events.iloc[: cutoff + 1].copy().reset_index(drop=True)
                prepared = preprocess_legal_points(prefix, gap=MERGE_GAP)
                mins, maxs = build_extrema_sets(prepared)
                prefix_cache[cutoff] = (prepared, mins, maxs)
            prepared, mins, maxs = prefix_cache[cutoff]
            if entry >= len(prepared) or not bool(prepared.at[entry, "entry_candidate"]):
                continue
            ap = simulate_deterministic_path_asof(
                prepared,
                entry,
                mins,
                maxs,
                asof_index=cutoff,
            )
            if ap is None or int(ap.forced_asof_exit_index) < 0:
                continue
            asof_r = float(ap.campaign_return)
            xs.append(x)
            rows.append(
                {
                    "entry_index": entry,
                    "cutoff_index": cutoff,
                    "cutoff_date": pd.Timestamp(df.at[cutoff, "date"]).date().isoformat(),
                    "final_exit_index": final_exit,
                    "asof_return": asof_r,
                    "final_return": final_r,
                    "delta_return": final_r - asof_r,
                    "age": cutoff - entry,
                }
            )

    if not rows:
        raise RuntimeError("no open-path snapshots produced")
    return np.stack(xs), pd.DataFrame(rows)


def _train(x: torch.Tensor, y: torch.Tensor) -> DeltaCNN:
    model = DeltaCNN()
    opt = torch.optim.AdamW(model.parameters(), lr=0.003, weight_decay=1e-4)
    loss_fn = nn.SmoothL1Loss()
    for _ in range(EPOCHS):
        model.train()
        opt.zero_grad(set_to_none=True)
        pred = model(x)
        loss = loss_fn(pred, y)
        loss.backward()
        opt.step()
    return model


def _safe_corr(a: pd.Series, b: pd.Series, method: str) -> float:
    z = pd.DataFrame({"a": a, "b": b}).dropna()
    if len(z) < 3 or z.a.nunique() < 2 or z.b.nunique() < 2:
        return float("nan")
    return float(z.a.corr(z.b, method=method))


def _bucket(s: pd.Series) -> pd.Series:
    q20, q80 = s.quantile([0.2, 0.8]).tolist()
    return pd.Series(
        np.where(s <= q20, "bottom20", np.where(s >= q80, "top20", "middle60")),
        index=s.index,
    )


def main() -> None:
    if LOOKBACK != 30:
        raise ValueError("exploratory smoke test is locked to 30-session normalized price/volume")
    torch.set_num_threads(2)
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    audit = validate_daily_ohlcv(df, minimum_rows=1800)
    events = add_strategy1_events(df).reset_index(drop=True)
    x_np, rows = build_snapshots(df, events)
    rows["year"] = pd.to_datetime(rows.cutoff_date).dt.year.astype(int)
    x_all = torch.from_numpy(x_np)
    y_all = torch.from_numpy(rows.delta_return.to_numpy(dtype=np.float32))

    outputs: list[pd.DataFrame] = []
    years: list[int] = []
    for year in sorted(rows.year.unique()):
        tr = rows.year < year
        va = rows.year == year
        ntr, nva = int(tr.sum()), int(va.sum())
        if ntr < MIN_TRAIN or nva < MIN_VALID:
            continue
        years.append(int(year))
        np.random.seed(SEED)
        torch.manual_seed(SEED)
        model = _train(x_all[torch.from_numpy(tr.to_numpy(copy=True))], y_all[torch.from_numpy(tr.to_numpy(copy=True))])
        model.eval()
        with torch.no_grad():
            pred_delta = model(x_all[torch.from_numpy(va.to_numpy(copy=True))]).numpy()
        fold = rows.loc[va].copy().reset_index(drop=True)
        fold["pred_delta"] = pred_delta
        fold["pred_final_return"] = fold.asof_return + fold.pred_delta
        fold["baseline_abs_err"] = np.abs(fold.final_return - fold.asof_return)
        fold["model_abs_err"] = np.abs(fold.final_return - fold.pred_final_return)
        fold["bucket_pred_delta"] = _bucket(fold.pred_delta)
        outputs.append(fold)

        print(
            f"S1 OPDCNN FOLD year={year} train={ntr} valid={nva} "
            f"delta_spearman={_safe_corr(fold.delta_return,fold.pred_delta,'spearman'):.6f} "
            f"final_spearman={_safe_corr(fold.final_return,fold.pred_final_return,'spearman'):.6f} "
            f"baseline_mae={fold.baseline_abs_err.mean():.6f} model_mae={fold.model_abs_err.mean():.6f}"
        )

    if not outputs:
        raise RuntimeError("no eligible chronological folds")
    out = pd.concat(outputs, ignore_index=True)
    out.to_csv(OUTPUT, index=False)

    bmae = float(out.baseline_abs_err.mean())
    mmae = float(out.model_abs_err.mean())
    improvement = (bmae - mmae) / bmae if bmae > 0 else float("nan")
    print(
        f"S1 OPDCNN START ticker={TICKER} rows={audit.rows} snapshots={len(rows)} "
        f"entries={rows.entry_index.nunique()} oos={len(out)} years={','.join(map(str,years))} epochs={EPOCHS}"
    )
    print(
        f"S1 OPDCNN POOLED delta_pearson={_safe_corr(out.delta_return,out.pred_delta,'pearson'):.6f} "
        f"delta_spearman={_safe_corr(out.delta_return,out.pred_delta,'spearman'):.6f} "
        f"final_pearson={_safe_corr(out.final_return,out.pred_final_return,'pearson'):.6f} "
        f"final_spearman={_safe_corr(out.final_return,out.pred_final_return,'spearman'):.6f} "
        f"baseline_mae={bmae:.6f} model_mae={mmae:.6f} mae_improvement={improvement:.6f}"
    )
    for bucket in ("bottom20", "middle60", "top20"):
        g = out.loc[out.bucket_pred_delta == bucket]
        print(
            f"S1 OPDCNN BUCKET bucket={bucket} n={len(g)} "
            f"actual_delta_mean={g.delta_return.mean():.6f} actual_delta_median={g.delta_return.median():.6f} "
            f"final_return_mean={g.final_return.mean():.6f} p_final_positive={(g.final_return>0).mean():.6f}"
        )
    print(f"S1 OPDCNN OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 OPDCNN COMPLETE")


if __name__ == "__main__":
    main()

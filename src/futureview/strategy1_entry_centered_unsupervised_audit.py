from __future__ import annotations

import os

import numpy as np
import pandas as pd
import torch
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from torch import nn

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import build_representation_a_table
from .strategy1_layer2_centered_train import _feature_series

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
EPOCHS = int(os.environ.get("FUTUREVIEW_EPOCHS", "300"))
LR = float(os.environ.get("FUTUREVIEW_LR", "0.001"))
LATENT = int(os.environ.get("FUTUREVIEW_LATENT", "8"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-entry-centered-unsupervised-audit.csv")
EPS = 1e-12


class AutoEncoder(nn.Module):
    def __init__(self, dim: int, latent: int) -> None:
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(dim, 64),
            nn.GELU(),
            nn.Linear(64, 24),
            nn.GELU(),
            nn.Linear(24, latent),
        )
        self.decoder = nn.Sequential(
            nn.Linear(latent, 24),
            nn.GELU(),
            nn.Linear(24, 64),
            nn.GELU(),
            nn.Linear(64, dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.decoder(self.encoder(x))


def build_samples() -> tuple[pd.DataFrame, np.ndarray]:
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    windows = build_representation_a_table(
        df,
        paths,
        window=2 * W,
        stride=1,
        random_samples=20,
        random_seed=SEED,
    )
    by_start = windows.set_index("start_index")
    ret_by_entry = paths.set_index("entry_index")["campaign_return"]
    feats = _feature_series(df)

    rows: list[dict[str, float | int | str]] = []
    xs: list[np.ndarray] = []
    for t in paths["entry_index"].astype(int).to_numpy():
        s, e = t - W + 1, t + W
        if s < 0 or e >= len(df) or s not in by_start.index:
            continue
        x = feats[s : t + 1].T
        if x.shape != (8, W) or not np.isfinite(x).all():
            continue
        wr = by_start.loc[s]
        if isinstance(wr, pd.DataFrame):
            wr = wr.iloc[0]
        u = float(wr.U)
        pe = float(ret_by_entry.loc[t])
        q = u - pe
        if q < -EPS:
            raise RuntimeError(f"Q invariant violated entry={t} U={u} E={pe} Q={q}")
        if abs(q) <= EPS:
            q = 0.0
        rows.append(
            {
                "entry_index": int(t),
                "entry_date": str(pd.Timestamp(df.loc[t, "date"]).date()),
                "C": float(u - wr.B_periodic),
                "Q": float(q),
            }
        )
        xs.append(x.reshape(-1).astype(np.float32))

    out = pd.DataFrame(rows).sort_values("entry_index").reset_index(drop=True)
    x = np.stack(xs)
    print(
        f"S1 UREP START ticker={TICKER} rows={audit.rows} first={audit.start} last={audit.end} "
        f"W={W} samples={len(out)} input_dim={x.shape[1]} latent={LATENT}"
    )
    return out, x


def main() -> None:
    if W != 30:
        raise ValueError("unsupervised Entry-centered audit locked to W=30")

    np.random.seed(SEED)
    torch.manual_seed(SEED)
    out, x = build_samples()

    # IMPORTANT: C/Q are not used anywhere in representation learning.
    # Standardization is based on causal Entry-time features only.
    mu = x.mean(axis=0, keepdims=True)
    sd = x.std(axis=0, keepdims=True)
    sd[sd < 1e-8] = 1.0
    xn = ((x - mu) / sd).astype(np.float32)

    device = torch.device("cpu")
    model = AutoEncoder(xn.shape[1], LATENT).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    loss_fn = nn.MSELoss()
    xt = torch.from_numpy(xn).to(device)
    for epoch in range(EPOCHS):
        model.train()
        pred = model(xt)
        loss = loss_fn(pred, xt)
        opt.zero_grad()
        loss.backward()
        opt.step()
        if epoch in (0, EPOCHS - 1):
            print(f"S1 UREP AE epoch={epoch+1} reconstruction_mse={float(loss.detach().cpu()):.6f}")

    model.eval()
    with torch.no_grad():
        z = model.encoder(xt).cpu().numpy()

    c, q = out.C, out.Q
    c40, c60 = float(c.quantile(.40)), float(c.quantile(.60))
    q40, q60 = float(q.quantile(.40)), float(q.quantile(.60))
    out["cq_label"] = "neutral"
    out.loc[(c >= c60) & (q <= q40), "cq_label"] = "good"
    out.loc[(c <= c40) & (q >= q60), "cq_label"] = "bad"

    print(
        f"S1 UREP POSTHOC thresholds C40={c40:.6f} C60={c60:.6f} Q40={q40:.6f} Q60={q60:.6f} "
        f"good={(out.cq_label=='good').sum()} bad={(out.cq_label=='bad').sum()} neutral={(out.cq_label=='neutral').sum()}"
    )

    best_sep = None
    best_sep_score = -np.inf
    for k in (3, 4, 5, 6):
        km = KMeans(n_clusters=k, random_state=SEED, n_init=50)
        labels = km.fit_predict(z)
        sil = float(silhouette_score(z, labels)) if len(np.unique(labels)) > 1 else float("nan")
        out[f"cluster_k{k}"] = labels
        print(f"S1 UREP KMEANS k={k} silhouette={sil:.6f}")
        stats = []
        for cl in range(k):
            g = out.loc[labels == cl]
            n = len(g)
            good_rate = float((g.cq_label == "good").mean())
            bad_rate = float((g.cq_label == "bad").mean())
            neutral_rate = float((g.cq_label == "neutral").mean())
            stats.append((cl, n, float(g.C.mean()), float(g.Q.mean()), good_rate, bad_rate))
            print(
                f"S1 UREP CLUSTER k={k} cluster={cl} n={n} "
                f"C_mean={g.C.mean():.6f} C_median={g.C.median():.6f} "
                f"Q_mean={g.Q.mean():.6f} Q_median={g.Q.median():.6f} "
                f"good_rate={good_rate:.6f} bad_rate={bad_rate:.6f} neutral_rate={neutral_rate:.6f}"
            )

        # Post-hoc separation audit only; not a training objective.
        best_good = max(stats, key=lambda r: (r[4], r[2], -r[3]))
        best_bad = max(stats, key=lambda r: (r[5], -r[2], r[3]))
        sep_score = best_good[4] + best_bad[5]
        print(
            f"S1 UREP SEPARATION k={k} favorable_cluster={best_good[0]} favorable_n={best_good[1]} "
            f"favorable_good_rate={best_good[4]:.6f} favorable_C_mean={best_good[2]:.6f} favorable_Q_mean={best_good[3]:.6f} "
            f"unfavorable_cluster={best_bad[0]} unfavorable_n={best_bad[1]} unfavorable_bad_rate={best_bad[5]:.6f} "
            f"unfavorable_C_mean={best_bad[2]:.6f} unfavorable_Q_mean={best_bad[3]:.6f}"
        )
        if sep_score > best_sep_score:
            best_sep_score = sep_score
            best_sep = k

    for j in range(z.shape[1]):
        out[f"z{j}"] = z[:, j]
    out.to_csv(OUTPUT, index=False)
    print(f"S1 UREP BEST_POSTHOC k={best_sep} score={best_sep_score:.6f}")
    print(f"S1 UREP OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 UREP COMPLETE labels_used_in_training=false cq_used_posthoc_only=true")


if __name__ == "__main__":
    main()

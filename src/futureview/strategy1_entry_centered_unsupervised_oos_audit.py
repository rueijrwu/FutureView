from __future__ import annotations

import os

import numpy as np
import torch
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from torch import nn

from .strategy1_entry_centered_unsupervised_audit import AutoEncoder, build_samples

SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
EPOCHS = int(os.environ.get("FUTUREVIEW_EPOCHS", "300"))
LR = float(os.environ.get("FUTUREVIEW_LR", "0.001"))
LATENT = int(os.environ.get("FUTUREVIEW_LATENT", "8"))
TRAIN_FRAC = float(os.environ.get("FUTUREVIEW_TRAIN_FRAC", "0.70"))
W = int(os.environ.get("FUTUREVIEW_W", "30"))


def _label(c: np.ndarray, q: np.ndarray, c40: float, c60: float, q40: float, q60: float) -> np.ndarray:
    y = np.full(len(c), "neutral", dtype="U7")
    y[(c >= c60) & (q <= q40)] = "good"
    y[(c <= c40) & (q >= q60)] = "bad"
    return y


def _rates(y: np.ndarray) -> tuple[float, float, float]:
    return float(np.mean(y == "good")), float(np.mean(y == "bad")), float(np.mean(y == "neutral"))


def main() -> None:
    if W != 30:
        raise ValueError("OOS unsupervised audit locked to W=30")
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    out, x = build_samples()
    idx = out.entry_index.to_numpy(dtype=int)
    n = len(out)
    nominal = int(n * TRAIN_FRAC)
    cut = int(idx[nominal])
    train_mask = (idx + W) < cut  # every train centered label is fully mature before first OOS Entry
    test_mask = idx >= cut
    if train_mask.sum() < 50 or test_mask.sum() < 20:
        raise RuntimeError(f"split too small train={train_mask.sum()} test={test_mask.sum()}")

    xtr, xte = x[train_mask], x[test_mask]
    mu = xtr.mean(axis=0, keepdims=True)
    sd = xtr.std(axis=0, keepdims=True)
    sd[sd < 1e-8] = 1.0
    xtrn = ((xtr - mu) / sd).astype(np.float32)
    xten = ((xte - mu) / sd).astype(np.float32)

    model = AutoEncoder(x.shape[1], LATENT)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    loss_fn = nn.MSELoss()
    xt = torch.from_numpy(xtrn)
    for epoch in range(EPOCHS):
        model.train()
        pred = model(xt)
        loss = loss_fn(pred, xt)
        opt.zero_grad(); loss.backward(); opt.step()
        if epoch in (0, EPOCHS - 1):
            print(f"S1 UOOS AE epoch={epoch+1} train_reconstruction_mse={float(loss.detach()):.6f}")

    model.eval()
    with torch.no_grad():
        ztr = model.encoder(torch.from_numpy(xtrn)).numpy()
        zte = model.encoder(torch.from_numpy(xten)).numpy()

    # Choose K from TRAIN geometry only. C/Q do not choose K or train the representation.
    candidates = []
    kms = {}
    for k in (3, 4, 5, 6):
        km = KMeans(n_clusters=k, random_state=SEED, n_init=50).fit(ztr)
        sil = float(silhouette_score(ztr, km.labels_))
        candidates.append((sil, -k, k)); kms[k] = km
        print(f"S1 UOOS TRAIN_GEOMETRY k={k} silhouette={sil:.6f}")
    k = max(candidates)[2]
    km = kms[k]
    tr_cluster = km.labels_
    te_cluster = km.predict(zte)

    tr = out.loc[train_mask].reset_index(drop=True)
    te = out.loc[test_mask].reset_index(drop=True)
    c40, c60 = float(tr.C.quantile(.40)), float(tr.C.quantile(.60))
    q40, q60 = float(tr.Q.quantile(.40)), float(tr.Q.quantile(.60))
    ytr = _label(tr.C.to_numpy(), tr.Q.to_numpy(), c40, c60, q40, q60)
    yte = _label(te.C.to_numpy(), te.Q.to_numpy(), c40, c60, q40, q60)

    # Historical C/Q are used only now to name frozen TRAIN clusters.
    stats = []
    for cl in range(k):
        m = tr_cluster == cl
        g, b, neu = _rates(ytr[m])
        stats.append((cl, int(m.sum()), g, b, float(tr.C.to_numpy()[m].mean()), float(tr.Q.to_numpy()[m].mean())))
        print(f"S1 UOOS TRAIN_CLUSTER cluster={cl} n={m.sum()} good_rate={g:.6f} bad_rate={b:.6f} neutral_rate={neu:.6f} C_mean={tr.C.to_numpy()[m].mean():.6f} Q_mean={tr.Q.to_numpy()[m].mean():.6f}")
    favorable = max(stats, key=lambda r: (r[2], r[4], -r[5]))[0]
    unfavorable = max(stats, key=lambda r: (r[3], -r[4], r[5]))[0]

    base_g, base_b, base_n = _rates(yte)
    print(f"S1 UOOS SPLIT cut_entry={cut} train={len(tr)} test={len(te)} embargo={W} train_last={tr.entry_date.iloc[-1]} test_first={te.entry_date.iloc[0]}")
    print(f"S1 UOOS TRAIN_THRESH C40={c40:.6f} C60={c60:.6f} Q40={q40:.6f} Q60={q60:.6f} chosen_k={k} favorable_cluster={favorable} unfavorable_cluster={unfavorable}")
    print(f"S1 UOOS TEST_BASE n={len(te)} good_rate={base_g:.6f} bad_rate={base_b:.6f} neutral_rate={base_n:.6f} C_mean={te.C.mean():.6f} Q_mean={te.Q.mean():.6f}")
    for role, cl in (("favorable", favorable), ("unfavorable", unfavorable)):
        m = te_cluster == cl
        if not m.any():
            print(f"S1 UOOS TEST_ROLE role={role} cluster={cl} n=0")
            continue
        g, b, neu = _rates(yte[m])
        print(f"S1 UOOS TEST_ROLE role={role} cluster={cl} n={m.sum()} good_rate={g:.6f} bad_rate={b:.6f} neutral_rate={neu:.6f} C_mean={te.C.to_numpy()[m].mean():.6f} Q_mean={te.Q.to_numpy()[m].mean():.6f} good_lift={(g/base_g if base_g>0 else float('nan')):.6f} bad_lift={(b/base_b if base_b>0 else float('nan')):.6f}")

    print("S1 UOOS COMPLETE scaler_train_only=true ae_train_only=true k_train_geometry_only=true centroids_frozen=true train_cq_names_clusters_only=true test_cq_audit_only=true")


if __name__ == "__main__":
    main()

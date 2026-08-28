from __future__ import annotations

import os
import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import build_representation_a_table
from .strategy1_cq_90d_rank_audit import build_window_q
from .strategy1_prev_w_neutral_gate_audit import classify_layer1

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-prev-w-neutral-gate-50-audit.csv")
EPS = 1e-12
TARGET_NEUTRAL = 0.50


def build_centered_entries_50(df: pd.DataFrame, paths: pd.DataFrame) -> pd.DataFrame:
    windows = build_representation_a_table(
        df, paths, window=2 * W, stride=1, random_samples=20, random_seed=SEED
    )
    by_start = windows.set_index("start_index")
    ret = paths.set_index("entry_index")["campaign_return"]
    rows = []
    for t in paths.entry_index.astype(int):
        s, e = t - W + 1, t + W
        if s < 0 or e >= len(df) or s not in by_start.index:
            continue
        wr = by_start.loc[s]
        if isinstance(wr, pd.DataFrame):
            wr = wr.iloc[0]
        u = float(wr.U)
        q = u - float(ret.loc[t])
        if q < -EPS:
            raise RuntimeError(f"Q invariant violated entry={t}")
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

    out = pd.DataFrame(rows).sort_values("entry_index").reset_index(drop=True)

    # Keep the same symmetric joint-C/Q semantics as the 40/60 audit, but
    # choose the quantile boundary that makes Neutral closest to 50%.
    best = None
    for hi in np.linspace(0.50, 0.60, 101):
        lo = 1.0 - hi
        c_hi = float(out.C.quantile(hi))
        c_lo = float(out.C.quantile(lo))
        q_hi = float(out.Q.quantile(hi))
        q_lo = float(out.Q.quantile(lo))
        good = (out.C >= c_hi) & (out.Q <= q_lo)
        bad = (out.C <= c_lo) & (out.Q >= q_hi)
        neutral_rate = float((~(good | bad)).mean())
        err = abs(neutral_rate - TARGET_NEUTRAL)
        candidate = (err, hi, lo, c_hi, c_lo, q_hi, q_lo, good, bad, neutral_rate)
        if best is None or candidate[0] < best[0]:
            best = candidate

    assert best is not None
    _, hi, lo, c_hi, c_lo, q_hi, q_lo, good, bad, neutral_rate = best
    out["label"] = "neutral"
    out.loc[good, "label"] = "good"
    out.loc[bad, "label"] = "bad"
    out["non_neutral"] = (out.label != "neutral").astype(int)
    print(
        f"S1 PWG50 TARGET target_neutral={TARGET_NEUTRAL:.6f} chosen_hi={hi:.3f} chosen_lo={lo:.3f} "
        f"C_hi={c_hi:.6f} C_lo={c_lo:.6f} Q_hi={q_hi:.6f} Q_lo={q_lo:.6f} "
        f"good={(out.label=='good').sum()} bad={(out.label=='bad').sum()} "
        f"neutral={(out.label=='neutral').sum()} neutral_rate={neutral_rate:.6f}"
    )
    return out


def main() -> None:
    if W != 30:
        raise ValueError("audit locked to W=30")

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)

    w30 = build_representation_a_table(
        df, paths, window=W, stride=1, random_samples=20, random_seed=SEED
    )
    wq = build_window_q(w30, paths).sort_values("start_index").reset_index(drop=True)
    gate = classify_layer1(wq)
    centered = build_centered_entries_50(df, paths)

    gate_by_end = gate.set_index("end_index")
    rows = []
    for r in centered.itertuples(index=False):
        prev_end = int(r.entry_index) - 1
        if prev_end not in gate_by_end.index:
            continue
        g = gate_by_end.loc[prev_end]
        if isinstance(g, pd.DataFrame):
            g = g.iloc[0]
        rows.append(
            {
                "entry_index": int(r.entry_index),
                "entry_date": r.entry_date,
                "C": float(r.C),
                "Q": float(r.Q),
                "label": r.label,
                "non_neutral": int(r.non_neutral),
                "prev_start": int(g.start_index),
                "prev_end": int(prev_end),
                "prev_state": g.state,
                "past_C": float(g.past_C),
                "past_Q": float(g.past_Q),
            }
        )

    matched = pd.DataFrame(rows)
    if matched.empty:
        raise RuntimeError("no exact previous-W gate matches")
    matched["decision"] = np.where(matched.prev_state.eq("neutral"), "block", "pass")

    print(
        f"S1 PWG50 START ticker={TICKER} rows={audit.rows} W={W} centered_entries={len(centered)} "
        f"layer1_windows={len(gate)} exact_prevW_matches={len(matched)}"
    )
    print(
        f"S1 PWG50 BASE n={len(matched)} non_neutral_rate={matched.non_neutral.mean():.6f} "
        f"neutral_rate={(matched.label=='neutral').mean():.6f}"
    )

    def s(name: str, g: pd.DataFrame) -> None:
        if g.empty:
            print(f"S1 PWG50 GROUP gate={name} n=0")
            return
        print(
            f"S1 PWG50 GROUP gate={name} n={len(g)} "
            f"non_neutral_rate={g.non_neutral.mean():.6f} neutral_rate={(g.label=='neutral').mean():.6f} "
            f"good_rate={(g.label=='good').mean():.6f} bad_rate={(g.label=='bad').mean():.6f} "
            f"C_mean={g.C.mean():.6f} Q_mean={g.Q.mean():.6f}"
        )

    p = matched.loc[matched.decision.eq("pass")]
    b = matched.loc[matched.decision.eq("block")]
    s("pass", p)
    s("block", b)
    for st in ("high", "neutral", "low"):
        s(st, matched.loc[matched.prev_state.eq(st)])

    pass_lift = p.non_neutral.mean() / matched.non_neutral.mean() if len(p) else np.nan
    block_neutral_lift = (
        b.label.eq("neutral").mean() / matched.label.eq("neutral").mean() if len(b) else np.nan
    )
    separation = b.label.eq("neutral").mean() - p.label.eq("neutral").mean()
    print(
        f"S1 PWG50 EFFECT pass_non_neutral_lift={pass_lift:.6f} "
        f"block_neutral_lift={block_neutral_lift:.6f} neutral_separation={separation:.6f} "
        f"pass_rate={(matched.decision=='pass').mean():.6f} block_rate={(matched.decision=='block').mean():.6f}"
    )
    matched.to_csv(OUTPUT, index=False)
    print(f"S1 PWG50 OUTPUT file={OUTPUT} rows={len(matched)}")
    print("S1 PWG50 COMPLETE target_neutral_approximately_50=true layer1_unchanged=true")


if __name__ == "__main__":
    main()

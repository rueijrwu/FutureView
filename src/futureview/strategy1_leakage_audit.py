from __future__ import annotations

import os
import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_entry_exit_cq_compare import build_cq
from .strategy1_exit_window_cq_audit import classify_causal, final_exit_index
from .strategy1_layer2_consensus_group_audit import consensus_label
from .strategy1_layer2_price_distribution import MODEL_HISTORY

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
ROLL_DAYS = int(os.environ.get("FUTUREVIEW_ROLL_DAYS", "10"))
L2_MEMORY = int(os.environ.get("FUTUREVIEW_L2_MEMORY", "150"))
HORIZONS = (5, 10, 15, 20, 25, 30, 45)


def main() -> None:
    if MODEL_HISTORY != 90:
        raise ValueError("leakage audit expects established 90D Layer2 input")

    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    validate_daily_ohlcv(df, minimum_rows=1800)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    p = paths.copy()
    p["final_exit_index"] = final_exit_index(p)

    # Build the exact Layer1 state table used by the current Layer2 audit.
    ce = classify_causal(build_cq(df, paths, membership="entry").rename(columns={"B": "B_periodic"}))
    cx = classify_causal(build_cq(df, paths, membership="exit").rename(columns={"B": "B_periodic"}))
    states = ce[["start_index", "end_index", "state"]].merge(
        cx[["start_index", "end_index", "state"]],
        on=["start_index", "end_index"],
        suffixes=("_entry", "_exit"),
    ).sort_values("end_index").reset_index(drop=True)
    states["consensus"] = [consensus_label(a, b) for a, b in zip(states.state_entry, states.state_exit)]

    eligible = states.loc[states.consensus.isin(["high", "low"])].copy()
    eligible = eligible.loc[
        (eligible.end_index.astype(int) - MODEL_HISTORY + 1 >= 0)
        & (eligible.end_index.astype(int) + max(HORIZONS) < len(df))
    ].copy()

    # Exact duplicate audit.
    dup_cut = eligible.end_index.astype(int).duplicated(keep=False)
    dup_windows = eligible.duplicated(["start_index", "end_index"], keep=False)
    print(
        f"S1 LEAK DUPLICATES W={W} eligible={len(eligible)} unique_cutoff={eligible.end_index.nunique()} "
        f"duplicate_cutoff_rows={int(dup_cut.sum())} duplicate_window_rows={int(dup_windows.sum())}"
    )

    # Sliding-window dependence is not exact duplication, but adjacent W windows overlap W-1 days.
    starts = np.sort(eligible.start_index.astype(int).unique())
    adjacent = np.diff(starts) if len(starts) > 1 else np.asarray([], dtype=int)
    adjacent_one = int((adjacent == 1).sum())
    print(
        f"S1 LEAK OVERLAP W={W} adjacent_pairs={len(adjacent)} adjacent_by_1={adjacent_one} "
        f"adjacent_window_overlap_if_step1={max(W-1,0)} overlap_fraction_if_step1={(W-1)/W if W else float('nan'):.6f}"
    )

    # Layer2 label-boundary audit: current code uses cutoff < block_start. Count rows whose label matures after OOS starts.
    first_cut = int(eligible.end_index.min())
    last_cut = int(eligible.end_index.max())
    for h in HORIZONS:
        contaminated = 0
        selected = 0
        clean_selected = 0
        folds = 0
        for block_start in range(first_cut, last_cut + 1, ROLL_DAYS):
            block_end = min(block_start + ROLL_DAYS - 1, last_cut)
            va = (eligible.end_index.astype(int) >= block_start) & (eligible.end_index.astype(int) <= block_end)
            if not va.any():
                continue
            tr = eligible.loc[eligible.end_index.astype(int) < block_start].sort_values("end_index")
            if len(tr) < L2_MEMORY:
                continue
            tr = tr.iloc[-L2_MEMORY:]
            folds += 1
            selected += len(tr)
            bad = tr.end_index.astype(int) + h >= block_start
            contaminated += int(bad.sum())
            clean = eligible.loc[eligible.end_index.astype(int) + h < block_start].sort_values("end_index")
            if len(clean) >= L2_MEMORY:
                clean_selected += L2_MEMORY
        frac = contaminated / selected if selected else float("nan")
        print(
            f"S1 LEAK L2_LABEL h={h} folds={folds} train_rows={selected} contaminated={contaminated} "
            f"contaminated_fraction={frac:.6f} clean_memory_rows_available={clean_selected}"
        )

    # Strict common purge for multi-horizon stacking.
    maxh = max(HORIZONS)
    contaminated = 0
    selected = 0
    folds = 0
    for block_start in range(first_cut, last_cut + 1, ROLL_DAYS):
        va = (eligible.end_index.astype(int) >= block_start) & (eligible.end_index.astype(int) <= block_end)
        tr = eligible.loc[eligible.end_index.astype(int) < block_start].sort_values("end_index")
        if not va.any() or len(tr) < L2_MEMORY:
            continue
        tr = tr.iloc[-L2_MEMORY:]
        folds += 1
        selected += len(tr)
        contaminated += int((tr.end_index.astype(int) + maxh >= block_start).sum())
    print(
        f"S1 LEAK L2_COMMON_PURGE max_h={maxh} folds={folds} train_rows={selected} contaminated={contaminated} "
        f"contaminated_fraction={(contaminated/selected if selected else float('nan')):.6f}"
    )

    # Layer1 as-of-t audit. Entry-window C/Q uses completed campaign_return from paths selected by entry inside W.
    # If any selected path exits after window end, that row's C/Q is not knowable at end_index.
    entry_cq = build_cq(df, paths, membership="entry")
    exit_cq = build_cq(df, paths, membership="exit")
    for membership, cq in (("entry", entry_cq), ("exit", exit_cq)):
        leak_windows = 0
        total_members = 0
        future_members = 0
        max_lookahead = 0
        for r in cq.itertuples(index=False):
            start, end = int(r.start_index), int(r.end_index)
            if membership == "entry":
                g = p.loc[(p.entry_index.astype(int) >= start) & (p.entry_index.astype(int) <= end)]
            else:
                g = p.loc[(p.final_exit_index.astype(int) >= start) & (p.final_exit_index.astype(int) <= end)]
            if g.empty:
                continue
            total_members += len(g)
            lag = g.final_exit_index.astype(int) - end
            bad = lag > 0
            future_members += int(bad.sum())
            if bad.any():
                leak_windows += 1
                max_lookahead = max(max_lookahead, int(lag[bad].max()))
        print(
            f"S1 LEAK L1_PATH membership={membership} windows={len(cq)} windows_with_future_path={leak_windows} "
            f"window_fraction={(leak_windows/len(cq) if len(cq) else float('nan')):.6f} members={total_members} "
            f"future_members={future_members} future_member_fraction={(future_members/total_members if total_members else float('nan')):.6f} "
            f"max_exit_lookahead={max_lookahead}"
        )

    # Deterministic path construction itself uses retrospective extrema with radius 5/10,
    # so an extremum at i cannot be confirmed until up to i+10 sessions.
    print("S1 LEAK EXTREMA retrospective_radius_max=10 confirmation_lookahead_sessions=10")
    print(f"S1 LEAK CONFIG ticker={TICKER} period={DATA_PERIOD} W={W} roll_days={ROLL_DAYS} l2_memory={L2_MEMORY}")
    print("S1 LEAK COMPLETE")


if __name__ == "__main__":
    main()

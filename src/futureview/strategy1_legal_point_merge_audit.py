from __future__ import annotations

import os
import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "10y")
MERGE_GAP = int(os.environ.get("FUTUREVIEW_MERGE_GAP", "3"))


def merge_after_full_scan(indices: np.ndarray, gap: int = MERGE_GAP) -> list[list[int]]:
    """Cluster fully-scanned legal points by chronological adjacency <= gap sessions.

    This function must receive the complete raw legal-point set. It never affects
    raw legality detection. Clustering is transitive over adjacent raw points.
    The canonical representative used by this audit is the earliest point in each
    cluster, which introduces no look-ahead beyond the point's own legality.
    """
    if gap < 0:
        raise ValueError("gap must be non-negative")
    x = np.unique(np.asarray(indices, dtype=np.int64))
    if len(x) == 0:
        return []
    clusters: list[list[int]] = [[int(x[0])]]
    for value in x[1:]:
        value = int(value)
        if value - clusters[-1][-1] <= gap:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return clusters


def _print_group(name: str, raw: np.ndarray, clusters: list[list[int]], events: pd.DataFrame) -> None:
    merged = np.asarray([c[0] for c in clusters], dtype=np.int64)
    multi = [c for c in clusters if len(c) > 1]
    max_size = max((len(c) for c in clusters), default=0)
    max_span = max((c[-1] - c[0] for c in clusters), default=0)
    print(
        f"S1 LPM COUNT type={name} raw={len(raw)} merged={len(merged)} "
        f"removed={len(raw)-len(merged)} reduction={(1-len(merged)/len(raw)) if len(raw) else 0.0:.6f} "
        f"multi_clusters={len(multi)} max_cluster_size={max_size} max_cluster_span={max_span}"
    )
    for c in clusters[-5:]:
        dates = [pd.Timestamp(events.at[i, 'date']).date().isoformat() for i in c]
        print(
            f"S1 LPM RECENT type={name} representative={dates[0]} size={len(c)} "
            f"first={dates[0]} last={dates[-1]} members={','.join(dates)}"
        )


def main() -> None:
    if MERGE_GAP != 3:
        raise ValueError("audit is locked to +/-3 trading-session merge")

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)

    # IMPORTANT: all raw legal sets are scanned first. Only after all three raw
    # sets exist do we perform any +/-3 clustering.
    raw_entry = np.flatnonzero(events["entry_candidate"].to_numpy(dtype=bool))
    raw_exit5 = np.flatnonzero(events["exit5_event"].to_numpy(dtype=bool))
    raw_exit10 = np.flatnonzero(events["exit10_event"].to_numpy(dtype=bool))

    entry_clusters = merge_after_full_scan(raw_entry)
    exit5_clusters = merge_after_full_scan(raw_exit5)
    exit10_clusters = merge_after_full_scan(raw_exit10)

    print(
        f"S1 LPM START ticker={TICKER} rows={audit.rows} first={audit.start} last={audit.end} "
        f"merge_gap={MERGE_GAP} order=scan_all_then_merge representative=earliest"
    )
    _print_group("entry", raw_entry, entry_clusters, events)
    _print_group("exit5", raw_exit5, exit5_clusters, events)
    _print_group("exit10", raw_exit10, exit10_clusters, events)

    # Validate that every raw point belongs to exactly one cluster and that no
    # cluster crossing occurs before the full raw scan.
    for name, raw, clusters in (
        ("entry", raw_entry, entry_clusters),
        ("exit5", raw_exit5, exit5_clusters),
        ("exit10", raw_exit10, exit10_clusters),
    ):
        flat = [v for c in clusters for v in c]
        if flat != raw.astype(int).tolist():
            raise RuntimeError(f"{name} merge lost/reordered raw legal points")
        if any((b[0] - a[-1]) <= MERGE_GAP for a, b in zip(clusters, clusters[1:])):
            raise RuntimeError(f"{name} adjacent clusters still within merge gap")

    print("S1 LPM COMPLETE scan_all_before_merge=true entry_exit_separate=true")


if __name__ == "__main__":
    main()

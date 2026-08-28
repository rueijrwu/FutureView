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
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer1-transition-audit.csv")


def build_episodes(classified: pd.DataFrame) -> pd.DataFrame:
    x = classified.sort_values("start_index").reset_index(drop=True)
    rows = []
    begin = 0
    for i in range(1, len(x) + 1):
        boundary = i == len(x) or x.at[i, "state"] != x.at[begin, "state"]
        if not boundary:
            continue
        g = x.iloc[begin:i]
        rows.append({
            "episode": len(rows),
            "state": str(g.iloc[0].state),
            "start_index": int(g.iloc[0].start_index),
            "last_start_index": int(g.iloc[-1].start_index),
            "duration": int(g.iloc[-1].start_index - g.iloc[0].start_index + 1),
            "rows": int(len(g)),
        })
        begin = i
    return pd.DataFrame(rows)


def build_transitions(episodes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    extremes = episodes.index[episodes.state.isin(["high", "low"])].tolist()
    for pos, i in enumerate(extremes[:-1]):
        j = extremes[pos + 1]
        src = episodes.loc[i]
        dst = episodes.loc[j]
        between = episodes.loc[i + 1:j - 1] if j > i + 1 else episodes.iloc[0:0]
        neutral_days = int(between.loc[between.state == "neutral", "duration"].sum())
        neutral_episodes = int((between.state == "neutral").sum())
        reversal = str(src.state) != str(dst.state)
        rows.append({
            "source_state": str(src.state),
            "destination_state": str(dst.state),
            "reversal": bool(reversal),
            "source_start": int(src.start_index),
            "source_duration": int(src.duration),
            "neutral_days": neutral_days,
            "neutral_episodes": neutral_episodes,
            "destination_start": int(dst.start_index),
            "first_passage_days": int(dst.start_index - src.last_start_index),
            "start_to_start_days": int(dst.start_index - src.start_index),
        })
    return pd.DataFrame(rows)


def _dist(name: str, values: pd.Series) -> None:
    a = values.to_numpy(dtype=float)
    if len(a) == 0:
        print(f"S1 L1TRANS DIST metric={name} n=0")
        return
    q = np.quantile(a, [0.10, 0.25, 0.50, 0.75, 0.90])
    print(
        f"S1 L1TRANS DIST metric={name} n={len(a)} mean={a.mean():.3f} "
        f"p10={q[0]:.3f} p25={q[1]:.3f} median={q[2]:.3f} p75={q[3]:.3f} p90={q[4]:.3f} max={a.max():.3f}"
    )


def main() -> None:
    if W != 30:
        raise ValueError("transition audit locked to W=30")
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    windows = build_representation_a_table(df, paths, window=W, stride=1, random_samples=20, random_seed=SEED)
    wq = build_window_q(windows, paths).sort_values("start_index").reset_index(drop=True)
    classified = _classify(wq)
    episodes = build_episodes(classified)
    transitions = build_transitions(episodes)
    transitions.to_csv(OUTPUT, index=False)

    print(f"S1 L1TRANS START ticker={TICKER} rows={audit.rows} classified={len(classified)} episodes={len(episodes)} transitions={len(transitions)}")
    for state in ("high", "neutral", "low"):
        g = episodes.loc[episodes.state == state]
        print(f"S1 L1TRANS EPISODES state={state} n={len(g)}")
        _dist(f"{state}_episode_duration", g.duration)

    for source, destination in (("high", "low"), ("low", "high")):
        all_src = transitions.loc[transitions.source_state == source]
        rev = all_src.loc[all_src.destination_state == destination]
        same = all_src.loc[all_src.destination_state == source]
        rate = len(rev) / len(all_src) if len(all_src) else float("nan")
        print(
            f"S1 L1TRANS DIRECTION source={source} destination={destination} opportunities={len(all_src)} "
            f"reversals={len(rev)} returns_same={len(same)} reversal_rate={rate:.6f}"
        )
        _dist(f"{source}_to_{destination}_neutral_days", rev.neutral_days)
        _dist(f"{source}_to_{destination}_first_passage_days", rev.first_passage_days)
        _dist(f"{source}_to_{destination}_start_to_start_days", rev.start_to_start_days)

    patterns = transitions.assign(pattern=transitions.source_state + "->" + np.where(transitions.neutral_days > 0, "neutral->", "") + transitions.destination_state)
    for pattern, n in patterns.pattern.value_counts().items():
        print(f"S1 L1TRANS PATTERN pattern={pattern} n={n} rate={n/len(patterns):.6f}")

    print(f"S1 L1TRANS OUTPUT file={OUTPUT} rows={len(transitions)}")
    print("S1 L1TRANS COMPLETE")


if __name__ == "__main__":
    main()

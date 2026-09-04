from __future__ import annotations

import numpy as np
import pandas as pd

from futureview.strategy1_layer2_price_distribution_causal import build_causal_paths_asof


def _events(n: int = 80) -> pd.DataFrame:
    close = np.linspace(100.0, 140.0, n)
    df = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=n, freq="D"),
            "close": close,
            "entry_candidate": False,
            "exit5_event": False,
            "exit10_event": False,
        }
    )
    df.loc[[20, 35, 50], "entry_candidate"] = True
    df.loc[[30, 45, 60], "exit5_event"] = True
    df.loc[[40, 55, 70], "exit10_event"] = True
    return df


def test_causal_path_builder_never_returns_future_entries() -> None:
    events = _events()
    out = build_causal_paths_asof(events, 49)
    assert out.empty or (out["entry_index"].astype(int) <= 49).all()


def test_causal_path_builder_is_invariant_to_future_mutation() -> None:
    events = _events()
    a = build_causal_paths_asof(events, 49)
    changed = events.copy()
    changed.loc[50:, "close"] = changed.loc[50:, "close"] * 100.0
    changed.loc[50:, "entry_candidate"] = ~changed.loc[50:, "entry_candidate"]
    changed.loc[50:, "exit5_event"] = ~changed.loc[50:, "exit5_event"]
    changed.loc[50:, "exit10_event"] = ~changed.loc[50:, "exit10_event"]
    b = build_causal_paths_asof(changed, 49)
    pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))

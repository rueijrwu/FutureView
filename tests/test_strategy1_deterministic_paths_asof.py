from __future__ import annotations

import numpy as np
import pandas as pd

from futureview.strategy1_deterministic_paths import (
    MERGE_GAP,
    build_extrema_sets,
    preprocess_legal_points,
    simulate_deterministic_path,
)
from futureview.strategy1_deterministic_paths_asof import (
    build_deterministic_path_table_asof,
    simulate_deterministic_path_asof,
)


def _events() -> pd.DataFrame:
    close = np.array([10.0, 10.2, 10.4, 10.6, 10.0, 11.0, 11.2, 11.4, 12.0, 12.2, 12.4, 12.6])
    return pd.DataFrame({
        "close": close,
        "exit5_event": np.zeros(len(close), dtype=bool),
        "exit10_event": np.zeros(len(close), dtype=bool),
    })


def test_open_position_is_force_closed_at_asof_close() -> None:
    events = _events()
    path = simulate_deterministic_path_asof(
        events,
        entry=5,
        local_mins=np.array([4], dtype=np.int32),
        local_maxs=np.array([], dtype=np.int32),
        asof_index=8,
        horizon=60,
    )
    assert path is not None
    assert path.exit10_index == -1
    assert path.horizon_exit_index == -1
    assert path.forced_asof_exit_index == 8
    expected = (2.0 / 3.0) + (1.0 / 3.0) * (12.0 / 11.0) - 1.0
    assert abs(path.campaign_return - expected) < 1e-12


def test_completed_exit10_is_not_force_closed() -> None:
    events = _events()
    events.loc[7, "exit10_event"] = True
    path = simulate_deterministic_path_asof(
        events,
        entry=5,
        local_mins=np.array([4], dtype=np.int32),
        local_maxs=np.array([], dtype=np.int32),
        asof_index=8,
        horizon=60,
    )
    assert path is not None
    assert path.exit10_index == 7
    assert path.forced_asof_exit_index == -1
    expected = (2.0 / 3.0) + (1.0 / 3.0) * (11.4 / 11.0) - 1.0
    assert abs(path.campaign_return - expected) < 1e-12


def _long_events() -> pd.DataFrame:
    n = 240
    x = np.arange(n, dtype=float)
    close = 100.0 + 0.035 * x + 3.0 * np.sin(x / 7.0) + 1.4 * np.sin(x / 17.0)
    entry_candidate = np.zeros(n, dtype=bool)
    exit5_event = np.zeros(n, dtype=bool)
    exit10_event = np.zeros(n, dtype=bool)
    entry_candidate[[25, 27, 31, 52, 76, 79, 105, 137, 166, 194, 218, 221]] = True
    exit5_event[[46, 89, 126, 173, 205, 229]] = True
    exit10_event[[60, 98, 151, 187, 214, 235]] = True
    return pd.DataFrame({
        "close": close,
        "entry_candidate": entry_candidate,
        "exit5_event": exit5_event,
        "exit10_event": exit10_event,
    })


def test_builder_reuses_completed_paths_and_only_forces_later_exits() -> None:
    events = _long_events()
    prepared = preprocess_legal_points(events, gap=MERGE_GAP)
    mins, maxs = build_extrema_sets(prepared)

    # Full paths are the prepared historical outcomes.  At each rolling cutoff,
    # completed paths must be identical; only paths whose exit lies later than
    # the cutoff are replayed and force-closed at that cutoff.
    full: dict[int, object] = {}
    entries = np.flatnonzero(prepared["entry_candidate"].to_numpy(dtype=bool))
    for entry in entries:
        p = simulate_deterministic_path(prepared, int(entry), mins, maxs)
        if p is not None:
            full[int(entry)] = p

    for cutoff in (90, 120, 160, 200, 230):
        actual = build_deterministic_path_table_asof(events, asof_index=cutoff).set_index("entry_index")
        for entry, p in full.items():
            if entry > cutoff:
                continue
            final_exit = p.exit10_index if p.exit10_index >= 0 else p.horizon_exit_index
            row = actual.loc[entry]
            if final_exit <= cutoff:
                assert row.exit_mode in {"exit10", "horizon"}
                assert int(row.forced_asof_exit_index) == -1
                assert int(row.addon1_index) == p.addon1_index
                assert int(row.addon2_index) == p.addon2_index
                assert int(row.exit5_index) == p.exit5_index
                assert int(row.exit10_index) == p.exit10_index
                assert int(row.horizon_exit_index) == p.horizon_exit_index
                assert abs(float(row.campaign_return) - p.campaign_return) < 1e-12
            else:
                assert row.exit_mode == "forced_asof"
                assert int(row.forced_asof_exit_index) == cutoff

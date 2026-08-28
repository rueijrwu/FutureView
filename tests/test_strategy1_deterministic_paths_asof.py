from __future__ import annotations

import numpy as np
import pandas as pd

from futureview.strategy1_deterministic_paths import (
    MERGE_GAP,
    build_extrema_sets,
    preprocess_legal_points,
)
from futureview.strategy1_deterministic_paths_asof import (
    build_deterministic_path_table_asof,
    simulate_deterministic_path_asof,
)


def _events() -> pd.DataFrame:
    close = np.array([10.0, 10.2, 10.4, 10.6, 10.0, 11.0, 11.2, 11.4, 12.0, 12.2, 12.4, 12.6])
    return pd.DataFrame(
        {
            "close": close,
            "exit5_event": np.zeros(len(close), dtype=bool),
            "exit10_event": np.zeros(len(close), dtype=bool),
        }
    )


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


def _reference_full_rebuild(events: pd.DataFrame, asof_index: int) -> pd.DataFrame:
    truncated = events.iloc[: asof_index + 1].copy().reset_index(drop=True)
    truncated = preprocess_legal_points(truncated, gap=MERGE_GAP)
    local_mins, local_maxs = build_extrema_sets(truncated)
    entries = np.flatnonzero(truncated["entry_candidate"].to_numpy(dtype=bool))

    rows: list[dict[str, int | float | str]] = []
    for raw_entry in entries:
        path = simulate_deterministic_path_asof(
            truncated,
            int(raw_entry),
            local_mins,
            local_maxs,
            asof_index=asof_index,
        )
        if path is None:
            continue
        if path.exit10_index >= 0:
            exit_mode = "exit10"
        elif path.horizon_exit_index >= 0:
            exit_mode = "horizon"
        elif path.forced_asof_exit_index >= 0:
            exit_mode = "forced_asof"
        else:
            exit_mode = "closed"
        rows.append(
            {
                "entry_index": path.entry_index,
                "base_min_index": path.base_min_index,
                "base_distance": path.base_distance,
                "addon1_index": path.addon1_index,
                "addon2_index": path.addon2_index,
                "exit5_index": path.exit5_index,
                "exit10_index": path.exit10_index,
                "horizon_exit_index": path.horizon_exit_index,
                "forced_asof_exit_index": path.forced_asof_exit_index,
                "exit_mode": exit_mode,
                "campaign_return": path.campaign_return,
                "executed_addons": int(path.addon1_index >= 0) + int(path.addon2_index >= 0),
            }
        )
    return pd.DataFrame(rows).sort_values("entry_index").reset_index(drop=True)


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
    return pd.DataFrame(
        {
            "close": close,
            "entry_candidate": entry_candidate,
            "exit5_event": exit5_event,
            "exit10_event": exit10_event,
        }
    )


def test_cached_builder_matches_full_rebuild_at_multiple_cutoffs() -> None:
    events = _long_events()
    for cutoff in (90, 120, 160, 200, 230):
        expected = _reference_full_rebuild(events, cutoff)
        actual = build_deterministic_path_table_asof(events, asof_index=cutoff)
        assert list(actual.columns) == list(expected.columns)
        assert actual["entry_index"].tolist() == expected["entry_index"].tolist()
        for col in actual.columns:
            if col in {"base_distance", "campaign_return"}:
                np.testing.assert_allclose(actual[col].to_numpy(dtype=float), expected[col].to_numpy(dtype=float), rtol=0.0, atol=1e-12)
            else:
                assert actual[col].tolist() == expected[col].tolist()

from __future__ import annotations

import numpy as np
import pandas as pd

from futureview.strategy1_deterministic_paths_asof import simulate_deterministic_path_asof


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

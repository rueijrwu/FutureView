from __future__ import annotations

import pandas as pd

from . import strategy1_reference_distribution as base
from . import strategy1_reference_distribution_fast as fast
from . import strategy1_reference_distribution_policy_compare as policy


def _init_worker_fast(events: pd.DataFrame) -> None:
    base._simulate_cached = fast._simulate_cached_fast
    base._prepare_worker_state(events)


def main() -> None:
    base._simulate_cached = fast._simulate_cached_fast
    policy._init_worker = _init_worker_fast
    print(
        "S1 POLICY_COMPARE FAST backend=numba_jit "
        "policies=max1,unrestricted,spacing10,spacing20,spacing30"
    )
    policy.main()


if __name__ == "__main__":
    main()

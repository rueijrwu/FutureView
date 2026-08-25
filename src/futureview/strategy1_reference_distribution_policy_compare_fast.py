from __future__ import annotations

import os

from . import strategy1_reference_distribution as base
from . import strategy1_reference_distribution_fast as fast
from . import strategy1_reference_distribution_policy_compare as policy


def main() -> None:
    # Runtime patching is kept single-process so every policy uses the Numba
    # simulator and the exact same realized-path signature implementation.
    base._simulate_cached = fast._simulate_cached_fast
    policy._simulate_policy_path = fast._simulate_cached_fast_path
    previous_workers = os.environ.get("FUTUREVIEW_WORKERS")
    os.environ["FUTUREVIEW_WORKERS"] = "1"
    try:
        print(
            "S1 POLICY_COMPARE FAST backend=numba_jit workers=1 "
            "reason=runtime_jit_patch_process_safe "
            f"cache_size={fast.FAST_SIM_CACHE_SIZE} "
            "distribution_weighting=unique_realized_paths "
            "policies=max1,unrestricted,spacing10,spacing20,spacing30"
        )
        policy.main()
    finally:
        if previous_workers is None:
            os.environ.pop("FUTUREVIEW_WORKERS", None)
        else:
            os.environ["FUTUREVIEW_WORKERS"] = previous_workers


if __name__ == "__main__":
    main()

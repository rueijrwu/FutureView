from __future__ import annotations

import os

from . import strategy1_reference_distribution as base
from . import strategy1_reference_distribution_fast as fast
from . import strategy1_reference_distribution_policy_compare as policy


def main() -> None:
    # The fast backend is installed at runtime by replacing base._simulate_cached.
    # ProcessPoolExecutor child processes re-import modules and do not reliably
    # inherit that monkeypatch, which can terminate workers abruptly. Keep this
    # runner single-process while retaining the Numba-JIT hot simulation path.
    # The fast simulator cache is bounded so policy sweeps cannot grow memory
    # without limit across thousands of anchors and five policies.
    base._simulate_cached = fast._simulate_cached_fast
    previous_workers = os.environ.get("FUTUREVIEW_WORKERS")
    os.environ["FUTUREVIEW_WORKERS"] = "1"
    try:
        print(
            "S1 POLICY_COMPARE FAST backend=numba_jit workers=1 "
            "reason=runtime_jit_patch_process_safe "
            f"cache_size={fast.FAST_SIM_CACHE_SIZE} "
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

from __future__ import annotations

from . import strategy1_entry_value_compare as _compare


def main() -> None:
    # Canonical entry-value experiment is intentionally capped at five years.
    _compare.DATA_PERIOD = "5y"
    _compare.main()


if __name__ == "__main__":
    main()

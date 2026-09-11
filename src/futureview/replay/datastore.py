from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from futureview.replay.models import Bar

_REQUIRED = {"timestamp", "symbol", "open", "high", "low", "close", "volume"}


class ReplayDataStore:
    """Read prepared MES 5-minute Parquet without inventing a continuous price series."""

    def __init__(self, manifest_path: str | Path) -> None:
        self.manifest_path = Path(manifest_path)
        if not self.manifest_path.exists():
            raise FileNotFoundError(
                f"Replay manifest not found: {self.manifest_path}. "
                "Run scripts/prepare_mes_databento.py first."
            )
        self._manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self._base = self.manifest_path.parent
        self._contract_files: dict[str, list[Path]] = {}
        self._contract_order: list[str] = []
        self._cache: dict[str, list[Bar]] = {}
        self._build_index()

    def _resolve_output(self, value: str) -> Path:
        path = Path(value)
        if path.exists():
            return path
        candidate = self._base / "parquet" / "5m" / path.name
        if candidate.exists():
            return candidate
        return path

    def _build_index(self) -> None:
        for entry in self._manifest.get("files", []):
            output = self._resolve_output(entry["output_5m"])
            for contract in entry.get("symbols", []):
                if contract not in self._contract_files:
                    self._contract_files[contract] = []
                    self._contract_order.append(contract)
                self._contract_files[contract].append(output)

    def contracts(self) -> list[str]:
        return list(self._contract_order)

    def contract_info(self, contract: str) -> dict[str, object]:
        bars = self.load_contract(contract)
        return {
            "contract": contract,
            "bars": len(bars),
            "first": bars[0].timestamp.isoformat(),
            "last": bars[-1].timestamp.isoformat(),
        }

    def load_contract(self, contract: str) -> list[Bar]:
        if contract in self._cache:
            return self._cache[contract]
        paths = self._contract_files.get(contract)
        if not paths:
            raise KeyError(f"Unknown MES contract: {contract}")

        frames: list[pd.DataFrame] = []
        for path in paths:
            if not path.exists():
                raise FileNotFoundError(
                    f"Prepared 5m Parquet missing: {path}. "
                    "Run scripts/prepare_mes_databento.py locally."
                )
            frame = pd.read_parquet(path)
            missing = sorted(_REQUIRED.difference(frame.columns))
            if missing:
                raise ValueError(f"{path}: missing replay columns: {missing}")
            frame = frame.loc[frame["symbol"].astype(str) == contract].copy()
            if not frame.empty:
                frames.append(frame)

        if not frames:
            raise ValueError(f"No 5m bars found for contract {contract}")

        data = pd.concat(frames, ignore_index=True)
        data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
        data = (
            data.drop_duplicates(["symbol", "timestamp"], keep="last")
            .sort_values("timestamp", kind="stable")
            .reset_index(drop=True)
        )

        bars = [
            Bar(
                timestamp=row.timestamp.to_pydatetime(),
                contract=contract,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
            )
            for row in data.itertuples(index=False)
        ]
        self._cache[contract] = bars
        return bars

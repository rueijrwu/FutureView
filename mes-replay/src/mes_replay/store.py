from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from mes_replay.models import Bar


class BarStore:
    def __init__(self, manifest_path: str | Path) -> None:
        self.manifest_path = Path(manifest_path)
        self.root = self.manifest_path.parent
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self._paths: dict[str, list[Path]] = {}
        self._order: list[str] = []
        self._cache: dict[str, list[Bar]] = {}
        for entry in self.manifest["files"]:
            path = self.root / str(entry["five_minute"])
            for symbol in entry["symbols"]:
                if symbol not in self._paths:
                    self._paths[symbol] = []
                    self._order.append(symbol)
                self._paths[symbol].append(path)

    def contracts(self) -> list[str]:
        return list(self._order)

    def bars(self, contract: str) -> list[Bar]:
        if contract in self._cache:
            return self._cache[contract]
        paths = self._paths.get(contract)
        if not paths:
            raise KeyError(contract)
        frames: list[pd.DataFrame] = []
        for path in paths:
            frame = pd.read_parquet(path)
            frame = frame.loc[frame["symbol"].astype(str) == contract]
            if not frame.empty:
                frames.append(frame)
        if not frames:
            raise ValueError(f"No 5m bars for {contract}")
        frame = pd.concat(frames, ignore_index=True)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame = frame.drop_duplicates(["symbol", "timestamp"], keep="last").sort_values("timestamp")
        result = [Bar(
            timestamp=row.timestamp.to_pydatetime(), contract=contract,
            open=float(row.open), high=float(row.high), low=float(row.low), close=float(row.close), volume=float(row.volume),
        ) for row in frame.itertuples(index=False)]
        self._cache[contract] = result
        return result

    def info(self, contract: str) -> dict[str, object]:
        bars = self.bars(contract)
        return {"contract": contract, "bars": len(bars), "first": bars[0].timestamp.isoformat(), "last": bars[-1].timestamp.isoformat()}

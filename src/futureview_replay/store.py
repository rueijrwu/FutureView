from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from futureview_replay.models import Bar
from futureview_replay.resolver import build_selection_calendar, resolve_from_calendar, session_date


class BarStore:
    def __init__(self, manifest_path: str | Path) -> None:
        self.manifest_path = Path(manifest_path)
        self.root = self.manifest_path.parent
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self._paths: dict[str, list[Path]] = {}
        self._order: list[str] = []
        self._cache: dict[str, list[Bar]] = {}
        self._selection_calendar: list[dict[str, object]] | None = None
        for entry in self.manifest["files"]:
            path = self.root / str(entry["five_minute"])
            for symbol in entry["symbols"]:
                if symbol not in self._paths:
                    self._paths[symbol] = []
                    self._order.append(symbol)
                self._paths[symbol].append(path)

    def contracts(self) -> list[str]:
        return list(self._order)

    @property
    def product(self) -> str:
        return str(self.manifest["product"])

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
        result = [
            Bar(
                timestamp=row.timestamp.to_pydatetime(),
                contract=contract,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
            )
            for row in frame.itertuples(index=False)
        ]
        self._cache[contract] = result
        return result

    def replay_range(self) -> dict[str, object]:
        infos = [self.info(contract) for contract in self.contracts()]
        first_iso = min(str(info["first"]) for info in infos)
        last_iso = max(str(info["last"]) for info in infos)
        first_dt = datetime.fromisoformat(first_iso)
        last_dt = datetime.fromisoformat(last_iso)
        return {
            "product": self.product,
            "first": first_iso,
            "last": last_iso,
            "first_time": int(first_dt.timestamp()),
            "last_time": int(last_dt.timestamp()),
        }

    def resolve_contract(self, product: str, start: datetime) -> dict[str, object]:
        if product.upper() != self.product.upper():
            raise ValueError(f"Unknown product {product}")
        if self._selection_calendar is None:
            volumes: dict[date, dict[str, float]] = {}
            for path in dict.fromkeys(path for paths in self._paths.values() for path in paths):
                frame = pd.read_parquet(path, columns=["timestamp", "symbol", "volume"])
                frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
                for row in frame.itertuples(index=False):
                    current = volumes.setdefault(session_date(row.timestamp.to_pydatetime()), {})
                    symbol = str(row.symbol)
                    current[symbol] = current.get(symbol, 0.0) + float(row.volume)
            self._selection_calendar = build_selection_calendar(volumes)
        return resolve_from_calendar(self._selection_calendar, start)

    def info(self, contract: str) -> dict[str, object]:
        bars = self.bars(contract)
        return {
            "contract": contract,
            "bars": len(bars),
            "first": bars[0].timestamp.isoformat(),
            "last": bars[-1].timestamp.isoformat(),
        }

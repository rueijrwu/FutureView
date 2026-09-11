from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ReplayState(str, Enum):
    STOPPED = "STOPPED"
    PLAYING = "PLAYING"
    PAUSED = "PAUSED"
    FINISHED = "FINISHED"


@dataclass(frozen=True, slots=True)
class Bar:
    timestamp: datetime
    contract: str
    open: float
    high: float
    low: float
    close: float
    volume: float

    def wire(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "time": int(self.timestamp.timestamp()),
            "contract": self.contract,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }

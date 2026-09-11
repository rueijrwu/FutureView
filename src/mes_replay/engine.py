from __future__ import annotations

import asyncio
import bisect
import time
from datetime import datetime, timezone
from typing import Any

from mes_replay.models import Bar, ReplayState
from mes_replay.store import BarStore

SPEEDS = {1, 5, 10, 25, 50, 100}


class ReplayEngine:
    def __init__(self, store: BarStore) -> None:
        self.store = store
        self.state = ReplayState.STOPPED
        self.speed: int | str = 1
        self.contract: str | None = None
        self._bars: list[Bar] = []
        self._cursor = -1
        self._origin = -1
        self._warmup = 300
        self._generation = 0
        self._task: asyncio.Task[None] | None = None
        self._queues: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2048)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._queues.discard(q)

    async def _emit(self, event: dict[str, Any]) -> None:
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                self._queues.discard(q)

    def snapshot(self) -> dict[str, Any]:
        current = self._bars[self._cursor] if 0 <= self._cursor < len(self._bars) else None
        return {
            "type": "session_snapshot", "state": self.state.value, "speed": self.speed,
            "contract": self.contract, "cursor": current.timestamp.isoformat() if current else None,
            "cursor_index": self._cursor, "bars_total": len(self._bars), "bars_released": max(0, self._cursor + 1),
        }

    async def start(self, contract: str, start: datetime, warmup: int = 300) -> dict[str, Any]:
        start = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start.astimezone(timezone.utc)
        async with self._lock:
            self._stop_task()
            self._generation += 1
            self._bars = self.store.bars(contract)
            idx = bisect.bisect_left([b.timestamp for b in self._bars], start)
            if idx >= len(self._bars):
                raise ValueError(f"No {contract} bar at or after {start.isoformat()}")
            self.contract = contract
            self._cursor = self._origin = idx
            self._warmup = max(0, int(warmup))
            self.state = ReplayState.PAUSED
            self.speed = 1
            first = max(0, idx - self._warmup)
            payload = {**self.snapshot(), "warmup": [b.wire() for b in self._bars[first:idx + 1]], "future_data_included": False}
        await self._emit(self.snapshot())
        return payload

    def _stop_task(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    def _advance(self, count: int) -> list[Bar]:
        if self._cursor >= len(self._bars) - 1:
            self.state = ReplayState.FINISHED
            return []
        end = min(len(self._bars) - 1, self._cursor + count)
        released = self._bars[self._cursor + 1:end + 1]
        self._cursor = end
        if end == len(self._bars) - 1:
            self.state = ReplayState.FINISHED
        return released

    @staticmethod
    def _bar_event(bars: list[Bar]) -> dict[str, Any]:
        return {"type": "bar", "bar": bars[0].wire()} if len(bars) == 1 else {"type": "bars_batch", "bars": [b.wire() for b in bars]}

    async def step(self) -> dict[str, Any]:
        async with self._lock:
            if not self._bars:
                raise RuntimeError("Replay not started")
            if self.state == ReplayState.PLAYING:
                raise RuntimeError("Pause before stepping")
            released = self._advance(1)
            snapshot = self.snapshot()
        if released:
            await self._emit(self._bar_event(released))
        await self._emit(snapshot)
        return snapshot

    async def restart(self) -> dict[str, Any]:
        async with self._lock:
            if not self._bars:
                raise RuntimeError("Replay not started")
            self._generation += 1
            self._stop_task()
            self._cursor = self._origin
            self.state = ReplayState.PAUSED
            first = max(0, self._cursor - self._warmup)
            payload = {**self.snapshot(), "warmup": [b.wire() for b in self._bars[first:self._cursor + 1]], "future_data_included": False}
        await self._emit(self.snapshot())
        return payload

    async def pause(self) -> dict[str, Any]:
        async with self._lock:
            self._generation += 1
            self._stop_task()
            if self._bars and self.state != ReplayState.FINISHED:
                self.state = ReplayState.PAUSED
            snapshot = self.snapshot()
        await self._emit(snapshot)
        return snapshot

    async def play(self, speed: int | str) -> dict[str, Any]:
        normalized: int | str
        if isinstance(speed, str) and speed.lower() == "max":
            normalized = "max"
        else:
            normalized = int(speed)
            if normalized not in SPEEDS:
                raise ValueError(f"Allowed speeds: {sorted(SPEEDS)} or max")
        async with self._lock:
            if not self._bars:
                raise RuntimeError("Replay not started")
            if self.state == ReplayState.FINISHED:
                raise RuntimeError("Replay finished; restart first")
            self._generation += 1
            generation = self._generation
            self._stop_task()
            self.speed = normalized
            self.state = ReplayState.PLAYING
            self._task = asyncio.create_task(self._scheduler(generation))
            snapshot = self.snapshot()
        await self._emit(snapshot)
        return snapshot

    async def _scheduler(self, generation: int) -> None:
        last = time.monotonic()
        credit = 0.0
        try:
            while True:
                await asyncio.sleep(0.01)
                event = snapshot = None
                async with self._lock:
                    if generation != self._generation or self.state != ReplayState.PLAYING:
                        return
                    now = time.monotonic()
                    elapsed = now - last
                    last = now
                    if self.speed == "max":
                        due = min(500, len(self._bars) - self._cursor - 1)
                    else:
                        credit += elapsed * int(self.speed)
                        due = int(credit)
                        credit -= due
                    if due <= 0:
                        continue
                    released = self._advance(due)
                    if released:
                        event = self._bar_event(released)
                    if self.state == ReplayState.FINISHED:
                        snapshot = self.snapshot()
                if event:
                    await self._emit(event)
                if snapshot:
                    await self._emit(snapshot)
                    return
        except asyncio.CancelledError:
            return

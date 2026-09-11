from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from futureview.replay.datastore import ReplayDataStore
from futureview.replay.models import Bar, ReplayState

_ALLOWED_SPEEDS = {1, 5, 10, 25, 50, 100}


class ReplayEngine:
    """Single-session, forward-only 5-minute replay engine.

    The engine owns all future bars. Clients only receive the warmup window and
    bars released as the cursor advances.
    """

    def __init__(self, datastore: ReplayDataStore) -> None:
        self.datastore = datastore
        self.state = ReplayState.STOPPED
        self.speed: int | str = 1
        self.contract: str | None = None
        self._bars: list[Bar] = []
        self._cursor = -1
        self._start_cursor = -1
        self._warmup = 300
        self._generation = 0
        self._play_task: asyncio.Task[None] | None = None
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()

    def contracts(self) -> list[str]:
        return self.datastore.contracts()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1024)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    async def _publish(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self._subscribers.discard(queue)

    def snapshot(self) -> dict[str, Any]:
        current = self._bars[self._cursor] if 0 <= self._cursor < len(self._bars) else None
        return {
            "type": "session_snapshot",
            "state": self.state.value,
            "speed": self.speed,
            "contract": self.contract,
            "cursor": current.timestamp.isoformat() if current else None,
            "cursor_index": self._cursor,
            "bars_total": len(self._bars),
            "bars_released": max(0, self._cursor + 1),
        }

    async def start(self, contract: str, start: datetime, *, warmup: int = 300) -> dict[str, Any]:
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        else:
            start = start.astimezone(timezone.utc)

        async with self._lock:
            self._generation += 1
            self._cancel_play_task()
            self._bars = self.datastore.load_contract(contract)
            timestamps = [bar.timestamp for bar in self._bars]

            lo, hi = 0, len(timestamps)
            while lo < hi:
                mid = (lo + hi) // 2
                if timestamps[mid] < start:
                    lo = mid + 1
                else:
                    hi = mid
            if lo >= len(self._bars):
                raise ValueError(
                    f"No {contract} bar at or after {start.isoformat()}; "
                    f"last bar is {timestamps[-1].isoformat()}"
                )

            self.contract = contract
            self._cursor = lo
            self._start_cursor = lo
            self._warmup = max(0, int(warmup))
            self.state = ReplayState.PAUSED
            self.speed = 1
            first = max(0, self._cursor - self._warmup)
            revealed = [bar.to_wire() for bar in self._bars[first : self._cursor + 1]]
            payload = {**self.snapshot(), "warmup": revealed, "future_data_included": False}

        await self._publish(self.snapshot())
        return payload

    def _cancel_play_task(self) -> None:
        if self._play_task and not self._play_task.done():
            self._play_task.cancel()
        self._play_task = None

    async def step(self, count: int = 1) -> dict[str, Any]:
        if count <= 0:
            raise ValueError("count must be positive")
        async with self._lock:
            if not self._bars or self._cursor < 0:
                raise RuntimeError("Replay has not been started")
            if self.state == ReplayState.PLAYING:
                raise RuntimeError("Pause replay before manual stepping")
            bars = self._advance_locked(count)
            event = self._bars_event(bars)
        if bars:
            await self._publish(event)
        await self._publish(self.snapshot())
        return event

    async def restart(self) -> dict[str, Any]:
        async with self._lock:
            if not self._bars or self._start_cursor < 0:
                raise RuntimeError("Replay has not been started")
            self._generation += 1
            self._cancel_play_task()
            self._cursor = self._start_cursor
            self.state = ReplayState.PAUSED
            first = max(0, self._cursor - self._warmup)
            warmup = [bar.to_wire() for bar in self._bars[first : self._cursor + 1]]
            payload = {**self.snapshot(), "warmup": warmup, "future_data_included": False}
        await self._publish(self.snapshot())
        return payload

    async def pause(self) -> dict[str, Any]:
        async with self._lock:
            self._generation += 1
            self._cancel_play_task()
            if self._bars and self.state != ReplayState.FINISHED:
                self.state = ReplayState.PAUSED
            snapshot = self.snapshot()
        await self._publish(snapshot)
        return snapshot

    async def play(self, speed: int | str) -> dict[str, Any]:
        if isinstance(speed, str) and speed.lower() == "max":
            normalized: int | str = "max"
        else:
            normalized = int(speed)
            if normalized not in _ALLOWED_SPEEDS:
                raise ValueError(f"speed must be one of {sorted(_ALLOWED_SPEEDS)} or 'max'")

        async with self._lock:
            if not self._bars or self._cursor < 0:
                raise RuntimeError("Replay has not been started")
            if self.state == ReplayState.FINISHED:
                raise RuntimeError("Replay is finished; restart to play again")
            self._generation += 1
            generation = self._generation
            self._cancel_play_task()
            self.speed = normalized
            self.state = ReplayState.PLAYING
            self._play_task = asyncio.create_task(self._run_scheduler(generation))
            snapshot = self.snapshot()
        await self._publish(snapshot)
        return snapshot

    def _advance_locked(self, count: int) -> list[Bar]:
        if self._cursor >= len(self._bars) - 1:
            self.state = ReplayState.FINISHED
            return []
        end = min(len(self._bars) - 1, self._cursor + count)
        bars = self._bars[self._cursor + 1 : end + 1]
        self._cursor = end
        if self._cursor >= len(self._bars) - 1:
            self.state = ReplayState.FINISHED
        return bars

    @staticmethod
    def _bars_event(bars: list[Bar]) -> dict[str, Any]:
        if len(bars) == 1:
            return {"type": "bar", "bar": bars[0].to_wire()}
        return {"type": "bars_batch", "bars": [bar.to_wire() for bar in bars]}

    async def _run_scheduler(self, generation: int) -> None:
        last = time.monotonic()
        carry = 0.0
        try:
            while True:
                await asyncio.sleep(0.01)
                event: dict[str, Any] | None = None
                snapshot: dict[str, Any] | None = None
                async with self._lock:
                    if generation != self._generation or self.state != ReplayState.PLAYING:
                        return
                    now = time.monotonic()
                    elapsed = now - last
                    last = now
                    if self.speed == "max":
                        due = min(500, len(self._bars) - self._cursor - 1)
                    else:
                        carry += elapsed * int(self.speed)
                        due = int(carry)
                        if due:
                            carry -= due
                    if due <= 0:
                        continue
                    bars = self._advance_locked(due)
                    if bars:
                        event = self._bars_event(bars)
                    if self.state == ReplayState.FINISHED:
                        snapshot = self.snapshot()
                if event:
                    await self._publish(event)
                if snapshot:
                    await self._publish(snapshot)
                    return
        except asyncio.CancelledError:
            return

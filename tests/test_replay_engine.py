from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pandas as pd

from futureview.replay.datastore import ReplayDataStore
from futureview.replay.engine import ReplayEngine


def _fixture_store(tmp_path: Path) -> ReplayDataStore:
    out = tmp_path / "parquet" / "5m"
    out.mkdir(parents=True)
    path = out / "sample.parquet"
    times = pd.date_range("2024-06-10 13:30:00+00:00", periods=20, freq="5min")
    frame = pd.DataFrame({
        "timestamp": times,
        "symbol": "MESM24",
        "instrument_id": 1,
        "open": range(100, 120),
        "high": range(101, 121),
        "low": range(99, 119),
        "close": [x + 0.5 for x in range(100, 120)],
        "volume": range(1000, 1020),
    })
    frame.to_parquet(path, index=False)
    manifest = {
        "files": [{
            "output_5m": str(path),
            "symbols": ["MESM24"],
        }]
    }
    manifest_path = tmp_path / "processed_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return ReplayDataStore(manifest_path)


def test_datastore_contract_info(tmp_path: Path) -> None:
    store = _fixture_store(tmp_path)
    assert store.contracts() == ["MESM24"]
    info = store.contract_info("MESM24")
    assert info["bars"] == 20
    assert info["first"].startswith("2024-06-10T13:30:00")


def test_replay_is_forward_only_and_no_lookahead(tmp_path: Path) -> None:
    store = _fixture_store(tmp_path)
    bars = store.load_contract("MESM24")

    async def run() -> None:
        engine = ReplayEngine(store)
        started = await engine.start("MESM24", bars[10].timestamp, warmup=3)
        assert started["future_data_included"] is False
        assert len(started["warmup"]) == 4
        assert started["warmup"][-1]["timestamp"] == bars[10].timestamp.isoformat()
        assert all(x["time"] <= int(bars[10].timestamp.timestamp()) for x in started["warmup"])

        event = await engine.step()
        assert event["type"] == "bar"
        assert event["bar"]["timestamp"] == bars[11].timestamp.isoformat()

        restarted = await engine.restart()
        assert restarted["cursor"] == bars[10].timestamp.isoformat()
        assert restarted["warmup"][-1]["timestamp"] == bars[10].timestamp.isoformat()

    asyncio.run(run())


def test_high_speed_play_batches_without_skipping_order(tmp_path: Path) -> None:
    store = _fixture_store(tmp_path)
    bars = store.load_contract("MESM24")

    async def run() -> None:
        engine = ReplayEngine(store)
        await engine.start("MESM24", bars[5].timestamp, warmup=1)
        queue = engine.subscribe()
        await engine.play(100)
        released = []
        while not released:
            event = await asyncio.wait_for(queue.get(), timeout=0.5)
            if event["type"] == "bar":
                released = [event["bar"]]
            elif event["type"] == "bars_batch":
                released = event["bars"]
        await engine.pause()
        times = [x["time"] for x in released]
        assert times == sorted(times)
        assert times[0] == int(bars[6].timestamp.timestamp())
        engine.unsubscribe(queue)

    asyncio.run(run())

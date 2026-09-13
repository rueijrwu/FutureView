from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pandas as pd

from futureview_replay.engine import ReplayEngine
from futureview_replay.store import BarStore


def store(tmp_path: Path) -> BarStore:
    p = tmp_path / "parquet" / "5m"
    p.mkdir(parents=True)
    f = p / "x.parquet"
    ts = pd.date_range("2024-06-10T13:30:00Z", periods=40, freq="5min")
    pd.DataFrame({"timestamp":ts,"symbol":"MESM24","instrument_id":1,"open":range(40),"high":[x+1 for x in range(40)],"low":[x-1 for x in range(40)],"close":[x+.5 for x in range(40)],"volume":[100+x for x in range(40)]}).to_parquet(f,index=False)
    (tmp_path / "manifest.json").write_text(json.dumps({"product":"MES","files":[{"five_minute":"parquet/5m/x.parquet","symbols":["MESM24"]}]}))
    return BarStore(tmp_path / "manifest.json")


def test_no_lookahead_and_step(tmp_path: Path) -> None:
    s=store(tmp_path); bars=s.bars("MESM24")
    async def run():
        e=ReplayEngine({"MES": s}); r=await e.start("MES",bars[10].timestamp,3)
        assert r["contract"] == "MESM24"
        assert r["contract_selection"]["reason"] == "nearest_expiry_fallback"
        assert r["future_data_included"] is False
        assert r["warmup"][-1]["timestamp"]==bars[10].timestamp.isoformat()
        q=e.subscribe(); snap=await e.step(); assert snap["cursor"]==bars[11].timestamp.isoformat()
        first=await asyncio.wait_for(q.get(),.2); assert first["type"]=="bar" and first["bar"]["timestamp"]==bars[11].timestamp.isoformat()
    asyncio.run(run())


def test_100x_preserves_order(tmp_path: Path) -> None:
    s=store(tmp_path); bars=s.bars("MESM24")
    async def run():
        e=ReplayEngine({"MES": s}); await e.start("MES",bars[5].timestamp,1); q=e.subscribe(); await e.play(100)
        seen=[]
        while not seen:
            x=await asyncio.wait_for(q.get(),.5)
            if x["type"]=="bar": seen=[x["bar"]]
            elif x["type"]=="bars_batch": seen=x["bars"]
        await e.pause(); assert [x["time"] for x in seen]==sorted(x["time"] for x in seen)
        assert seen[0]["timestamp"]==bars[6].timestamp.isoformat()
    asyncio.run(run())

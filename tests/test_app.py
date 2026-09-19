from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from futureview_replay.app import create_app


def test_health_and_index(tmp_path: Path) -> None:
    p=tmp_path/"parquet"/"1m"; p.mkdir(parents=True); f=p/"x.parquet"
    ts=pd.date_range("2024-06-10T13:30:00Z",periods=4,freq="1min")
    pd.DataFrame({"timestamp":ts,"symbol":"MESM24","instrument_id":1,"open":[1,2,3,4],"high":[2,3,4,5],"low":[0,1,2,3],"close":[1.5,2.5,3.5,4.5],"volume":[10,11,12,13]}).to_parquet(f,index=False)
    m=tmp_path/"manifest.json"; m.write_text(json.dumps({"product":"MES","files":[{"one_minute":"parquet/1m/x.parquet","symbols":["MESM24"]}]}))
    with TestClient(create_app(m)) as c:
        health=c.get("/api/health").json()
        assert health["ok"] is True and health["contracts"]==1 and health["product"]=="MES"
        replay_range=c.get("/api/replay/range").json()
        assert replay_range["product"] == "MES"
        assert "first_time" in replay_range and "last_time" in replay_range
        started=c.post("/api/replay/start",json={"product":"MES","start":ts[1].isoformat(),"warmup":1})
        assert started.status_code == 200
        assert started.json()["contract"] == "MESM24"
        index=c.get("/")
        assert index.status_code==200
        assert "/chart-tools.js" in index.text
        assert 'data-tool="sma20"' in index.text
        assert 'data-tool="hline"' in index.text
        assert 'id="random-btn"' in index.text

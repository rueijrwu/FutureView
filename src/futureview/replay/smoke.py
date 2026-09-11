from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from futureview.replay.datastore import ReplayDataStore
from futureview.replay.engine import ReplayEngine


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="data/databento/mes/processed_manifest.json")
    args = parser.parse_args()

    store = ReplayDataStore(Path(args.manifest))
    contracts = store.contracts()
    if not contracts:
        raise SystemExit("No replay contracts found")
    contract = contracts[0]
    bars = store.load_contract(contract)
    if len(bars) < 12:
        raise SystemExit(f"Not enough bars for replay smoke: {len(bars)}")

    async def run() -> None:
        engine = ReplayEngine(store)
        started = await engine.start(contract, bars[10].timestamp, warmup=5)
        assert started["future_data_included"] is False
        assert started["warmup"][-1]["timestamp"] == bars[10].timestamp.isoformat()
        event = await engine.step()
        assert event["bar"]["timestamp"] == bars[11].timestamp.isoformat()
        assert engine.snapshot()["cursor"] == bars[11].timestamp.isoformat()
        print(
            "MES_REPLAY_OK",
            f"contract={contract}",
            f"bars={len(bars)}",
            f"start={bars[10].timestamp.isoformat()}",
            f"next={bars[11].timestamp.isoformat()}",
        )

    asyncio.run(run())


if __name__ == "__main__":
    main()

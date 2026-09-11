from __future__ import annotations

import argparse
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from futureview.replay.datastore import ReplayDataStore
from futureview.replay.engine import ReplayEngine


class StartRequest(BaseModel):
    contract: str
    start: datetime
    warmup: int = Field(default=300, ge=0, le=5000)


class SpeedRequest(BaseModel):
    speed: int | str


def create_app(manifest_path: str | Path = "data/databento/mes/processed_manifest.json") -> FastAPI:
    datastore = ReplayDataStore(manifest_path)
    engine = ReplayEngine(datastore)
    static_dir = Path(__file__).with_name("static")

    app = FastAPI(title="FutureView MES Replay", version="0.1.0")
    app.state.replay_engine = engine
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "contracts": len(engine.contracts())}

    @app.get("/api/contracts")
    async def contracts() -> dict[str, Any]:
        return {"contracts": engine.contracts()}

    @app.get("/api/contracts/{contract}")
    async def contract_info(contract: str) -> dict[str, Any]:
        try:
            return datastore.contract_info(contract)
        except (KeyError, ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/replay/state")
    async def state() -> dict[str, Any]:
        return engine.snapshot()

    @app.post("/api/replay/start")
    async def start(request: StartRequest) -> dict[str, Any]:
        try:
            return await engine.start(request.contract, request.start, warmup=request.warmup)
        except (KeyError, ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/replay/step")
    async def step() -> dict[str, Any]:
        try:
            return await engine.step()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/replay/play")
    async def play(request: SpeedRequest) -> dict[str, Any]:
        try:
            return await engine.play(request.speed)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/replay/pause")
    async def pause() -> dict[str, Any]:
        return await engine.pause()

    @app.post("/api/replay/restart")
    async def restart() -> dict[str, Any]:
        try:
            return await engine.restart()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.websocket("/ws/replay")
    async def websocket_replay(websocket: WebSocket) -> None:
        await websocket.accept()
        queue = engine.subscribe()
        await websocket.send_json(engine.snapshot())
        try:
            while True:
                event = await queue.get()
                await websocket.send_json(event)
        except WebSocketDisconnect:
            pass
        finally:
            engine.unsubscribe(queue)

    return app


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local FutureView MES bar-replay application.")
    parser.add_argument("--manifest", default="data/databento/mes/processed_manifest.json")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-open-browser", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    app = create_app(args.manifest)
    url = f"http://{args.host}:{args.port}"
    if not args.no_open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()

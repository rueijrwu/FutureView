from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from futureview_replay.engine import ReplayEngine
from futureview_replay.store import BarStore


class StartRequest(BaseModel):
    contract: str
    start: datetime
    warmup: int = Field(default=300, ge=0, le=5000)


class PlayRequest(BaseModel):
    speed: int | str


def create_app(manifest: str | Path) -> FastAPI:
    store = BarStore(manifest)
    engine = ReplayEngine(store)
    static = Path(__file__).with_name("static")
    app = FastAPI(title="FutureView Replay", version="0.2.0")
    app.state.engine = engine
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(static / "index.html")

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "contracts": len(store.contracts()), "product": store.manifest.get("product")}

    @app.get("/api/contracts")
    async def contracts() -> dict[str, Any]:
        return {"product": store.manifest.get("product"), "contracts": store.contracts()}

    @app.get("/api/contracts/{contract}")
    async def info(contract: str) -> dict[str, object]:
        try:
            return store.info(contract)
        except (KeyError, ValueError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/replay/state")
    async def state() -> dict[str, Any]:
        return engine.snapshot()

    @app.post("/api/replay/start")
    async def start(req: StartRequest) -> dict[str, Any]:
        try:
            return await engine.start(req.contract, req.start, req.warmup)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/replay/step")
    async def step() -> dict[str, Any]:
        try:
            return await engine.step()
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/replay/play")
    async def play(req: PlayRequest) -> dict[str, Any]:
        try:
            return await engine.play(req.speed)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/replay/pause")
    async def pause() -> dict[str, Any]:
        return await engine.pause()

    @app.post("/api/replay/restart")
    async def restart() -> dict[str, Any]:
        try:
            return await engine.restart()
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.websocket("/ws/replay")
    async def ws(ws: WebSocket) -> None:
        await ws.accept()
        q = engine.subscribe()
        await ws.send_json(engine.snapshot())
        try:
            while True:
                await ws.send_json(await q.get())
        except WebSocketDisconnect:
            pass
        finally:
            engine.unsubscribe(q)

    return app

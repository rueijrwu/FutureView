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
    product: str
    start: datetime
    warmup: int = Field(default=300, ge=0, le=5000)


class PlayRequest(BaseModel):
    speed: int | str


def create_app(runtime_dir: str | Path = "runtime") -> FastAPI:
    runtime_path = Path(runtime_dir)
    stores: dict[str, BarStore] = {}
    
    if runtime_path.is_file():
        store = BarStore(runtime_path)
        stores[store.product.upper()] = store
        parent = runtime_path.parent
        search_root = parent.parent if parent.name in {"ES", "MES"} else parent
        if search_root.is_dir():
            for p in search_root.rglob("manifest.json"):
                if p.resolve() != runtime_path.resolve():
                    try:
                        s = BarStore(p)
                        stores[s.product.upper()] = s
                    except Exception:
                        pass
    elif runtime_path.is_dir():
        for p in runtime_path.rglob("manifest.json"):
            try:
                store = BarStore(p)
                stores[store.product.upper()] = store
            except Exception:
                pass
    elif Path("runtime").is_dir():
        for p in Path("runtime").rglob("manifest.json"):
            try:
                store = BarStore(p)
                stores[store.product.upper()] = store
            except Exception:
                pass

    engine = ReplayEngine(stores)
    static = Path(__file__).with_name("static")
    app = FastAPI(title="FutureView Replay", version="0.3.0")
    app.state.engine = engine
    app.mount("/static", StaticFiles(directory=static), name="static")

    def get_store(product: str | None = None) -> BarStore:
        if not stores:
            raise HTTPException(503, "No replay data available")
        if product is None:
            return next(iter(stores.values()))
        prod = product.upper()
        if prod not in stores:
            raise HTTPException(404, f"Product {product} not found. Available products: {list(stores.keys())}")
        return stores[prod]

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(static / "index.html")

    @app.get("/api/health")
    async def health(product: str | None = None) -> dict[str, Any]:
        if not stores:
            return {"ok": False, "contracts": 0, "product": None}
        prod = product.upper() if product else None
        if prod and prod in stores:
            store = stores[prod]
            return {"ok": True, "contracts": len(store.contracts()), "product": store.manifest.get("product")}
        elif prod and prod not in stores:
            return {"ok": False, "contracts": 0, "product": product}
        else:
            store = next(iter(stores.values()))
            return {"ok": True, "contracts": len(store.contracts()), "product": store.manifest.get("product")}

    @app.get("/api/contracts")
    async def contracts(product: str | None = None) -> dict[str, Any]:
        store = get_store(product)
        return {"product": store.manifest.get("product"), "contracts": store.contracts()}

    @app.get("/api/replay/range")
    async def replay_range(product: str | None = None) -> dict[str, object]:
        store = get_store(product)
        return store.replay_range()

    @app.get("/api/contracts/{contract}")
    async def info(contract: str, product: str | None = None) -> dict[str, object]:
        try:
            store = get_store(product)
            return store.info(contract)
        except (KeyError, ValueError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/replay/state")
    async def state() -> dict[str, Any]:
        return engine.snapshot()

    @app.post("/api/replay/start")
    async def start(req: StartRequest) -> dict[str, Any]:
        try:
            return await engine.start(req.product, req.start, req.warmup)
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

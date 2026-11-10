"""FastAPI app – gắn các router REST dưới tiền tố `/api` và WebSocket `/ws` (spec mục 9)."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from api import ws
from api.routers import (
    alerts,
    auth,
    commands,
    devices,
    experiments,
    greenhouses,
    models,
    push,
    zones,
)
from core.config import get_settings
from core.db import engine
from core.log import setup_logging
from core.pubsub import CHANNEL_WS, listen_loop

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Khởi tạo vòng lặp lắng nghe PostgreSQL ws_events để fan-out WebSocket."""
    settings = get_settings()
    stop_event = asyncio.Event()
    listener_task = asyncio.create_task(
        listen_loop(settings.database_url, CHANNEL_WS, ws.manager.on_ws_event, stop_event)
    )
    try:
        yield
    finally:
        stop_event.set()
        listener_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await listener_task


app = FastAPI(
    title="GreenHub API",
    version="0.3.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# WebSocket endpoint (/ws và /api/ws)
app.include_router(ws.router)

# REST API endpoints (/api/*)
app.include_router(auth.router, prefix="/api")
app.include_router(greenhouses.router, prefix="/api")
app.include_router(devices.router, prefix="/api")
app.include_router(zones.router, prefix="/api")
app.include_router(commands.router, prefix="/api")
app.include_router(alerts.router, prefix="/api")
app.include_router(push.router, prefix="/api")
app.include_router(models.router, prefix="/api")
app.include_router(experiments.router, prefix="/api")


@app.get("/api/health", tags=["system"])
async def health() -> dict:
    """Healthcheck cho Docker/Caddy: kiểm tra kết nối DB."""
    db_ok = True
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "db": db_ok}

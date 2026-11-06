"""FastAPI app – gắn các router REST dưới tiền tố `/api` (spec mục 9)."""

from fastapi import FastAPI
from sqlalchemy import text

from api.routers import auth, commands, devices, greenhouses, zones
from core.db import engine
from core.log import setup_logging

setup_logging()

app = FastAPI(
    title="GreenHub API",
    version="0.2.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.include_router(auth.router, prefix="/api")
app.include_router(greenhouses.router, prefix="/api")
app.include_router(devices.router, prefix="/api")
app.include_router(zones.router, prefix="/api")
app.include_router(commands.router, prefix="/api")


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

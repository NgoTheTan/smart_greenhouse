"""FastAPI app. Router nghiệp vụ được thêm dần theo milestone (api/routers/)."""

from fastapi import FastAPI
from sqlalchemy import text

from core.db import engine
from core.log import setup_logging

setup_logging()

app = FastAPI(
    title="GreenHub API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)


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


"""PostgreSQL LISTEN/NOTIFY dùng chung cho ws_events và worker_events (spec 3.2)."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("core.pubsub")

CHANNEL_WS = "ws_events"
CHANNEL_WORKER = "worker_events"


def _asyncpg_dsn(sqlalchemy_url: str) -> str:
    if sqlalchemy_url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + sqlalchemy_url.removeprefix("postgresql+asyncpg://")
    return sqlalchemy_url


async def pg_notify(session: AsyncSession, channel: str, payload: dict[str, Any]) -> None:
    """Gửi thông báo trong cùng transaction hiện tại (chỉ phát khi commit thành công)."""
    data = json.dumps(payload, separators=(",", ":"), default=str)
    await session.execute(text("SELECT pg_notify(:ch, :msg)"), {"ch": channel, "msg": data})


async def listen_loop(
    database_url: str,
    channel: str,
    on_event: Callable[[dict[str, Any]], Awaitable[None]],
    stop_event: asyncio.Event | None = None,
) -> None:
    """Giữ kết nối asyncpg riêng để LISTEN kênh `channel`, tự kết nối lại khi DB ngắt."""
    dsn = _asyncpg_dsn(database_url)
    backoff = 1
    queue: asyncio.Queue[str] = asyncio.Queue()

    def _callback(_conn: Any, _pid: int, _channel: str, payload: str) -> None:
        queue.put_nowait(payload)

    while stop_event is None or not stop_event.is_set():
        conn: asyncpg.Connection | None = None
        try:
            conn = await asyncpg.connect(dsn, timeout=2.0)
            await conn.add_listener(channel, _callback)
            log.info("LISTEN %s connected", channel)
            backoff = 1
            while stop_event is None or not stop_event.is_set():
                try:
                    raw = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    # Ping nhẹ giữ kết nối sống
                    await conn.execute("SELECT 1")
                    continue
                try:
                    data = json.loads(raw)
                    await on_event(data)
                except Exception:  # noqa: BLE001
                    log.exception("Lỗi xử lý sự kiện từ kênh %s: %s", channel, raw)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("LISTEN %s mất kết nối (%s); thử lại sau %ss", channel, e, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
        finally:
            if conn is not None and not conn.is_closed():
                await conn.close()


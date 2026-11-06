"""APScheduler định kỳ của worker: quét timeout lệnh, gửi bù lệnh/cfg, hết hạn manual (spec 6)."""

import logging
from collections.abc import Callable

import aiomqtt
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.db import SessionLocal
from worker.commands import (
    dispatch_pending_commands,
    expire_manual_modes,
    expire_timed_out_commands,
)
from worker.shadow import ShadowPublisher

log = logging.getLogger("worker.scheduler")


def create_worker_scheduler(
    get_mqtt_client: Callable[[], aiomqtt.Client | None],
    shadow_pub: ShadowPublisher,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    async def _tick_5s() -> None:
        client = get_mqtt_client()
        async with SessionLocal() as session:
            try:
                await expire_timed_out_commands(session)
                await expire_manual_modes(session)
                if client is not None:
                    await dispatch_pending_commands(client, session)
                    await shadow_pub.sync_unsynced(client, session)
                await session.commit()
            except Exception:  # noqa: BLE001
                await session.rollback()
                log.exception("Lỗi trong tick 5s của worker")

    scheduler.add_job(_tick_5s, "interval", seconds=5, id="worker_tick_5s", max_instances=1)
    return scheduler

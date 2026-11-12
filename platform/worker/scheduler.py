"""APScheduler định kỳ: timeout lệnh, bù lệnh/cfg, hết hạn manual, rules, AI (spec 6, 8)."""

import logging
from collections.abc import Callable

import aiomqtt
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.db import SessionLocal
from worker.alerts import escalate_alerts
from worker.commands import (
    dispatch_pending_commands,
    expire_manual_modes,
    expire_timed_out_commands,
)
from worker.inference import InferenceService
from worker.rules import RuleEngine
from worker.shadow import ShadowPublisher

log = logging.getLogger("worker.scheduler")


def create_worker_scheduler(
    get_mqtt_client: Callable[[], aiomqtt.Client | None],
    shadow_pub: ShadowPublisher,
    rule_engine: RuleEngine | None = None,
    inference_service: InferenceService | None = None,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    async def _tick_5s() -> None:
        client = get_mqtt_client()
        async with SessionLocal() as session:
            try:
                await expire_timed_out_commands(session)
                await expire_manual_modes(session)
                if rule_engine is not None:
                    await rule_engine.tick_5s(session, client)
                await escalate_alerts(session)
                if client is not None:
                    await dispatch_pending_commands(client, session)
                    await shadow_pub.sync_unsynced(client, session)
                await session.commit()
            except Exception:  # noqa: BLE001
                await session.rollback()
                log.exception("Lỗi trong tick 5s của worker")

    scheduler.add_job(_tick_5s, "interval", seconds=5, id="worker_tick_5s", max_instances=1)

    if inference_service is not None:

        async def _tick_60s() -> None:
            async with SessionLocal() as session:
                try:
                    await inference_service.run_cycle(session)
                    await session.commit()
                except Exception:  # noqa: BLE001
                    await session.rollback()
                    log.exception("Lỗi trong chu kỳ suy luận 60s của worker")

        scheduler.add_job(
            _tick_60s,
            "interval",
            seconds=60,
            id="worker_inference_60s",
            max_instances=1,
        )

        async def _tick_10m() -> None:
            async with SessionLocal() as session:
                try:
                    await inference_service.check_and_reload_active_model(session)
                    await session.commit()
                except Exception:  # noqa: BLE001
                    await session.rollback()
                    log.exception("Lỗi trong chu kỳ đồng bộ model & yield_samples 10m")

        scheduler.add_job(
            _tick_10m,
            "interval",
            minutes=10,
            id="worker_model_sync_10m",
            max_instances=1,
        )

    return scheduler

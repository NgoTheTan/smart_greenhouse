"""Điểm vào tiến trình worker: MQTT ingest, command/ack, device shadow/cfg và scheduler (spec 6)."""

import asyncio
import logging
import sys
import uuid
from typing import Any

import aiomqtt

from core.config import get_settings
from core.db import SessionLocal
from core.log import setup_logging
from core.pubsub import CHANNEL_WORKER, listen_loop
from worker.commands import dispatch_pending_commands, handle_ack
from worker.ingest import IngestService
from worker.scheduler import create_worker_scheduler
from worker.shadow import ShadowPublisher

log = logging.getLogger("worker")

# Các topic gateway -> cloud (spec 6.1)
SUBSCRIPTIONS = [
    "gh/+/+/telemetry/+",
    "gh/+/+/status",
    "gh/+/+/event",
    "gh/+/+/discovery",
    "gh/+/+/ack/+",
]


def parse_gh_topic(topic: str) -> tuple[uuid.UUID, uuid.UUID, list[str]] | None:
    """Tách `gh/{farm_id}/{greenhouse_id}/<rest...>` thành UUID và phần hậu tố."""
    parts = topic.split("/")
    if len(parts) < 4 or parts[0] != "gh":
        return None
    try:
        farm_id = uuid.UUID(parts[1])
        gh_id = uuid.UUID(parts[2])
    except ValueError:
        return None
    return farm_id, gh_id, parts[3:]


class WorkerRuntime:
    def __init__(self) -> None:
        self.ingest = IngestService()
        self.shadow_pub = ShadowPublisher()
        self._mqtt_client: aiomqtt.Client | None = None

    def get_mqtt_client(self) -> aiomqtt.Client | None:
        return self._mqtt_client

    async def on_worker_event(self, event: dict[str, Any]) -> None:
        """Xử lý thông báo tức thời từ tiến trình `api` qua kênh PostgreSQL `worker_events`."""
        client = self._mqtt_client
        if client is None:
            return
        kind = event.get("type")
        async with SessionLocal() as session:
            try:
                if kind == "command_created":
                    cmd_id = uuid.UUID(str(event["cmd_id"]))
                    await dispatch_pending_commands(client, session, command_id=cmd_id)
                elif kind == "cfg_updated":
                    gh_id = uuid.UUID(str(event["greenhouse_id"]))
                    await self.shadow_pub.publish_cfg(client, session, gh_id, force=True)
                await session.commit()
            except Exception:  # noqa: BLE001
                await session.rollback()
                log.exception("Lỗi xử lý worker_event: %s", event)

    async def dispatch_mqtt_message(self, topic: str, payload: bytes) -> None:
        parsed = parse_gh_topic(topic)
        if parsed is None:
            return
        farm_id, gh_id, rest = parsed

        async with SessionLocal() as session:
            try:
                if len(rest) == 2 and rest[0] == "telemetry":
                    await self.ingest.handle_telemetry(
                        session, farm_id, gh_id, int(rest[1]), payload
                    )
                elif rest == ["status"]:
                    await self.ingest.handle_status(session, farm_id, gh_id, payload)
                elif rest == ["discovery"]:
                    await self.ingest.handle_discovery(session, farm_id, gh_id, payload)
                elif rest == ["event"]:
                    await self.ingest.handle_event(session, farm_id, gh_id, payload)
                elif len(rest) == 2 and rest[0] == "ack":
                    await handle_ack(session, farm_id, gh_id, uuid.UUID(rest[1]), payload)
                await session.commit()
            except Exception:  # noqa: BLE001
                await session.rollback()
                log.exception("Lỗi xử lý gói MQTT trên topic %s", topic)

    async def run(self) -> None:
        s = get_settings()
        async with SessionLocal() as session:
            await self.ingest.warm_up(session)

        stop_event = asyncio.Event()
        listener_task = asyncio.create_task(
            listen_loop(s.database_url, CHANNEL_WORKER, self.on_worker_event, stop_event)
        )
        scheduler = create_worker_scheduler(self.get_mqtt_client, self.shadow_pub)
        scheduler.start()

        backoff = 1
        try:
            while True:
                try:
                    async with aiomqtt.Client(
                        hostname=s.mqtt_host,
                        port=s.mqtt_port,
                        username=s.mqtt_worker_user,
                        password=s.mqtt_worker_password or None,
                        identifier="greenhub-worker",
                    ) as client:
                        self._mqtt_client = client
                        self.shadow_pub.reset_cache()
                        for sub in SUBSCRIPTIONS:
                            await client.subscribe(sub, qos=1)
                        log.info("Connected to MQTT %s:%s", s.mqtt_host, s.mqtt_port)
                        backoff = 1

                        # Đồng bộ ngay các lệnh/cfg đang chờ sau khi kết nối lại
                        async with SessionLocal() as session:
                            await dispatch_pending_commands(client, session)
                            await self.shadow_pub.sync_unsynced(client, session)
                            await session.commit()

                        async for msg in client.messages:
                            await self.dispatch_mqtt_message(str(msg.topic), bytes(msg.payload))
                except aiomqtt.MqttError as e:
                    self._mqtt_client = None
                    log.warning("MQTT error: %s; reconnect in %ss", e, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
        finally:
            self._mqtt_client = None
            stop_event.set()
            scheduler.shutdown(wait=False)
            listener_task.cancel()


async def run() -> None:
    await WorkerRuntime().run()


def main() -> None:
    setup_logging()
    # aiomqtt cần SelectorEventLoop trên Windows (khi chạy worker ngoài Docker)
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(run(), loop_factory=loop_factory)


if __name__ == "__main__":
    main()

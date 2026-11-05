"""Điểm vào worker: kết nối MQTT, subscribe các topic gateway và (tạm thời) log bản tin.

Các module ingest/rules/commands/alerts/notify/inference/scheduler sẽ được gắn vào từ M2.
"""

import asyncio
import logging
import sys

import aiomqtt

from core.config import get_settings
from core.log import setup_logging

log = logging.getLogger("worker")

# spec 6.1
SUBSCRIPTIONS = [
    "gh/+/+/telemetry/+",
    "gh/+/+/status",
    "gh/+/+/event",
    "gh/+/+/discovery",
    "gh/+/+/ack/+",
]


async def run() -> None:
    s = get_settings()
    backoff = 1
    while True:
        try:
            async with aiomqtt.Client(
                hostname=s.mqtt_host,
                port=s.mqtt_port,
                username=s.mqtt_worker_user,
                password=s.mqtt_worker_password,
                identifier="greenhub-worker",
            ) as client:
                for topic in SUBSCRIPTIONS:
                    await client.subscribe(topic, qos=1)
                log.info("connected to MQTT %s:%s", s.mqtt_host, s.mqtt_port)
                backoff = 1
                async for msg in client.messages:
                    log.info("%s %s", msg.topic, msg.payload[:200])
        except aiomqtt.MqttError as e:
            log.warning("MQTT error: %s; reconnect in %ss", e, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


def main() -> None:
    setup_logging()
    # aiomqtt cần SelectorEventLoop trên Windows (khi chạy worker ngoài Docker)
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(run(), loop_factory=loop_factory)


if __name__ == "__main__":
    main()

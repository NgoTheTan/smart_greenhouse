"""Provisioning MQTT qua Mosquitto Dynamic Security ($CONTROL/dynamic-security/v1 – spec 5, 6.2)."""

import asyncio
import json
import logging
import secrets
import sys
import uuid
from typing import Any

import aiomqtt

from core.config import get_settings

log = logging.getLogger("api.provisioning")

DYNSEC_REQ_TOPIC = "$CONTROL/dynamic-security/v1"
DYNSEC_RESP_TOPIC = "$CONTROL/dynamic-security/v1/response"


def build_gateway_dynsec_commands(
    farm_id: uuid.UUID,
    greenhouse_id: uuid.UUID,
    mqtt_username: str,
    mqtt_password: str,
) -> list[dict[str, Any]]:
    """Sinh danh sách lệnh Dynamic Security khoá chặt ACL của gateway vào `gh/{farm}/{gh}/...`."""
    prefix = f"gh/{farm_id}/{greenhouse_id}"
    role_name = f"gw-{greenhouse_id}"
    acls = [
        # Quyền đọc: cmd/# và cfg
        {"acltype": "subscribePattern", "topic": f"{prefix}/cmd/#", "allow": True},
        {"acltype": "publishClientReceive", "topic": f"{prefix}/cmd/#", "allow": True},
        {"acltype": "subscribeLiteral", "topic": f"{prefix}/cfg", "allow": True},
        {"acltype": "subscribePattern", "topic": f"{prefix}/cfg", "allow": True},
        {"acltype": "publishClientReceive", "topic": f"{prefix}/cfg", "allow": True},
        # Quyền ghi: telemetry/#, status, event, discovery, ack/#
        {"acltype": "publishClientSend", "topic": f"{prefix}/telemetry/#", "allow": True},
        {"acltype": "publishClientSend", "topic": f"{prefix}/status", "allow": True},
        {"acltype": "publishClientSend", "topic": f"{prefix}/event", "allow": True},
        {"acltype": "publishClientSend", "topic": f"{prefix}/discovery", "allow": True},
        {"acltype": "publishClientSend", "topic": f"{prefix}/ack/#", "allow": True},
    ]
    return [
        # Xoá trước nếu tồn tại để thao tác cấp lại/seed idempotent
        {"command": "deleteClient", "username": mqtt_username},
        {"command": "deleteRole", "rolename": role_name},
        {"command": "createRole", "rolename": role_name, "acls": acls},
        {
            "command": "createClient",
            "username": mqtt_username,
            "password": mqtt_password,
            "roles": [{"rolename": role_name}],
        },
    ]


async def _send_dynsec_commands(commands: list[dict[str, Any]], timeout_s: float = 8.0) -> None:
    s = get_settings()
    client_id = f"gh-api-admin-{secrets.token_hex(4)}"

    async with aiomqtt.Client(
        hostname=s.mqtt_host,
        port=s.mqtt_port,
        username=s.mqtt_admin_user,
        password=s.mqtt_admin_password or None,
        identifier=client_id,
    ) as client:
        await client.subscribe(DYNSEC_RESP_TOPIC, qos=1)
        payload = json.dumps({"commands": commands}).encode("utf-8")
        await client.publish(DYNSEC_REQ_TOPIC, payload=payload, qos=1)

        async with asyncio.timeout(timeout_s):
            async for msg in client.messages:
                body = json.loads(bytes(msg.payload))
                responses = body.get("responses", [])
                # Chỉ kiểm tra lỗi trên 2 lệnh tạo cuối (2 lệnh delete đầu cho phép not found)
                for resp in responses[-2:]:
                    if "error" in resp:
                        raise RuntimeError(f"Dynamic Security lỗi: {resp}")
                return


def _run_in_selector_loop(commands: list[dict[str, Any]]) -> None:
    loop = asyncio.SelectorEventLoop()
    try:
        loop.run_until_complete(_send_dynsec_commands(commands))
    finally:
        loop.close()


async def provision_gateway_mqtt(
    farm_id: uuid.UUID,
    greenhouse_id: uuid.UUID,
    mqtt_username: str,
    mqtt_password: str,
) -> None:
    """Tạo user + role ACL cho gateway trên Mosquitto."""
    commands = build_gateway_dynsec_commands(
        farm_id, greenhouse_id, mqtt_username, mqtt_password
    )
    loop = asyncio.get_running_loop()
    if sys.platform == "win32" and not isinstance(loop, asyncio.SelectorEventLoop):
        await asyncio.to_thread(_run_in_selector_loop, commands)
    else:
        await _send_dynsec_commands(commands)
    log.info("Provisioned MQTT user %s for gh=%s", mqtt_username, greenhouse_id)

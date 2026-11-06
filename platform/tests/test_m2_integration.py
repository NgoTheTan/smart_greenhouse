"""Kiểm thử tích hợp trọn vòng Milestone M2 trên Docker stack thật (spec mục 15).

Tự động skip nếu Docker stack (API 127.0.0.1:8000 + Mosquitto TLS 127.0.0.1:8883) chưa chạy.
Chạy trực tiếp:
    .venv\\Scripts\\pytest.exe -v -m integration
"""

import asyncio
import contextlib
import json
import socket
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiomqtt
import httpx
import pytest

from tools.seed_dev import seed
from tools.simulator.gateway_client import GatewaySafetyEngine, make_tls_context

REPO_ROOT = Path(__file__).resolve().parents[2]
CA_CERT = REPO_ROOT / "deploy" / "certs" / "ca.crt"

_LWT_HELPER_CODE = """
import asyncio, pathlib, sys
import aiomqtt
from tools.simulator.gateway_client import make_tls_context

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

username, password, prefix, ca_path = sys.argv[1:5]
ca = pathlib.Path(ca_path)
tls_ctx = make_tls_context(ca, insecure=not ca.exists())
will = aiomqtt.Will(topic=f"{prefix}/status", payload=b'{"online":false}', qos=1, retain=True)

async def main() -> None:
    async with aiomqtt.Client(
        hostname="127.0.0.1",
        port=8883,
        username=username,
        password=password,
        identifier=f"lwt-{username}",
        tls_context=tls_ctx,
        will=will,
        keepalive=5,
    ) as client:
        await client.publish(
            f"{prefix}/status",
            payload=b'{"online":true}',
            qos=1,
            retain=True,
        )
        print("READY", flush=True)
        await asyncio.sleep(60)

asyncio.run(main())
"""


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (_port_open("127.0.0.1", 8000) and _port_open("127.0.0.1", 8883)),
        reason="Cần chạy Docker stack dev (127.0.0.1:8000 & 127.0.0.1:8883) để chạy test tích hợp",
    ),
]


async def _wait_until(predicate, timeout_s: float = 8.0, step_s: float = 0.25):
    deadline = asyncio.get_running_loop().time() + timeout_s
    last_val = None
    while asyncio.get_running_loop().time() < deadline:
        last_val = await predicate()
        if last_val:
            return last_val
        await asyncio.sleep(step_s)
    raise AssertionError(f"Timeout chờ điều kiện sau {timeout_s}s; giá trị cuối: {last_val}")


async def test_m2_end_to_end_pipeline() -> None:
    await seed()

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000/api", timeout=10.0) as http:
        login_res = await http.post(
            "/auth/login", json={"email": "owner@greenhub.vn", "password": "greenhub123"}
        )
        assert login_res.status_code == 200
        headers = {"Authorization": f"Bearer {login_res.json()['access_token']}"}

        # 1. Tạo nhà kính & cấp phát gateway mới qua Dynamic Security
        gh_res = await http.post(
            "/greenhouses",
            headers=headers,
            json={"name": f"ITest GH {uuid.uuid4().hex[:6]}", "location": "Test"},
        )
        assert gh_res.status_code == 201
        gh = gh_res.json()
        gh_id = gh["id"]
        zone1_id = gh["zones"][0]["id"]
        zone2_id = gh["zones"][1]["id"]

        gw_res = await http.post(
            "/gateways",
            headers=headers,
            json={"greenhouse_id": gh_id, "is_simulated": True},
        )
        assert gw_res.status_code == 201
        cred = gw_res.json()
        prefix = f"gh/{cred['farm_id']}/{gh_id}"

        tls_ctx = make_tls_context(CA_CERT, insecure=not CA_CERT.exists())
        safety = GatewaySafetyEngine()
        received_cfgs: list[dict] = []

        will = aiomqtt.Will(
            topic=f"{prefix}/status", payload=b'{"online":false}', qos=1, retain=True
        )
        async def _run_gw_session() -> None:
            async with aiomqtt.Client(
                hostname="127.0.0.1",
                port=8883,
                username=cred["mqtt_username"],
                password=cred["mqtt_password"],
                identifier=f"itest-{cred['mqtt_username']}",
                tls_context=tls_ctx,
                will=will,
                keepalive=5,
            ) as gw_mqtt:
                await gw_mqtt.subscribe(f"{prefix}/cfg", qos=1)
                await gw_mqtt.subscribe(f"{prefix}/cmd/#", qos=1)
                await gw_mqtt.publish(
                    f"{prefix}/status",
                    payload=json.dumps(
                        {
                            "online": True,
                            "fw": "1.0.0-test",
                            "rssi": -55,
                            "cfg_version": 0,
                            "actuators": safety.actuators,
                        }
                    ).encode(),
                    qos=1,
                    retain=True,
                )

                async def _gw_loop() -> None:
                    async for msg in gw_mqtt.messages:
                        t = str(msg.topic)
                        if t.endswith("/cfg"):
                            c = json.loads(bytes(msg.payload))
                            received_cfgs.append(c)
                            safety.apply_cfg(c)
                            await gw_mqtt.publish(
                                f"{prefix}/status",
                                payload=json.dumps(
                                    {
                                        "online": True,
                                        "cfg_version": safety.cfg_version,
                                        "actuators": safety.actuators,
                                    }
                                ).encode(),
                                qos=1,
                                retain=True,
                            )
                        elif "/cmd/" in t:
                            cmd = json.loads(bytes(msg.payload))
                            ack = safety.apply_command(cmd, datetime.now(UTC), 0.0)
                            if ack is not None:
                                await gw_mqtt.publish(
                                    f"{prefix}/ack/{ack['cmd_id']}",
                                    payload=json.dumps(ack).encode(),
                                    qos=1,
                                )

                gw_task = asyncio.create_task(_gw_loop())
                try:
                    # 2. Discovery -> Pair node -> Đồng bộ cfg_version
                    rand_mac = "AA:BB:CC:" + ":".join(
                        f"{b:02X}" for b in uuid.uuid4().bytes[:3]
                    )
                    await gw_mqtt.publish(
                        f"{prefix}/discovery",
                        payload=json.dumps({"mac": rand_mac, "fw": "1.0", "rssi": -61}).encode(),
                        qos=1,
                    )

                    async def _node_discovered() -> bool:
                        r = await http.get("/nodes?status=discovered", headers=headers)
                        return any(n["mac_address"] == rand_mac for n in r.json())

                    await _wait_until(_node_discovered)

                    pair_res = await http.post(
                        f"/nodes/{rand_mac}/pair",
                        headers=headers,
                        json={"zone_id": zone1_id},
                    )
                    assert pair_res.status_code == 200

                    # 2b. Ghép node bằng MAC nhập tay (không cần discovery trước) cho Zone 2
                    manual_mac = "AA:BB:DD:" + ":".join(
                        f"{b:02X}" for b in uuid.uuid4().bytes[:3]
                    )
                    manual_pair_res = await http.post(
                        f"/nodes/{manual_mac}/pair",
                        headers=headers,
                        json={"zone_id": zone2_id},
                    )
                    assert manual_pair_res.status_code == 200
                    assert manual_pair_res.json()["status"] == "paired"

                    async def _cfg_synced() -> bool:
                        r = await http.get(f"/greenhouses/{gh_id}/config-sync", headers=headers)
                        body = r.json()
                        return body["synced"] and body["cfg_version_reported"] >= 3

                    await _wait_until(_cfg_synced)

                    # 3. Telemetry hợp lệ + lỗi rút dây -> kiểm tra readings & VPD
                    t_now = datetime.now(UTC).replace(microsecond=0)
                    await gw_mqtt.publish(
                        f"{prefix}/telemetry/1",
                        payload=json.dumps(
                            {
                                "ts": (t_now - timedelta(seconds=10)).isoformat(),
                                "zone": 1,
                                "air_t": 24.0,
                                "air_rh": 80.0,
                                "soil_m": 65.0,
                                "soil_raw": 1850,
                                "lux": 20000.0,
                                "rssi": -57,
                                "flags": 0,
                                "seq": 1,
                            }
                        ).encode(),
                        qos=1,
                    )
                    await gw_mqtt.publish(
                        f"{prefix}/telemetry/1",
                        payload=json.dumps(
                            {
                                "ts": t_now.isoformat(),
                                "zone": 1,
                                "air_t": 24.0,
                                "air_rh": 80.0,
                                "soil_m": 100.0,
                                "soil_raw": 0,
                                "lux": 20000.0,
                                "rssi": -57,
                                "flags": 0,
                                "seq": 2,
                            }
                        ).encode(),
                        qos=1,
                    )

                    async def _two_readings():
                        r = await http.get(f"/zones/{zone1_id}/readings", headers=headers)
                        pts = r.json()
                        return pts if len(pts) >= 2 else None

                    pts = await _wait_until(_two_readings)
                    assert pts[0]["quality"] == "ok" and pts[0]["vpd"] is not None
                    assert pts[1]["quality"] == "out_of_range"

                    # 4. Lệnh điều khiển + Interlock ACK cập nhật reported
                    m_res = await http.post(
                        f"/greenhouses/{gh_id}/commands",
                        headers=headers,
                        json={"actuator": "mist", "action": "on", "duration_s": 60},
                    )
                    assert m_res.status_code == 201
                    f_res = await http.post(
                        f"/greenhouses/{gh_id}/commands",
                        headers=headers,
                        json={"actuator": "fan", "action": "on", "duration_s": 60},
                    )
                    assert f_res.status_code == 201
                    fan_cmd_id = f_res.json()["id"]

                    async def _fan_applied() -> bool:
                        r = await http.get(f"/greenhouses/{gh_id}/commands", headers=headers)
                        found = next((c for c in r.json() if c["id"] == fan_cmd_id), None)
                        return bool(found and found["status"] == "applied")

                    await _wait_until(_fan_applied)
                    st_res = await http.get(
                        f"/gateways/{cred['gateway_id']}/status", headers=headers
                    )
                    rep_act = st_res.json()["reported"]["actuators"]
                    assert rep_act["fan"] == "on" and rep_act["mist"] == "off"

                    # 5. Kiểm tra endpoint DLI
                    dli_res = await http.get(f"/zones/{zone1_id}/dli", headers=headers)
                    assert dli_res.status_code == 200
                    assert dli_res.json()["sample_count"] >= 1

                finally:
                    gw_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await gw_task

        await _run_gw_session()

        # 6. Mô phỏng mất điện/rớt mạng đột ngột bằng tiến trình con bị kill (không gửi DISCONNECT)
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _LWT_HELPER_CODE,
                cred["mqtt_username"],
                cred["mqtt_password"],
                prefix,
                str(CA_CERT),
            ],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            assert proc.stdout is not None
            ready_line = await asyncio.wait_for(
                asyncio.to_thread(proc.stdout.readline), timeout=8.0
            )
            err_out = proc.stderr.read() if (not ready_line and proc.stderr) else ""
            assert "READY" in ready_line, f"Tiến trình LWT lỗi: {err_out}"

            async def _gw_marked_online() -> bool:
                r = await http.get(f"/gateways/{cred['gateway_id']}/status", headers=headers)
                return r.json()["online"] is True

            await _wait_until(_gw_marked_online, timeout_s=6.0)
        finally:
            proc.kill()
            await asyncio.to_thread(proc.wait, 5)

        async def _gw_marked_offline() -> bool:
            r = await http.get(f"/gateways/{cred['gateway_id']}/status", headers=headers)
            return r.json()["online"] is False

        await _wait_until(_gw_marked_offline, timeout_s=12.0)

        off_cmd = await http.post(
            f"/greenhouses/{gh_id}/commands",
            headers=headers,
            json={"actuator": "fan", "action": "off"},
        )
        assert off_cmd.status_code == 409
        assert off_cmd.json()["detail"] == "gateway_offline"

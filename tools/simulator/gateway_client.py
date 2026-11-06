"""Lõi Gateway giả lập: bộ quy tắc an toàn cục bộ (spec 4.3) và client MQTT TLS (spec 5, 11)."""

import asyncio
import json
import logging
import random
import ssl
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiomqtt

log = logging.getLogger("simulator.gw")

ACTUATORS = ("pump_1", "pump_2", "fan", "mist")


@dataclass
class ZoneSafetyLimits:
    irrigation_max_run_s: int = 15
    irrigation_min_gap_s: int = 90
    irrigation_max_total_s_per_hour: int = 120
    fan_max_on_s: int = 300
    mist_max_on_s: int = 300


@dataclass
class GatewaySafetyEngine:
    """Thực thi quy tắc an toàn tại biên của gateway: tự tắt, chặn duration, interlock, min_gap."""

    cfg_version: int = 0
    sample_interval_s: int = 10
    actuators: dict[str, str] = field(
        default_factory=lambda: dict.fromkeys(ACTUATORS, "off")
    )
    limits_by_pump: dict[str, ZoneSafetyLimits] = field(
        default_factory=lambda: {
            "pump_1": ZoneSafetyLimits(),
            "pump_2": ZoneSafetyLimits(),
        }
    )
    fan_max_on_s: int = 300
    mist_max_on_s: int = 300

    _off_deadlines: dict[str, float] = field(default_factory=dict)
    _last_pump_end: dict[str, float] = field(default_factory=dict)
    _pump_history: dict[str, deque[tuple[float, int]]] = field(
        default_factory=lambda: {"pump_1": deque(), "pump_2": deque()}
    )
    _seen_cmd_ids: deque[str] = field(default_factory=lambda: deque(maxlen=50))

    def apply_cfg(self, cfg: dict[str, Any]) -> bool:
        new_ver = int(cfg.get("cfg_version", 0))
        changed = new_ver != self.cfg_version
        self.cfg_version = new_ver
        for z in cfg.get("zones", []):
            pump_name = str(z.get("pump", f"pump_{z.get('zone', 1)}"))
            lim = z.get("limits", {})
            z_lim = ZoneSafetyLimits(
                irrigation_max_run_s=int(lim.get("irrigation_max_run_s", 15)),
                irrigation_min_gap_s=int(lim.get("irrigation_min_gap_s", 90)),
                irrigation_max_total_s_per_hour=int(
                    lim.get("irrigation_max_total_s_per_hour", 120)
                ),
                fan_max_on_s=int(lim.get("fan_max_on_s", 300)),
                mist_max_on_s=int(lim.get("mist_max_on_s", 300)),
            )
            self.limits_by_pump[pump_name] = z_lim
            self.fan_max_on_s = z_lim.fan_max_on_s
            self.mist_max_on_s = z_lim.mist_max_on_s
            self.sample_interval_s = int(z.get("sample_interval_s", self.sample_interval_s))
        return changed

    def tick(self, now_mono: float) -> list[str]:
        """Tự tắt các actuator đã hết thời gian chạy."""
        expired = [act for act, dl in self._off_deadlines.items() if now_mono >= dl]
        for act in expired:
            del self._off_deadlines[act]
            if self.actuators.get(act) == "on":
                self.actuators[act] = "off"
                if act in ("pump_1", "pump_2"):
                    self._last_pump_end[act] = now_mono
        return expired

    def _pump_used_last_hour(self, pump: str, now_mono: float) -> int:
        hist = self._pump_history[pump]
        while hist and now_mono - hist[0][0] > 3600.0:
            hist.popleft()
        return sum(dur for _, dur in hist)

    def apply_command(
        self, cmd: dict[str, Any], now_utc: datetime, now_mono: float
    ) -> dict[str, Any] | None:
        """Xử lý lệnh `cmd` và trả về dict ACK (hoặc `None` nếu trùng `cmd_id` đã xử lý)."""
        self.tick(now_mono)
        cmd_id = str(cmd.get("cmd_id", ""))
        if not cmd_id or cmd_id in self._seen_cmd_ids:
            return None
        self._seen_cmd_ids.append(cmd_id)

        expires_raw = cmd.get("expires_at")
        if expires_raw:
            exp_dt = datetime.fromisoformat(str(expires_raw).replace("Z", "+00:00"))
            if exp_dt <= now_utc:
                return {
                    "cmd_id": cmd_id,
                    "status": "expired",
                    "reason": None,
                    "applied_at": None,
                    "side_effects": [],
                    "state": dict(self.actuators),
                }

        actuator = str(cmd.get("actuator", ""))
        action = str(cmd.get("action", ""))
        duration_raw = cmd.get("duration_s")

        if actuator not in ACTUATORS or action not in ("on", "off"):
            return self._reject(cmd_id, "invalid")

        if action == "off":
            was_on = self.actuators[actuator] == "on"
            self.actuators[actuator] = "off"
            self._off_deadlines.pop(actuator, None)
            if was_on and actuator in ("pump_1", "pump_2"):
                self._last_pump_end[actuator] = now_mono
            return self._applied(cmd_id, now_utc, [])

        if duration_raw is None or int(duration_raw) <= 0:
            return self._reject(cmd_id, "invalid")
        req_duration = int(duration_raw)
        side_effects: list[str] = []

        # Interlock quạt - máy tạo ẩm (spec 4.3)
        if actuator == "mist" and self.actuators["fan"] == "on":
            return self._reject(cmd_id, "interlock")

        if actuator == "fan" and self.actuators["mist"] == "on":
            self.actuators["mist"] = "off"
            self._off_deadlines.pop("mist", None)
            side_effects.append("mist_off")

        # Chặn trên duration_s và kiểm tra giới hạn bơm
        if actuator in ("pump_1", "pump_2"):
            lim = self.limits_by_pump.get(actuator, ZoneSafetyLimits())
            eff_duration = min(req_duration, lim.irrigation_max_run_s)
            last_end = self._last_pump_end.get(actuator)
            if (
                self.actuators[actuator] == "off"
                and last_end is not None
                and (now_mono - last_end) < lim.irrigation_min_gap_s
            ):
                return self._reject(cmd_id, "min_gap")
            if self._pump_used_last_hour(actuator, now_mono) + eff_duration > (
                lim.irrigation_max_total_s_per_hour
            ):
                return self._reject(cmd_id, "max_total")
            self._pump_history[actuator].append((now_mono, eff_duration))
        elif actuator == "fan":
            eff_duration = min(req_duration, self.fan_max_on_s)
        else:
            eff_duration = min(req_duration, self.mist_max_on_s)

        self.actuators[actuator] = "on"
        self._off_deadlines[actuator] = now_mono + eff_duration
        return self._applied(cmd_id, now_utc, side_effects)

    def _reject(self, cmd_id: str, reason: str) -> dict[str, Any]:
        return {
            "cmd_id": cmd_id,
            "status": "rejected",
            "reason": reason,
            "applied_at": None,
            "side_effects": [],
            "state": dict(self.actuators),
        }

    def _applied(
        self, cmd_id: str, now_utc: datetime, side_effects: list[str]
    ) -> dict[str, Any]:
        return {
            "cmd_id": cmd_id,
            "status": "applied",
            "reason": None,
            "applied_at": now_utc.isoformat(),
            "side_effects": side_effects,
            "state": dict(self.actuators),
        }


def make_tls_context(ca_cert: Path | None = None, insecure: bool = False) -> ssl.SSLContext:
    ctx = ssl.create_default_context(
        cafile=str(ca_cert) if (ca_cert and ca_cert.exists()) else None
    )
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


class SimulatedGateway:
    """Mô phỏng 1 Gateway ESP32 kết nối MQTT TLS với đầy đủ LWT, status, cfg, telemetry, cmd/ack."""

    def __init__(
        self,
        *,
        farm_id: uuid.UUID,
        greenhouse_id: uuid.UUID,
        mqtt_host: str,
        mqtt_port: int,
        mqtt_username: str,
        mqtt_password: str,
        nodes_per_gw: int = 2,
        interval_s: float = 10.0,
        scenario: str = "normal",
        ca_cert: Path | None = None,
        insecure: bool = False,
    ) -> None:
        self.farm_id = farm_id
        self.greenhouse_id = greenhouse_id
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.mqtt_username = mqtt_username
        self.mqtt_password = mqtt_password
        self.nodes_per_gw = nodes_per_gw
        self.interval_s = interval_s
        self.scenario = scenario
        self.tls_ctx = make_tls_context(ca_cert, insecure=insecure)
        self.safety = GatewaySafetyEngine(sample_interval_s=int(max(1, interval_s)))
        self._start_mono = time.monotonic()
        self._seq = 0
        self._zone_state: dict[int, dict[str, float]] = {
            z: {"air_t": 25.0 + z * 0.4, "air_rh": 72.0, "soil_m": 64.0, "lux": 16000.0}
            for z in range(1, nodes_per_gw + 1)
        }

    @property
    def prefix(self) -> str:
        return f"gh/{self.farm_id}/{self.greenhouse_id}"

    def _step_physics(self, zone_idx: int, dt_s: float) -> dict[str, Any]:
        st = self._zone_state[zone_idx]
        pump_on = self.safety.actuators.get(f"pump_{zone_idx}") == "on"
        fan_on = self.safety.actuators.get("fan") == "on"
        mist_on = self.safety.actuators.get("mist") == "on"

        # Nhiệt độ & ẩm không khí
        st["air_t"] += random.uniform(-0.15, 0.15) - (0.04 * dt_s if fan_on else 0.0)
        if self.scenario == "humid_spike" or mist_on:
            st["air_rh"] = min(98.5, st["air_rh"] + 0.35 * dt_s)
        elif fan_on:
            st["air_rh"] = max(50.0, st["air_rh"] - 0.25 * dt_s)
        else:
            st["air_rh"] = min(95.0, max(45.0, st["air_rh"] + random.uniform(-0.4, 0.4)))

        # Ẩm đất
        if pump_on:
            st["soil_m"] = min(92.0, st["soil_m"] + 0.9 * dt_s)
        elif self.scenario == "dry_down":
            st["soil_m"] = max(22.0, st["soil_m"] - 0.25 * dt_s)
        else:
            st["soil_m"] = max(30.0, st["soil_m"] - 0.02 * dt_s)

        st["lux"] = max(0.0, st["lux"] + random.uniform(-300, 300))
        self._seq += 1

        soil_raw = int(2900 - (st["soil_m"] / 100.0) * (2900 - 1300))
        flags = 0
        if self.scenario == "sensor_fault" and zone_idx == 2:
            soil_raw = 0
            flags = 1 << 1  # FLAG_SOIL_ERR

        return {
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "zone": zone_idx,
            "air_t": round(st["air_t"], 2),
            "air_rh": round(st["air_rh"], 2),
            "soil_m": round(st["soil_m"], 2),
            "soil_raw": soil_raw,
            "lux": round(st["lux"], 1) if zone_idx == 1 else None,
            "batt": 0,
            "rssi": random.randint(-66, -54),
            "flags": flags,
            "seq": self._seq,
        }

    def build_status_payload(self) -> bytes:
        uptime = int(time.monotonic() - self._start_mono)
        body = {
            "online": True,
            "fw": "1.0.0-sim",
            "rssi": -58,
            "uptime_s": uptime,
            "heap": 184000,
            "queue_len": 0,
            "cfg_version": self.safety.cfg_version,
            "actuators": dict(self.safety.actuators),
            "nodes": [
                {
                    "mac": f"AA:BB:CC:DD:EE:{z:02X}",
                    "zone": z,
                    "last_seen_s": 2,
                }
                for z in range(1, self.nodes_per_gw + 1)
            ],
        }
        return json.dumps(body).encode("utf-8")

    async def run(self, stop_event: asyncio.Event | None = None) -> None:
        will = aiomqtt.Will(
            topic=f"{self.prefix}/status",
            payload=b'{"online":false}',
            qos=1,
            retain=True,
        )
        async with aiomqtt.Client(
            hostname=self.mqtt_host,
            port=self.mqtt_port,
            username=self.mqtt_username,
            password=self.mqtt_password,
            identifier=f"sim-{self.mqtt_username}",
            tls_context=self.tls_ctx if self.mqtt_port == 8883 else None,
            will=will,
            keepalive=15,
        ) as client:
            await client.subscribe(f"{self.prefix}/cfg", qos=1)
            await client.subscribe(f"{self.prefix}/cmd/#", qos=1)
            await client.publish(
                f"{self.prefix}/status",
                payload=self.build_status_payload(),
                qos=1,
                retain=True,
            )
            log.info("Gateway %s online (%s)", self.mqtt_username, self.prefix)

            async def _rx_loop() -> None:
                async for msg in client.messages:
                    topic = str(msg.topic)
                    if topic.endswith("/cfg"):
                        cfg = json.loads(bytes(msg.payload))
                        if self.safety.apply_cfg(cfg):
                            await client.publish(
                                f"{self.prefix}/status",
                                payload=self.build_status_payload(),
                                qos=1,
                                retain=True,
                            )
                    elif "/cmd/" in topic:
                        cmd = json.loads(bytes(msg.payload))
                        ack = self.safety.apply_command(
                            cmd, datetime.now(UTC), time.monotonic()
                        )
                        if ack is not None:
                            await client.publish(
                                f"{self.prefix}/ack/{ack['cmd_id']}",
                                payload=json.dumps(ack).encode("utf-8"),
                                qos=1,
                                retain=False,
                            )

            async def _tx_loop() -> None:
                last_hb = 0.0
                while stop_event is None or not stop_event.is_set():
                    now_m = time.monotonic()
                    if self.safety.tick(now_m) or (now_m - last_hb >= 30.0):
                        await client.publish(
                            f"{self.prefix}/status",
                            payload=self.build_status_payload(),
                            qos=1,
                            retain=True,
                        )
                        last_hb = now_m

                    for z in range(1, self.nodes_per_gw + 1):
                        pkt = self._step_physics(z, self.interval_s)
                        await client.publish(
                            f"{self.prefix}/telemetry/{z}",
                            payload=json.dumps(pkt).encode("utf-8"),
                            qos=1,
                            retain=False,
                        )
                    await asyncio.sleep(self.interval_s)

            rx_task = asyncio.create_task(_rx_loop())
            tx_task = asyncio.create_task(_tx_loop())
            try:
                if stop_event is not None:
                    await stop_event.wait()
                else:
                    await asyncio.gather(rx_task, tx_task)
            finally:
                rx_task.cancel()
                tx_task.cancel()


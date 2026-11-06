"""Command Service: phát lệnh MQTT, xử lý ACK, quản lý timeout và chế độ manual (spec 6.3, 6.5)."""

import copy
import logging
import uuid
from datetime import UTC, datetime

import aiomqtt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import ActuatorLog, Command, DeviceState, Gateway, Greenhouse
from core.pubsub import CHANNEL_WS, pg_notify
from core.schemas import ACTUATOR_NAMES, AckPayload, CommandMqttPayload
from worker.shadow import ensure_device_state

log = logging.getLogger("worker.commands")


def _parse_side_effect(effect: str) -> tuple[str, str] | None:
    """Giải mã chuỗi side_effect như 'mist_off' -> ('mist', 'off')."""
    for act in ACTUATOR_NAMES:
        prefix = f"{act}_"
        if effect.startswith(prefix):
            action = effect[len(prefix) :]
            if action in ("on", "off"):
                return act, action
    return None


async def dispatch_pending_commands(
    mqtt_client: aiomqtt.Client,
    session: AsyncSession,
    command_id: uuid.UUID | None = None,
) -> int:
    """Phát các lệnh đang ở trạng thái `pending` lên topic `cmd/{actuator}` (QoS 1)."""
    now = datetime.now(UTC)
    stmt = (
        select(Command, Greenhouse, Gateway)
        .join(Greenhouse, Command.greenhouse_id == Greenhouse.id)
        .outerjoin(Gateway, Gateway.greenhouse_id == Greenhouse.id)
        .where(Command.status == "pending")
        .order_by(Command.created_at)
    )
    if command_id is not None:
        stmt = stmt.where(Command.id == command_id)

    rows = (await session.execute(stmt)).all()
    sent_count = 0

    for cmd, gh, gw in rows:
        if cmd.expires_at <= now:
            cmd.status = "expired"
            await pg_notify(
                session,
                CHANNEL_WS,
                {
                    "farm_id": str(gh.farm_id),
                    "type": "command_status",
                    "data": {"cmd_id": str(cmd.id), "status": "expired"},
                },
            )
            continue

        if gw is None or not gw.online:
            cmd.status = "rejected"
            cmd.reject_reason = "gateway_offline"
            cmd.acked_at = now
            await pg_notify(
                session,
                CHANNEL_WS,
                {
                    "farm_id": str(gh.farm_id),
                    "type": "command_status",
                    "data": {
                        "cmd_id": str(cmd.id),
                        "status": "rejected",
                        "reason": "gateway_offline",
                    },
                },
            )
            continue

        mqtt_payload = CommandMqttPayload(
            cmd_id=cmd.id,
            actuator=cmd.actuator,  # type: ignore[arg-type]
            action=cmd.action,  # type: ignore[arg-type]
            duration_s=cmd.duration_s,
            expires_at=cmd.expires_at,
            source=cmd.source,  # type: ignore[arg-type]
        )
        topic = f"gh/{gh.farm_id}/{gh.id}/cmd/{cmd.actuator}"
        await mqtt_client.publish(
            topic,
            payload=mqtt_payload.model_dump_json().encode("utf-8"),
            qos=1,
            retain=False,
        )
        cmd.status = "sent"
        cmd.sent_at = now
        sent_count += 1
        log.info("Sent cmd %s (%s %s) -> %s", cmd.id, cmd.actuator, cmd.action, topic)
        await pg_notify(
            session,
            CHANNEL_WS,
            {
                "farm_id": str(gh.farm_id),
                "type": "command_status",
                "data": {"cmd_id": str(cmd.id), "status": "sent"},
            },
        )

    return sent_count


async def handle_ack(
    session: AsyncSession,
    farm_id: uuid.UUID,
    greenhouse_id: uuid.UUID,
    cmd_id: uuid.UUID,
    raw_json: bytes,
) -> bool:
    """Xử lý bản tin `ack/{cmd_id}` từ gateway."""
    payload = AckPayload.model_validate_json(raw_json)
    if payload.cmd_id != cmd_id:
        log.warning("cmd_id trong topic (%s) khác payload (%s)", cmd_id, payload.cmd_id)
        return False

    row = (
        await session.execute(
            select(Command, Greenhouse)
            .join(Greenhouse, Command.greenhouse_id == Greenhouse.id)
            .where(
                Command.id == cmd_id,
                Command.greenhouse_id == greenhouse_id,
                Greenhouse.farm_id == farm_id,
            )
        )
    ).first()
    if row is None:
        log.warning("Không tìm thấy lệnh %s cho greenhouse %s", cmd_id, greenhouse_id)
        return False

    cmd, gh = row
    if cmd.status in ("applied", "rejected", "expired"):
        return False

    now = datetime.now(UTC)
    cmd.status = payload.status
    cmd.reject_reason = payload.reason
    cmd.acked_at = payload.applied_at or now

    state = await ensure_device_state(session, greenhouse_id)
    reported = copy.deepcopy(state.reported or {})
    if payload.state:
        reported["actuators"] = dict(payload.state)
    state.reported = reported
    state.updated_at = now

    if payload.status == "applied":
        session.add(
            ActuatorLog(
                greenhouse_id=greenhouse_id,
                actuator=cmd.actuator,
                action=cmd.action,
                source=cmd.source,
                cmd_id=cmd.id,
                duration_s=cmd.duration_s,
                reason=cmd.reason,
            )
        )
        for effect in payload.side_effects:
            parsed = _parse_side_effect(effect)
            if parsed is not None:
                eff_act, eff_action = parsed
                session.add(
                    ActuatorLog(
                        greenhouse_id=greenhouse_id,
                        actuator=eff_act,
                        action=eff_action,
                        source=cmd.source,
                        cmd_id=cmd.id,
                        duration_s=None,
                        reason=f"side_effect:{effect}",
                    )
                )

    await pg_notify(
        session,
        CHANNEL_WS,
        {
            "farm_id": str(gh.farm_id),
            "type": "command_status",
            "data": {
                "cmd_id": str(cmd.id),
                "greenhouse_id": str(greenhouse_id),
                "actuator": cmd.actuator,
                "action": cmd.action,
                "status": cmd.status,
                "reason": cmd.reject_reason,
                "side_effects": payload.side_effects,
                "state": payload.state,
            },
        },
    )
    return True


async def expire_timed_out_commands(session: AsyncSession) -> int:
    """Chuyển các lệnh `pending`/`sent` quá `expires_at` sang `expired`/`timeout` (spec 6.5)."""
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(Command, Greenhouse.farm_id)
            .join(Greenhouse, Command.greenhouse_id == Greenhouse.id)
            .where(Command.status.in_(("pending", "sent")), Command.expires_at <= now)
        )
    ).all()

    for cmd, farm_id in rows:
        cmd.status = "expired" if cmd.status == "pending" else "timeout"
        await pg_notify(
            session,
            CHANNEL_WS,
            {
                "farm_id": str(farm_id),
                "type": "command_status",
                "data": {
                    "cmd_id": str(cmd.id),
                    "greenhouse_id": str(cmd.greenhouse_id),
                    "status": cmd.status,
                },
            },
        )
    return len(rows)


async def expire_manual_modes(session: AsyncSession) -> int:
    """Tự trả actuator về `auto` khi thời điểm `until` của chế độ `manual` đã qua (spec 6.3)."""
    now = datetime.now(UTC)
    states = (await session.execute(select(DeviceState))).scalars().all()
    changed_count = 0

    for st in states:
        desired = copy.deepcopy(st.desired or {})
        modes = desired.get("modes")
        if not isinstance(modes, dict):
            continue
        mutated = False
        for act, cfg in modes.items():
            if not isinstance(cfg, dict) or cfg.get("mode") != "manual":
                continue
            until_raw = cfg.get("until")
            if not until_raw:
                continue
            try:
                until_dt = datetime.fromisoformat(str(until_raw).replace("Z", "+00:00"))
            except ValueError:
                continue
            if until_dt <= now:
                modes[act] = {"mode": "auto", "until": None}
                mutated = True
        if mutated:
            desired["modes"] = modes
            st.desired = desired
            st.updated_at = now
            changed_count += 1

    return changed_count

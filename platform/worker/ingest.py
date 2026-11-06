"""Ingestion: nhận telemetry/status/discovery/event từ gateway, tính VPD, gắn quality A1, ghi DB."""

import copy
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.crop_templates import DEFAULT_DEMO_PARAMS
from core.models import (
    ActuatorLog,
    CropProfile,
    DeviceNode,
    Gateway,
    Greenhouse,
    Reading,
    Zone,
)
from core.pubsub import CHANNEL_WS, pg_notify
from core.quality import ReadingSample, ZoneQualityTracker, is_neighbor_divergent
from core.schemas import (
    DiscoveryPayload,
    GatewayEventPayload,
    GatewayStatusPayload,
    TelemetryPayload,
    normalize_mac,
)
from core.vpd import calc_vpd
from worker.shadow import ensure_device_state

log = logging.getLogger("worker.ingest")


class IngestService:
    """Quản lý bộ nhớ ngắn hạn cho kiểm tra chất lượng dữ liệu A1 và xử lý gói MQTT đến."""

    def __init__(self) -> None:
        self._trackers: dict[uuid.UUID, ZoneQualityTracker] = {}

    def _tracker(self, zone_id: uuid.UUID) -> ZoneQualityTracker:
        tracker = self._trackers.get(zone_id)
        if tracker is None:
            tracker = ZoneQualityTracker()
            self._trackers[zone_id] = tracker
        return tracker

    async def warm_up(self, session: AsyncSession, window_size: int = 60) -> None:
        """Dựng lại cửa sổ mẫu gần nhất cho từng zone khi worker khởi động (spec 3.2)."""
        zone_ids = (await session.execute(select(Zone.id))).scalars().all()
        for zid in zone_ids:
            rows = (
                await session.execute(
                    select(Reading)
                    .where(Reading.zone_id == zid)
                    .order_by(desc(Reading.ts))
                    .limit(window_size)
                )
            ).scalars().all()
            samples = [
                ReadingSample(
                    ts_epoch=r.ts.timestamp(),
                    air_t=r.air_temp,
                    air_rh=r.air_rh,
                    soil_m=r.soil_moisture,
                    soil_raw=r.soil_raw,
                    lux=r.lux,
                    flags=0,
                )
                for r in reversed(rows)
            ]
            self._tracker(zid).warm_up(samples)
        log.info("Warmed up A1 trackers for %d zones", len(zone_ids))

    async def handle_telemetry(
        self,
        session: AsyncSession,
        farm_id: uuid.UUID,
        greenhouse_id: uuid.UUID,
        zone_index: int,
        raw_json: bytes,
    ) -> str | None:
        payload = TelemetryPayload.model_validate_json(raw_json)
        row = (
            await session.execute(
                select(Zone, Greenhouse, Gateway, CropProfile)
                .join(Greenhouse, Zone.greenhouse_id == Greenhouse.id)
                .outerjoin(Gateway, Gateway.greenhouse_id == Greenhouse.id)
                .outerjoin(CropProfile, Zone.crop_profile_id == CropProfile.id)
                .where(
                    Greenhouse.id == greenhouse_id,
                    Greenhouse.farm_id == farm_id,
                    Zone.zone_index == zone_index,
                )
            )
        ).first()
        if row is None:
            log.warning(
                "Bỏ qua telemetry không khớp zone: farm=%s gh=%s zone=%s",
                farm_id,
                greenhouse_id,
                zone_index,
            )
            return None

        zone, _gh, gw, profile = row
        params = profile.parameters_json if profile is not None else DEFAULT_DEMO_PARAMS
        sample_interval_s = float(params.get("sample_interval_s", 60))
        leaf_offset_c = float(params.get("vpd", {}).get("leaf_offset_c", 1.0))

        sample = ReadingSample(
            ts_epoch=payload.ts.timestamp(),
            air_t=payload.air_t,
            air_rh=payload.air_rh,
            soil_m=payload.soil_m,
            soil_raw=payload.soil_raw,
            lux=payload.lux,
            flags=payload.flags,
        )
        quality = self._tracker(zone.id).evaluate(sample, sample_interval_s=sample_interval_s)

        vpd_val: float | None = None
        if payload.air_t is not None and payload.air_rh is not None:
            vpd_val = round(calc_vpd(payload.air_t, payload.air_rh, leaf_offset_c), 4)

        # Đối chiếu chênh lệch nghi ngờ với các zone lân cận cùng nhà kính
        sibling_ids = (
            await session.execute(
                select(Zone.id).where(Zone.greenhouse_id == greenhouse_id, Zone.id != zone.id)
            )
        ).scalars().all()
        neighbor_suspect = False
        for sib_id in sibling_ids:
            sib_last = self._trackers.get(sib_id)
            if sib_last and sib_last.last_sample is not None:
                if is_neighbor_divergent(sample, sib_last.last_sample, sample_interval_s):
                    neighbor_suspect = True
                    log.warning(
                        "Chênh lệch khí hậu nghi ngờ giữa zone %s và %s", zone.id, sib_id
                    )

        source = "sim" if (gw is not None and gw.is_simulated) else "real"
        now = datetime.now(UTC)

        stmt = (
            pg_insert(Reading)
            .values(
                ts=payload.ts,
                zone_id=zone.id,
                air_temp=payload.air_t,
                air_rh=payload.air_rh,
                vpd=vpd_val,
                soil_moisture=payload.soil_m,
                soil_raw=payload.soil_raw,
                lux=payload.lux,
                rssi=payload.rssi,
                seq=payload.seq,
                quality=quality,
                source=source,
            )
            .on_conflict_do_nothing(index_elements=["zone_id", "ts"])
        )
        await session.execute(stmt)

        if gw is not None:
            gw.last_seen = now
            gw.online = True

        node = (
            await session.execute(
                select(DeviceNode).where(
                    DeviceNode.zone_id == zone.id, DeviceNode.status == "paired"
                )
            )
        ).scalar_one_or_none()
        if node is not None:
            node.last_seen = now
            node.rssi = payload.rssi
            node.battery_mv = payload.batt

        await pg_notify(
            session,
            CHANNEL_WS,
            {
                "farm_id": str(farm_id),
                "type": "telemetry",
                "data": {
                    "greenhouse_id": str(greenhouse_id),
                    "zone_id": str(zone.id),
                    "zone_index": zone_index,
                    "ts": payload.ts.isoformat(),
                    "air_temp": payload.air_t,
                    "air_rh": payload.air_rh,
                    "vpd": vpd_val,
                    "soil_moisture": payload.soil_m,
                    "soil_raw": payload.soil_raw,
                    "lux": payload.lux,
                    "quality": quality,
                    "neighbor_suspect": neighbor_suspect,
                },
            },
        )
        return quality

    async def handle_status(
        self,
        session: AsyncSession,
        farm_id: uuid.UUID,
        greenhouse_id: uuid.UUID,
        raw_json: bytes,
    ) -> bool:
        payload = GatewayStatusPayload.model_validate_json(raw_json)
        row = (
            await session.execute(
                select(Greenhouse, Gateway)
                .outerjoin(Gateway, Gateway.greenhouse_id == Greenhouse.id)
                .where(Greenhouse.id == greenhouse_id, Greenhouse.farm_id == farm_id)
            )
        ).first()
        if row is None:
            return False

        _gh, gw = row
        now = datetime.now(UTC)
        if gw is not None:
            gw.online = payload.online
            if payload.online:
                gw.last_seen = now
                if payload.fw is not None:
                    gw.fw_version = payload.fw
                if payload.rssi is not None:
                    gw.rssi = payload.rssi

        state = await ensure_device_state(session, greenhouse_id)
        prev_cfg_rep = state.cfg_version_reported

        if payload.online:
            reported = copy.deepcopy(state.reported or {})
            if payload.actuators is not None:
                reported["actuators"] = dict(payload.actuators)
            if payload.uptime_s is not None:
                reported["uptime_s"] = payload.uptime_s
            if payload.heap is not None:
                reported["heap"] = payload.heap
            if payload.queue_len is not None:
                reported["queue_len"] = payload.queue_len
            if payload.nodes is not None:
                reported["nodes"] = [n.model_dump() for n in payload.nodes]
            state.reported = reported
            if payload.cfg_version is not None:
                state.cfg_version_reported = payload.cfg_version
            state.updated_at = now

        await pg_notify(
            session,
            CHANNEL_WS,
            {
                "farm_id": str(farm_id),
                "type": "device_status",
                "data": {
                    "greenhouse_id": str(greenhouse_id),
                    "online": payload.online,
                    "rssi": payload.rssi,
                    "cfg_version_reported": state.cfg_version_reported,
                    "cfg_version_desired": state.cfg_version_desired,
                    "actuators": (state.reported or {}).get("actuators", {}),
                },
            },
        )
        if state.cfg_version_reported != prev_cfg_rep:
            await pg_notify(
                session,
                CHANNEL_WS,
                {
                    "farm_id": str(farm_id),
                    "type": "config_sync",
                    "data": {
                        "greenhouse_id": str(greenhouse_id),
                        "cfg_version_desired": state.cfg_version_desired,
                        "cfg_version_reported": state.cfg_version_reported,
                        "synced": state.cfg_version_reported >= state.cfg_version_desired,
                    },
                },
            )
        return True

    async def handle_discovery(
        self,
        session: AsyncSession,
        farm_id: uuid.UUID,
        greenhouse_id: uuid.UUID,
        raw_json: bytes,
    ) -> DeviceNode | None:
        payload = DiscoveryPayload.model_validate_json(raw_json)
        gh = (
            await session.execute(
                select(Greenhouse).where(
                    Greenhouse.id == greenhouse_id, Greenhouse.farm_id == farm_id
                )
            )
        ).scalar_one_or_none()
        if gh is None:
            return None

        mac = normalize_mac(payload.mac)
        now = datetime.now(UTC)
        node = (
            await session.execute(select(DeviceNode).where(DeviceNode.mac_address == mac))
        ).scalar_one_or_none()
        if node is None:
            node = DeviceNode(
                mac_address=mac,
                greenhouse_id=greenhouse_id,
                status="discovered",
                firmware_version=payload.fw,
                rssi=payload.rssi,
                first_seen=now,
                last_seen=now,
            )
            session.add(node)
            await session.flush()
        else:
            if node.status == "discovered":
                node.greenhouse_id = greenhouse_id
            node.firmware_version = payload.fw or node.firmware_version
            node.rssi = payload.rssi if payload.rssi is not None else node.rssi
            node.last_seen = now

        await pg_notify(
            session,
            CHANNEL_WS,
            {
                "farm_id": str(farm_id),
                "type": "device_status",
                "data": {
                    "event": "node_discovered",
                    "greenhouse_id": str(greenhouse_id),
                    "mac": mac,
                    "status": node.status,
                    "rssi": node.rssi,
                },
            },
        )
        return node

    async def handle_event(
        self,
        session: AsyncSession,
        farm_id: uuid.UUID,
        greenhouse_id: uuid.UUID,
        raw_json: bytes,
    ) -> bool:
        payload = GatewayEventPayload.model_validate_json(raw_json)
        gh = (
            await session.execute(
                select(Greenhouse).where(
                    Greenhouse.id == greenhouse_id, Greenhouse.farm_id == farm_id
                )
            )
        ).scalar_one_or_none()
        if gh is None:
            return False

        if payload.type == "actuator_changed" and payload.actuator and payload.action:
            session.add(
                ActuatorLog(
                    greenhouse_id=greenhouse_id,
                    actuator=payload.actuator,
                    action=payload.action,
                    source=payload.source or "failsafe",
                    duration_s=payload.detail.get("duration_s"),
                    reason=f"gateway_event:{payload.detail.get('trigger', payload.type)}",
                )
            )
        log.info(
            "Gateway event gh=%s type=%s detail=%s", greenhouse_id, payload.type, payload.detail
        )
        return True

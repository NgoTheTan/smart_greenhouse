"""Device Shadow & Config: sinh và publish bản tin `cfg` retained xuống gateway (spec 5, 6.3)."""

import logging
import uuid
from datetime import UTC, datetime

import aiomqtt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.crop_templates import DEFAULT_DEMO_PARAMS
from core.models import CropProfile, DeviceNode, DeviceState, Greenhouse, Zone
from core.schemas import (
    CfgFailsafe,
    CfgLimits,
    CfgNodeItem,
    CfgPayload,
    CfgSoilCal,
    CfgZoneItem,
)

log = logging.getLogger("worker.shadow")


async def ensure_device_state(session: AsyncSession, greenhouse_id: uuid.UUID) -> DeviceState:
    state = await session.get(DeviceState, greenhouse_id)
    if state is None:
        state = DeviceState(
            greenhouse_id=greenhouse_id,
            reported={},
            desired={},
            cfg_version_desired=1,
            cfg_version_reported=0,
        )
        session.add(state)
        await session.flush()
    return state


async def bump_cfg_version(session: AsyncSession, greenhouse_id: uuid.UUID) -> int:
    state = await ensure_device_state(session, greenhouse_id)
    state.cfg_version_desired = (state.cfg_version_desired or 0) + 1
    state.updated_at = datetime.now(UTC)
    await session.flush()
    return state.cfg_version_desired


async def build_gateway_cfg(
    session: AsyncSession, greenhouse_id: uuid.UUID
) -> tuple[uuid.UUID, CfgPayload] | None:
    gh = await session.get(Greenhouse, greenhouse_id)
    if gh is None:
        return None

    state = await ensure_device_state(session, greenhouse_id)

    zones_rows = (
        await session.execute(
            select(Zone, CropProfile)
            .outerjoin(CropProfile, Zone.crop_profile_id == CropProfile.id)
            .where(Zone.greenhouse_id == greenhouse_id)
            .order_by(Zone.zone_index)
        )
    ).all()

    zone_index_by_id: dict[uuid.UUID, int] = {}
    cfg_zones: list[CfgZoneItem] = []

    for zone, profile in zones_rows:
        zone_index_by_id[zone.id] = zone.zone_index
        params = profile.parameters_json if profile is not None else DEFAULT_DEMO_PARAMS
        irr = params.get("irrigation", DEFAULT_DEMO_PARAMS["irrigation"])
        fan = params.get("fan", DEFAULT_DEMO_PARAMS["fan"])
        mist = params.get("mist", DEFAULT_DEMO_PARAMS["mist"])
        fs = params.get("failsafe", DEFAULT_DEMO_PARAMS["failsafe"])
        pump_ch = zone.pump_channel or zone.zone_index

        cfg_zones.append(
            CfgZoneItem(
                zone=zone.zone_index,
                pump=f"pump_{pump_ch}",
                sample_interval_s=int(params.get("sample_interval_s", 60)),
                soil_cal=CfgSoilCal(
                    dry_raw=zone.soil_dry_raw if zone.soil_dry_raw is not None else 2900,
                    wet_raw=zone.soil_wet_raw if zone.soil_wet_raw is not None else 1300,
                ),
                limits=CfgLimits(
                    irrigation_max_run_s=int(irr["max_run_s"]),
                    irrigation_min_gap_s=int(irr["min_gap_s"]),
                    irrigation_max_total_s_per_hour=int(irr["max_total_s_per_hour"]),
                    fan_max_on_s=int(fan["max_on_s"]),
                    mist_max_on_s=int(mist["max_on_s"]),
                ),
                failsafe=CfgFailsafe(
                    temp_critical_high_c=float(fs["temp_critical_high_c"]),
                    soil_moisture_critical_low_pct=float(fs["soil_moisture_critical_low_pct"]),
                ),
            )
        )

    nodes_rows = (
        await session.execute(
            select(DeviceNode)
            .where(
                DeviceNode.greenhouse_id == greenhouse_id,
                DeviceNode.status == "paired",
                DeviceNode.zone_id.is_not(None),
            )
            .order_by(DeviceNode.mac_address)
        )
    ).scalars().all()

    cfg_nodes = [
        CfgNodeItem(mac=n.mac_address, zone=zone_index_by_id[n.zone_id])
        for n in nodes_rows
        if n.zone_id in zone_index_by_id
    ]

    payload = CfgPayload(
        cfg_version=state.cfg_version_desired,
        offline_failsafe_after_s=60,
        nodes=cfg_nodes,
        zones=cfg_zones,
    )
    return gh.farm_id, payload


class ShadowPublisher:
    """Publish `cfg` retained và nhớ phiên bản đã phát trong phiên kết nối MQTT hiện tại."""

    def __init__(self) -> None:
        self._published_versions: dict[uuid.UUID, int] = {}

    def reset_cache(self) -> None:
        self._published_versions.clear()

    async def publish_cfg(
        self,
        mqtt_client: aiomqtt.Client,
        session: AsyncSession,
        greenhouse_id: uuid.UUID,
        *,
        force: bool = True,
    ) -> bool:
        built = await build_gateway_cfg(session, greenhouse_id)
        if built is None:
            return False
        farm_id, cfg = built
        if not force and self._published_versions.get(greenhouse_id) == cfg.cfg_version:
            return False

        topic = f"gh/{farm_id}/{greenhouse_id}/cfg"
        await mqtt_client.publish(
            topic,
            payload=cfg.model_dump_json().encode("utf-8"),
            qos=1,
            retain=True,
        )
        self._published_versions[greenhouse_id] = cfg.cfg_version
        log.info("Published cfg v%s -> %s", cfg.cfg_version, topic)
        return True

    async def sync_unsynced(
        self, mqtt_client: aiomqtt.Client, session: AsyncSession
    ) -> int:
        rows = (
            await session.execute(
                select(DeviceState.greenhouse_id).where(
                    DeviceState.cfg_version_desired > DeviceState.cfg_version_reported
                )
            )
        ).scalars().all()
        count = 0
        for gh_id in rows:
            if await self.publish_cfg(mqtt_client, session, gh_id, force=False):
                count += 1
        return count

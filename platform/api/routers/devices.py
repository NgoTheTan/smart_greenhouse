"""Router thiết bị: cấp phát gateway, trạng thái, ghép node & hiệu chuẩn ẩm đất (spec 6.2, 9)."""

import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from api.deps import CurrentOwner, CurrentViewer, DbSession
from api.provisioning import provision_gateway_mqtt
from api.routers.greenhouses import get_owned_greenhouse
from core.config import get_settings
from core.models import DeviceNode, Gateway, Greenhouse, Zone
from core.pubsub import CHANNEL_WORKER, pg_notify
from core.schemas import (
    CalibrationUpdateRequest,
    DeviceNodeResponse,
    GatewayCreateRequest,
    GatewayProvisionResponse,
    GatewayStatusResponse,
    NodePairRequest,
    normalize_mac,
)
from worker.shadow import bump_cfg_version, ensure_device_state

router = APIRouter(tags=["devices"])


@router.post(
    "/gateways",
    response_model=GatewayProvisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_gateway(
    body: GatewayCreateRequest, user: CurrentOwner, session: DbSession
) -> GatewayProvisionResponse:
    gh = await get_owned_greenhouse(session, body.greenhouse_id, user.farm_id)
    existing = (
        await session.execute(select(Gateway).where(Gateway.greenhouse_id == gh.id))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nhà kính này đã được cấp phát gateway",
        )

    mqtt_username = f"gw_{gh.id.hex[:12]}"
    mqtt_password = secrets.token_urlsafe(20)

    await provision_gateway_mqtt(user.farm_id, gh.id, mqtt_username, mqtt_password)

    gw = Gateway(
        greenhouse_id=gh.id,
        mqtt_username=mqtt_username,
        is_simulated=body.is_simulated,
        online=False,
    )
    session.add(gw)
    await ensure_device_state(session, gh.id)
    await pg_notify(session, CHANNEL_WORKER, {"type": "cfg_updated", "greenhouse_id": str(gh.id)})
    await session.commit()
    await session.refresh(gw)

    s = get_settings()
    return GatewayProvisionResponse(
        gateway_id=gw.id,
        farm_id=user.farm_id,
        greenhouse_id=gh.id,
        mqtt_username=mqtt_username,
        mqtt_password=mqtt_password,
        host=s.mqtt_public_host,
        port=s.mqtt_public_port,
        is_simulated=gw.is_simulated,
    )


@router.get("/gateways/{gateway_id}/status", response_model=GatewayStatusResponse)
async def get_gateway_status(
    gateway_id: uuid.UUID, user: CurrentViewer, session: DbSession
) -> GatewayStatusResponse:
    row = (
        await session.execute(
            select(Gateway, Greenhouse)
            .join(Greenhouse, Gateway.greenhouse_id == Greenhouse.id)
            .where(Gateway.id == gateway_id, Greenhouse.farm_id == user.farm_id)
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy gateway"
        )
    gw, gh = row
    state = await ensure_device_state(session, gh.id)
    return GatewayStatusResponse(
        id=gw.id,
        greenhouse_id=gw.greenhouse_id,
        mqtt_username=gw.mqtt_username,
        is_simulated=gw.is_simulated,
        online=gw.online,
        last_seen=gw.last_seen,
        fw_version=gw.fw_version,
        rssi=gw.rssi,
        reported=state.reported or {},
        desired=state.desired or {},
        cfg_version_desired=state.cfg_version_desired,
        cfg_version_reported=state.cfg_version_reported,
    )


@router.get("/nodes", response_model=list[DeviceNodeResponse])
async def list_nodes(
    user: CurrentOwner,
    session: DbSession,
    node_status: Annotated[str | None, Query(alias="status")] = None,
) -> list[DeviceNode]:
    stmt = (
        select(DeviceNode)
        .join(Greenhouse, DeviceNode.greenhouse_id == Greenhouse.id)
        .where(Greenhouse.farm_id == user.farm_id)
        .order_by(DeviceNode.first_seen.desc())
    )
    if node_status is not None:
        stmt = stmt.where(DeviceNode.status == node_status)
    return list((await session.execute(stmt)).scalars().all())


@router.post("/nodes/{mac}/pair", response_model=DeviceNodeResponse)
async def pair_node(
    mac: str, body: NodePairRequest, user: CurrentOwner, session: DbSession
) -> DeviceNode:
    """Ghép node vào zone: hỗ trợ cả node đã `discovered` lẫn nhập MAC thủ công mới."""
    try:
        norm_mac = normalize_mac(mac)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    zone_row = (
        await session.execute(
            select(Zone, Greenhouse)
            .join(Greenhouse, Zone.greenhouse_id == Greenhouse.id)
            .where(Zone.id == body.zone_id, Greenhouse.farm_id == user.farm_id)
        )
    ).first()
    if zone_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy zone thuộc farm của bạn"
        )
    zone, gh = zone_row

    node = (
        await session.execute(select(DeviceNode).where(DeviceNode.mac_address == norm_mac))
    ).scalar_one_or_none()

    if node is not None and node.greenhouse_id is not None:
        existing_gh = await session.get(Greenhouse, node.greenhouse_id)
        if existing_gh is not None and existing_gh.farm_id != user.farm_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="MAC này đã thuộc về một farm khác",
            )

    # Nếu zone đang có node khác paired thì gỡ liên kết cũ về discovered
    prev_nodes = (
        await session.execute(
            select(DeviceNode).where(
                DeviceNode.zone_id == zone.id, DeviceNode.mac_address != norm_mac
            )
        )
    ).scalars().all()
    for prev in prev_nodes:
        prev.zone_id = None
        prev.status = "discovered"

    now = datetime.now(UTC)
    if node is None:
        node = DeviceNode(
            mac_address=norm_mac,
            greenhouse_id=gh.id,
            zone_id=zone.id,
            status="paired",
            first_seen=now,
        )
        session.add(node)
    else:
        node.greenhouse_id = gh.id
        node.zone_id = zone.id
        node.status = "paired"

    await bump_cfg_version(session, gh.id)
    await pg_notify(session, CHANNEL_WORKER, {"type": "cfg_updated", "greenhouse_id": str(gh.id)})
    await session.commit()
    await session.refresh(node)
    return node


@router.put("/zones/{zone_id}/calibration", response_model=dict)
async def update_zone_calibration(
    zone_id: uuid.UUID,
    body: CalibrationUpdateRequest,
    user: CurrentOwner,
    session: DbSession,
) -> dict:
    row = (
        await session.execute(
            select(Zone, Greenhouse)
            .join(Greenhouse, Zone.greenhouse_id == Greenhouse.id)
            .where(Zone.id == zone_id, Greenhouse.farm_id == user.farm_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy zone")
    zone, gh = row
    zone.soil_dry_raw = body.soil_dry_raw
    zone.soil_wet_raw = body.soil_wet_raw

    new_ver = await bump_cfg_version(session, gh.id)
    await pg_notify(session, CHANNEL_WORKER, {"type": "cfg_updated", "greenhouse_id": str(gh.id)})
    await session.commit()
    return {
        "zone_id": str(zone.id),
        "soil_dry_raw": zone.soil_dry_raw,
        "soil_wet_raw": zone.soil_wet_raw,
        "cfg_version_desired": new_ver,
    }

"""Router nhà kính & đồng bộ cấu hình: /api/greenhouses* (spec 9)."""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from api.deps import CurrentOwner, CurrentViewer, DbSession
from core.crop_templates import TEMPLATE_STRAWBERRY_DEMO_ID, TEMPLATE_TOMATO_DEMO_ID
from core.models import Alert, DeviceState, Gateway, Greenhouse, Zone
from core.schemas import (
    ConfigSyncResponse,
    GreenhouseCreateRequest,
    GreenhouseResponse,
    ZoneCreateSpec,
    ZoneResponse,
)
from worker.shadow import ensure_device_state

router = APIRouter(prefix="/greenhouses", tags=["greenhouses"])


async def get_owned_greenhouse(
    session: DbSession, gh_id: uuid.UUID, farm_id: uuid.UUID
) -> Greenhouse:
    gh = (
        await session.execute(
            select(Greenhouse).where(Greenhouse.id == gh_id, Greenhouse.farm_id == farm_id)
        )
    ).scalar_one_or_none()
    if gh is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy nhà kính"
        )
    return gh


async def _serialize_greenhouse(session: DbSession, gh: Greenhouse) -> GreenhouseResponse:
    gw = (
        await session.execute(select(Gateway).where(Gateway.greenhouse_id == gh.id))
    ).scalar_one_or_none()
    zones = (
        await session.execute(
            select(Zone).where(Zone.greenhouse_id == gh.id).order_by(Zone.zone_index)
        )
    ).scalars().all()
    open_alerts = (
        await session.execute(
            select(func.count())
            .select_from(Alert)
            .where(Alert.greenhouse_id == gh.id, Alert.state != "resolved")
        )
    ).scalar_one()

    return GreenhouseResponse(
        id=gh.id,
        farm_id=gh.farm_id,
        name=gh.name,
        location=gh.location,
        created_at=gh.created_at,
        online=bool(gw and gw.online),
        open_alerts=int(open_alerts),
        zones=[ZoneResponse.model_validate(z) for z in zones],
    )


@router.get("", response_model=list[GreenhouseResponse])
async def list_greenhouses(user: CurrentViewer, session: DbSession) -> list[GreenhouseResponse]:
    ghs = (
        await session.execute(
            select(Greenhouse)
            .where(Greenhouse.farm_id == user.farm_id)
            .order_by(Greenhouse.created_at)
        )
    ).scalars().all()
    return [await _serialize_greenhouse(session, gh) for gh in ghs]


@router.post("", response_model=GreenhouseResponse, status_code=status.HTTP_201_CREATED)
async def create_greenhouse(
    body: GreenhouseCreateRequest, user: CurrentOwner, session: DbSession
) -> GreenhouseResponse:
    gh = Greenhouse(farm_id=user.farm_id, name=body.name, location=body.location)
    session.add(gh)
    await session.flush()

    zone_specs = body.zones or [
        ZoneCreateSpec(
            zone_index=1,
            name="Zone 1 – Cà chua bi",
            crop_profile_id=TEMPLATE_TOMATO_DEMO_ID,
            pump_channel=1,
        ),
        ZoneCreateSpec(
            zone_index=2,
            name="Zone 2 – Dâu tây",
            crop_profile_id=TEMPLATE_STRAWBERRY_DEMO_ID,
            pump_channel=2,
        ),
    ]
    for z in zone_specs:
        session.add(
            Zone(
                greenhouse_id=gh.id,
                zone_index=z.zone_index,
                name=z.name,
                crop_profile_id=z.crop_profile_id,
                pump_channel=z.pump_channel or z.zone_index,
                soil_dry_raw=z.soil_dry_raw,
                soil_wet_raw=z.soil_wet_raw,
            )
        )

    session.add(
        DeviceState(
            greenhouse_id=gh.id,
            reported={},
            desired={},
            cfg_version_desired=1,
            cfg_version_reported=0,
        )
    )
    await session.commit()
    await session.refresh(gh)
    return await _serialize_greenhouse(session, gh)


@router.get("/{gh_id}", response_model=GreenhouseResponse)
async def get_greenhouse(
    gh_id: uuid.UUID, user: CurrentViewer, session: DbSession
) -> GreenhouseResponse:
    gh = await get_owned_greenhouse(session, gh_id, user.farm_id)
    return await _serialize_greenhouse(session, gh)


@router.get("/{gh_id}/config-sync", response_model=ConfigSyncResponse)
async def get_config_sync(
    gh_id: uuid.UUID, user: CurrentViewer, session: DbSession
) -> ConfigSyncResponse:
    await get_owned_greenhouse(session, gh_id, user.farm_id)
    state = await ensure_device_state(session, gh_id)
    await session.commit()
    return ConfigSyncResponse(
        greenhouse_id=gh_id,
        cfg_version_desired=state.cfg_version_desired,
        cfg_version_reported=state.cfg_version_reported,
        synced=state.cfg_version_reported >= state.cfg_version_desired,
        updated_at=state.updated_at,
    )


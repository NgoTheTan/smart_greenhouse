"""Router quản lý vụ trồng: /api/zones/{id}/cycles & /api/cycles/{id}/harvest|abandon."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Query, status
from sqlalchemy import desc, or_, select

from api.deps import CurrentOperator, CurrentViewer, DbSession
from api.routers.zones import _get_owned_zone
from core.models import CropCycle, CropProfile, Greenhouse, Zone
from core.pubsub import CHANNEL_WORKER, CHANNEL_WS, pg_notify
from core.schemas import (
    CropCycleAbandonRequest,
    CropCycleCreateRequest,
    CropCycleHarvestRequest,
    CropCycleResponse,
    CycleStatusType,
)
from worker.shadow import bump_cfg_version

router = APIRouter(tags=["cycles"])


def _normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _serialize_cycle(cycle: CropCycle, profile: CropProfile | None) -> CropCycleResponse:
    yield_kg_m2 = None
    if cycle.yield_kg is not None and cycle.area_m2 and cycle.area_m2 > 0:
        yield_kg_m2 = round(cycle.yield_kg / cycle.area_m2, 4)
    return CropCycleResponse(
        id=cycle.id,
        zone_id=cycle.zone_id,
        crop_profile_id=cycle.crop_profile_id,
        crop_code=profile.crop_code if profile else None,
        crop_name=profile.crop_name if profile else None,
        started_at=cycle.started_at,
        harvested_at=cycle.harvested_at,
        area_m2=cycle.area_m2,
        yield_kg=cycle.yield_kg,
        yield_kg_m2=yield_kg_m2,
        status=cycle.status,
        notes=cycle.notes,
        created_by=cycle.created_by,
        created_at=cycle.created_at,
    )


def _cycle_ws_payload(
    event: str,
    gh: Greenhouse,
    cycle: CropCycle,
    profile: CropProfile | None,
) -> dict:
    return {
        "farm_id": str(gh.farm_id),
        "type": "crop_cycle",
        "data": {
            "event": event,
            "cycle_id": str(cycle.id),
            "greenhouse_id": str(gh.id),
            "zone_id": str(cycle.zone_id),
            "crop_profile_id": str(cycle.crop_profile_id),
            "crop_code": profile.crop_code if profile else None,
            "status": cycle.status,
            "started_at": cycle.started_at.isoformat(),
            "harvested_at": cycle.harvested_at.isoformat() if cycle.harvested_at else None,
            "area_m2": cycle.area_m2,
            "yield_kg": cycle.yield_kg,
        },
    }


async def _get_owned_cycle(
    session: DbSession, cycle_id: uuid.UUID, farm_id: uuid.UUID
) -> tuple[CropCycle, Zone, Greenhouse, CropProfile | None]:
    stmt = (
        select(CropCycle, Zone, Greenhouse, CropProfile)
        .join(Zone, CropCycle.zone_id == Zone.id)
        .join(Greenhouse, Zone.greenhouse_id == Greenhouse.id)
        .outerjoin(CropProfile, CropCycle.crop_profile_id == CropProfile.id)
        .where(CropCycle.id == cycle_id, Greenhouse.farm_id == farm_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy vụ trồng hoặc không có quyền truy cập",
        )
    return row


@router.get("/zones/{zone_id}/cycles", response_model=list[CropCycleResponse])
async def list_zone_cycles(
    zone_id: uuid.UUID,
    user: CurrentViewer,
    session: DbSession,
    cycle_status: Annotated[CycleStatusType | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[CropCycleResponse]:
    """Lấy danh sách các vụ trồng của một zone theo thứ tự mới nhất trước."""
    await _get_owned_zone(session, zone_id, user.farm_id)

    stmt = (
        select(CropCycle, CropProfile)
        .outerjoin(CropProfile, CropCycle.crop_profile_id == CropProfile.id)
        .where(CropCycle.zone_id == zone_id)
        .order_by(desc(CropCycle.started_at))
        .limit(limit)
    )
    if cycle_status is not None:
        stmt = stmt.where(CropCycle.status == cycle_status)

    rows = (await session.execute(stmt)).all()
    return [_serialize_cycle(c, p) for c, p in rows]


@router.post(
    "/zones/{zone_id}/cycles",
    response_model=CropCycleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_zone_cycle(
    zone_id: uuid.UUID,
    body: CropCycleCreateRequest,
    user: CurrentOperator,
    session: DbSession,
) -> CropCycleResponse:
    """Bắt đầu vụ trồng mới cho zone (tối đa 1 vụ active trên mỗi zone)."""
    zone, gh = await _get_owned_zone(session, zone_id, user.farm_id)

    active = (
        await session.execute(
            select(CropCycle.id).where(
                CropCycle.zone_id == zone_id, CropCycle.status == "active"
            )
        )
    ).first()
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="zone_already_has_active_cycle",
        )

    profile = (
        await session.execute(
            select(CropProfile).where(
                CropProfile.id == body.crop_profile_id,
                or_(CropProfile.farm_id.is_(None), CropProfile.farm_id == user.farm_id),
            )
        )
    ).scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy crop profile"
        )

    area_m2 = body.area_m2 if body.area_m2 is not None else zone.area_m2
    if area_m2 is None or area_m2 <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="area_m2 là bắt buộc (> 0) khi zone chưa cấu hình diện tích",
        )

    now = datetime.now(UTC)
    started_at = _normalize_utc(body.started_at) if body.started_at else now

    cycle = CropCycle(
        id=uuid.uuid4(),
        zone_id=zone.id,
        crop_profile_id=profile.id,
        started_at=started_at,
        area_m2=float(area_m2),
        status="active",
        notes=body.notes,
        created_by=user.id,
        created_at=now,
    )
    session.add(cycle)

    cfg_changed = zone.crop_profile_id != profile.id
    zone.crop_profile_id = profile.id
    zone.planting_date = started_at.date()
    if cfg_changed:
        await bump_cfg_version(session, gh.id)
        await pg_notify(
            session, CHANNEL_WORKER, {"type": "cfg_updated", "greenhouse_id": str(gh.id)}
        )

    await session.flush()
    await pg_notify(session, CHANNEL_WS, _cycle_ws_payload("started", gh, cycle, profile))
    await session.commit()
    await session.refresh(cycle)
    return _serialize_cycle(cycle, profile)


@router.post("/cycles/{cycle_id}/harvest", response_model=CropCycleResponse)
async def harvest_cycle(
    cycle_id: uuid.UUID,
    body: CropCycleHarvestRequest,
    user: CurrentOperator,
    session: DbSession,
) -> CropCycleResponse:
    """Ghi nhận thu hoạch vụ trồng và kích hoạt worker tạo mẫu `yield_samples`."""
    cycle, _zone, gh, profile = await _get_owned_cycle(session, cycle_id, user.farm_id)
    if cycle.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cycle_not_active",
        )

    harvested_at = (
        _normalize_utc(body.harvested_at) if body.harvested_at else datetime.now(UTC)
    )
    if harvested_at < _normalize_utc(cycle.started_at):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="harvested_at phải lớn hơn hoặc bằng started_at",
        )

    cycle.status = "harvested"
    cycle.harvested_at = harvested_at
    cycle.yield_kg = float(body.yield_kg)
    if body.notes is not None:
        cycle.notes = body.notes

    await session.flush()
    await pg_notify(
        session,
        CHANNEL_WORKER,
        {"type": "cycle_harvested", "cycle_id": str(cycle.id)},
    )
    await pg_notify(session, CHANNEL_WS, _cycle_ws_payload("harvested", gh, cycle, profile))
    await session.commit()
    await session.refresh(cycle)
    return _serialize_cycle(cycle, profile)


@router.post("/cycles/{cycle_id}/abandon", response_model=CropCycleResponse)
async def abandon_cycle(
    cycle_id: uuid.UUID,
    user: CurrentOperator,
    session: DbSession,
    body: Annotated[CropCycleAbandonRequest | None, Body()] = None,
) -> CropCycleResponse:
    """Huỷ vụ trồng đang chạy (không tạo mẫu huấn luyện)."""
    cycle, _zone, gh, profile = await _get_owned_cycle(session, cycle_id, user.farm_id)
    if cycle.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cycle_not_active",
        )

    cycle.status = "abandoned"
    if body is not None and body.notes is not None:
        cycle.notes = body.notes

    await session.flush()
    await pg_notify(session, CHANNEL_WS, _cycle_ws_payload("abandoned", gh, cycle, profile))
    await session.commit()
    await session.refresh(cycle)
    return _serialize_cycle(cycle, profile)

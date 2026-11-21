"""Router zone, dữ liệu chuỗi thời gian, DLI & crop profile (spec 6.4, 7.1, 9)."""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import delete, func, or_, select, text, update

from api.deps import CurrentUser, DbSession
from core.crop_templates import CropParameters
from core.models import (
    ActuatorLog,
    Alert,
    Command,
    CropCycle,
    CropProfile,
    DeviceNode,
    DeviceState,
    Gateway,
    Greenhouse,
    Prediction,
    Reading,
    YieldSample,
    Zone,
)
from core.pubsub import CHANNEL_WORKER, pg_notify
from core.schemas import (
    CropProfileResponse,
    CropProfileUpdateRequest,
    DliResponse,
    ReadingPoint,
    ZoneResponse,
    ZoneUpdateRequest,
)
from core.vpd import integrate_dli
from worker.shadow import bump_cfg_version

router = APIRouter(tags=["zones"])


async def _get_owned_zone(
    session: DbSession, zone_id: uuid.UUID, farm_id: uuid.UUID
) -> tuple[Zone, Greenhouse]:
    row = (
        await session.execute(
            select(Zone, Greenhouse)
            .join(Greenhouse, Zone.greenhouse_id == Greenhouse.id)
            .where(Zone.id == zone_id, Greenhouse.farm_id == farm_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy zone")
    return row


@router.get("/zones/{zone_id}", response_model=ZoneResponse)
async def get_zone(zone_id: uuid.UUID, user: CurrentUser, session: DbSession) -> Zone:
    zone, _gh = await _get_owned_zone(session, zone_id, user.farm_id)
    return zone


@router.put("/zones/{zone_id}", response_model=ZoneResponse)
async def update_zone(
    zone_id: uuid.UUID, body: ZoneUpdateRequest, user: CurrentUser, session: DbSession
) -> Zone:
    zone, gh = await _get_owned_zone(session, zone_id, user.farm_id)
    cfg_changed = False

    if body.name is not None:
        zone.name = body.name
    if body.area_m2 is not None:
        zone.area_m2 = body.area_m2
    if body.planting_date is not None:
        zone.planting_date = body.planting_date
    if body.crop_profile_id is not None and body.crop_profile_id != zone.crop_profile_id:
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
        zone.crop_profile_id = profile.id
        cfg_changed = True

    if cfg_changed:
        await bump_cfg_version(session, gh.id)
        await pg_notify(
            session, CHANNEL_WORKER, {"type": "cfg_updated", "greenhouse_id": str(gh.id)}
        )

    await session.commit()
    await session.refresh(zone)
    return zone


async def _delete_greenhouse_cascade(session: DbSession, gh: Greenhouse) -> None:
    """Xóa toàn bộ greenhouse và tất cả các bảng phụ thuộc cascade."""
    # 1. Gỡ liên kết DeviceNode
    await session.execute(
        update(DeviceNode)
        .where(DeviceNode.greenhouse_id == gh.id)
        .values(greenhouse_id=None, zone_id=None, status="discovered")
    )

    # 2. Gỡ liên kết YieldSample liên quan crop_cycle trong greenhouse này
    subq_crop_cycles = select(CropCycle.id).where(
        CropCycle.zone_id.in_(select(Zone.id).where(Zone.greenhouse_id == gh.id))
    )
    await session.execute(
        update(YieldSample)
        .where(YieldSample.crop_cycle_id.in_(subq_crop_cycles))
        .values(crop_cycle_id=None)
    )

    # 3. Xóa Predictions
    await session.execute(delete(Prediction).where(Prediction.greenhouse_id == gh.id))

    # 4. Xóa ActuatorLogs
    await session.execute(delete(ActuatorLog).where(ActuatorLog.greenhouse_id == gh.id))

    # 5. Xóa Commands
    await session.execute(delete(Command).where(Command.greenhouse_id == gh.id))

    # 6. Xóa Alerts
    await session.execute(delete(Alert).where(Alert.greenhouse_id == gh.id))

    # 7. Xóa DeviceState
    await session.execute(delete(DeviceState).where(DeviceState.greenhouse_id == gh.id))

    # 8. Xóa Readings (và bảng sqlite rollups)
    subq_zones = select(Zone.id).where(Zone.greenhouse_id == gh.id)
    await session.execute(delete(Reading).where(Reading.zone_id.in_(subq_zones)))
    bind = getattr(session, "bind", None) or (
        session.get_bind() if hasattr(session, "get_bind") else None
    )
    if bind and getattr(bind.dialect, "name", "") == "sqlite":
        zone_ids = (
            await session.execute(select(Zone.id).where(Zone.greenhouse_id == gh.id))
        ).scalars().all()
        for zid in zone_ids:
            await session.execute(
                text("DELETE FROM readings_1m WHERE zone_id = :zid"), {"zid": str(zid)}
            )
            await session.execute(
                text("DELETE FROM readings_1h WHERE zone_id = :zid"), {"zid": str(zid)}
            )

    # 9. Xóa CropCycles
    await session.execute(delete(CropCycle).where(CropCycle.zone_id.in_(subq_zones)))

    # 10. Xóa Gateway
    await session.execute(delete(Gateway).where(Gateway.greenhouse_id == gh.id))

    # 11. Xóa Zones
    await session.execute(delete(Zone).where(Zone.greenhouse_id == gh.id))

    # 12. Xóa Greenhouse
    await session.delete(gh)


@router.delete("/zones/{zone_id}", status_code=status.HTTP_200_OK)
async def delete_zone(
    zone_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    delete_greenhouse_if_last: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    zone, gh = await _get_owned_zone(session, zone_id, user.farm_id)

    count = (
        await session.execute(
            select(func.count()).select_from(Zone).where(Zone.greenhouse_id == gh.id)
        )
    ).scalar_one()
    if count <= 1:
        if not delete_greenhouse_if_last:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nhà kính phải có ít nhất 1 vùng trồng. Nếu tiếp tục xóa, toàn bộ nhà kính sẽ bị xóa.",
            )
        await _delete_greenhouse_cascade(session, gh)
        await session.commit()
        return {
            "ok": True,
            "deleted_greenhouse": True,
            "message": f"Đã xóa thành công vùng trồng và toàn bộ nhà kính '{gh.name}'.",
        }

    # Gỡ liên kết DeviceNode
    await session.execute(
        update(DeviceNode).where(DeviceNode.zone_id == zone.id).values(zone_id=None)
    )

    # Gỡ liên kết Alert
    await session.execute(
        update(Alert).where(Alert.zone_id == zone.id).values(zone_id=None)
    )

    # Gỡ liên kết YieldSample nếu có
    await session.execute(
        update(YieldSample)
        .where(
            YieldSample.crop_cycle_id.in_(
                select(CropCycle.id).where(CropCycle.zone_id == zone.id)
            )
        )
        .values(crop_cycle_id=None)
    )

    # Xóa Readings
    await session.execute(delete(Reading).where(Reading.zone_id == zone.id))

    # Xóa bảng tổng hợp nếu ở chế độ sqlite
    bind = getattr(session, "bind", None) or (
        session.get_bind() if hasattr(session, "get_bind") else None
    )
    if bind and getattr(bind.dialect, "name", "") == "sqlite":
        await session.execute(
            text("DELETE FROM readings_1m WHERE zone_id = :zid"), {"zid": str(zone.id)}
        )
        await session.execute(
            text("DELETE FROM readings_1h WHERE zone_id = :zid"), {"zid": str(zone.id)}
        )

    # Xóa CropCycles & Predictions
    await session.execute(delete(CropCycle).where(CropCycle.zone_id == zone.id))
    await session.execute(delete(Prediction).where(Prediction.zone_id == zone.id))

    # Xóa Zone
    await session.delete(zone)

    # Đồng bộ shadow
    await bump_cfg_version(session, gh.id)
    await pg_notify(
        session, CHANNEL_WORKER, {"type": "cfg_updated", "greenhouse_id": str(gh.id)}
    )
    await session.commit()
    return {
        "ok": True,
        "deleted_greenhouse": False,
        "message": f"Đã xóa thành công {zone.name or f'Zone {zone.zone_index}'}",
    }



@router.get("/zones/{zone_id}/readings", response_model=list[ReadingPoint])
async def get_zone_readings(
    zone_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    dt_from: Annotated[datetime | None, Query(alias="from")] = None,
    dt_to: Annotated[datetime | None, Query(alias="to")] = None,
    agg: Annotated[Literal["raw", "1m", "1h"], Query()] = "raw",
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> list[ReadingPoint]:
    await _get_owned_zone(session, zone_id, user.farm_id)
    now = datetime.now(UTC)
    end_ts = dt_to or now

    if agg == "raw":
        stmt = select(Reading).where(Reading.zone_id == zone_id)
        if dt_from is not None:
            stmt = stmt.where(Reading.ts >= dt_from)
        if dt_to is not None:
            stmt = stmt.where(Reading.ts <= dt_to)
        elif dt_from is not None:
            stmt = stmt.where(Reading.ts <= end_ts)

        if dt_from is None and dt_to is None:
            stmt = stmt.order_by(Reading.ts.desc()).limit(limit)
            rows = list(reversed((await session.execute(stmt)).scalars().all()))
        else:
            stmt = stmt.order_by(Reading.ts.asc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()

        return [
            ReadingPoint(
                ts=r.ts,
                air_temp=r.air_temp,
                air_rh=r.air_rh,
                vpd=r.vpd,
                soil_moisture=r.soil_moisture,
                soil_raw=r.soil_raw,
                lux=r.lux,
                quality=r.quality,
                source=r.source,
            )
            for r in rows
        ]

    view_name = "readings_1m" if agg == "1m" else "readings_1h"
    is_sqlite = (session.get_bind().dialect.name == "sqlite") if session.get_bind() else False
    zid_param = str(zone_id) if is_sqlite else zone_id

    where_clauses = ["zone_id = :zid"]
    params: dict[str, Any] = {"zid": zid_param, "lim": limit}
    if dt_from is not None:
        where_clauses.append("bucket >= :start")
        params["start"] = dt_from
    if dt_to is not None:
        where_clauses.append("bucket <= :end")
        params["end"] = dt_to
    elif dt_from is not None:
        where_clauses.append("bucket <= :end")
        params["end"] = end_ts

    where_sql = " AND ".join(where_clauses)
    agg_rows = (
        await session.execute(
            text(
                f"SELECT bucket, air_temp, air_rh, vpd, soil_moisture, lux "  # noqa: S608
                f"FROM {view_name} "
                f"WHERE {where_sql} "
                f"ORDER BY bucket ASC LIMIT :lim"
            ),
            params,
        )
    ).mappings().all()

    return [
        ReadingPoint(
            ts=r["bucket"],
            air_temp=r["air_temp"],
            air_rh=r["air_rh"],
            vpd=r["vpd"],
            soil_moisture=r["soil_moisture"],
            lux=r["lux"],
            quality="ok",
        )
        for r in agg_rows
    ]


@router.get("/zones/{zone_id}/dli", response_model=DliResponse)
async def get_zone_dli(
    zone_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    target_date: Annotated[date | None, Query(alias="date")] = None,
) -> DliResponse:
    zone, _gh = await _get_owned_zone(session, zone_id, user.farm_id)
    day = target_date or datetime.now(UTC).date()
    day_start = datetime.combine(day, time.min, tzinfo=UTC)
    day_end = day_start + timedelta(days=1)

    sample_interval_s = 60.0
    if zone.crop_profile_id is not None:
        profile = await session.get(CropProfile, zone.crop_profile_id)
        if profile is not None:
            sample_interval_s = float(profile.parameters_json.get("sample_interval_s", 60))

    rows = (
        await session.execute(
            select(Reading.ts, Reading.lux)
            .where(
                Reading.zone_id == zone_id,
                Reading.quality == "ok",
                Reading.lux.is_not(None),
                Reading.ts >= day_start,
                Reading.ts < day_end,
            )
            .order_by(Reading.ts.asc())
        )
    ).all()

    samples = [(ts, lux) for ts, lux in rows]
    dli_val = round(integrate_dli(samples, max_gap_s=3.0 * sample_interval_s), 4)
    return DliResponse(
        zone_id=zone_id, date=day, dli_mol_m2_day=dli_val, sample_count=len(samples)
    )


@router.get("/crop-profiles", response_model=list[CropProfileResponse])
async def list_crop_profiles(user: CurrentUser, session: DbSession) -> list[CropProfile]:
    rows = (
        await session.execute(
            select(CropProfile)
            .where(or_(CropProfile.farm_id.is_(None), CropProfile.farm_id == user.farm_id))
            .order_by(CropProfile.crop_name, CropProfile.variety)
        )
    ).scalars().all()
    return list(rows)


@router.get("/crop-profiles/{profile_id}", response_model=CropProfileResponse)
async def get_crop_profile(
    profile_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> CropProfile:
    profile = (
        await session.execute(
            select(CropProfile).where(
                CropProfile.id == profile_id,
                or_(CropProfile.farm_id.is_(None), CropProfile.farm_id == user.farm_id),
            )
        )
    ).scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy crop profile"
        )
    return profile


@router.put("/crop-profiles/{profile_id}", response_model=CropProfileResponse)
async def update_crop_profile(
    profile_id: uuid.UUID,
    body: CropProfileUpdateRequest,
    user: CurrentUser,
    session: DbSession,
) -> CropProfile:
    try:
        validated = CropParameters.model_validate(body.parameters_json).model_dump(by_alias=True)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()
        ) from exc

    profile = (
        await session.execute(
            select(CropProfile).where(
                CropProfile.id == profile_id,
                or_(CropProfile.farm_id.is_(None), CropProfile.farm_id == user.farm_id),
            )
        )
    ).scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy crop profile"
        )

    # Nếu đang chỉnh trên template hệ thống (farm_id = NULL) thì tạo bản sao riêng cho farm
    if profile.farm_id is None:
        cloned = CropProfile(
            farm_id=user.farm_id,
            crop_code=body.crop_code or profile.crop_code,
            crop_name=body.crop_name or profile.crop_name,
            variety=body.variety if body.variety is not None else profile.variety,
            schema_version=validated["schema_version"],
            parameters_json=validated,
        )
        session.add(cloned)
        await session.flush()

        affected_zones = (
            await session.execute(
                select(Zone, Greenhouse)
                .join(Greenhouse, Zone.greenhouse_id == Greenhouse.id)
                .where(Zone.crop_profile_id == profile.id, Greenhouse.farm_id == user.farm_id)
            )
        ).all()
        affected_gh_ids: set[uuid.UUID] = set()
        for z, gh in affected_zones:
            z.crop_profile_id = cloned.id
            affected_gh_ids.add(gh.id)

        for gh_id in affected_gh_ids:
            await bump_cfg_version(session, gh_id)
            await pg_notify(
                session, CHANNEL_WORKER, {"type": "cfg_updated", "greenhouse_id": str(gh_id)}
            )
        await session.commit()
        await session.refresh(cloned)
        return cloned

    if body.crop_code is not None:
        profile.crop_code = body.crop_code
    if body.crop_name is not None:
        profile.crop_name = body.crop_name
    if body.variety is not None:
        profile.variety = body.variety
    profile.parameters_json = validated
    profile.schema_version = validated["schema_version"]

    affected_gh_rows = (
        await session.execute(
            select(Zone.greenhouse_id).where(Zone.crop_profile_id == profile.id).distinct()
        )
    ).scalars().all()
    for gh_id in affected_gh_rows:
        await bump_cfg_version(session, gh_id)
        await pg_notify(
            session, CHANNEL_WORKER, {"type": "cfg_updated", "greenhouse_id": str(gh_id)}
        )

    await session.commit()
    await session.refresh(profile)
    return profile

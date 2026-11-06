"""Router zone, dữ liệu chuỗi thời gian, DLI & crop profile (spec 6.4, 7.1, 9)."""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import or_, select, text

from api.deps import CurrentOwner, CurrentViewer, DbSession
from core.crop_templates import CropParameters
from core.models import CropProfile, Greenhouse, Reading, Zone
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
async def get_zone(zone_id: uuid.UUID, user: CurrentViewer, session: DbSession) -> Zone:
    zone, _gh = await _get_owned_zone(session, zone_id, user.farm_id)
    return zone


@router.put("/zones/{zone_id}", response_model=ZoneResponse)
async def update_zone(
    zone_id: uuid.UUID, body: ZoneUpdateRequest, user: CurrentOwner, session: DbSession
) -> Zone:
    zone, gh = await _get_owned_zone(session, zone_id, user.farm_id)
    cfg_changed = False

    if body.name is not None:
        zone.name = body.name
    if body.planting_date is not None:
        zone.planting_date = body.planting_date
    if body.control_strategy is not None:
        zone.control_strategy = body.control_strategy
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


@router.get("/zones/{zone_id}/readings", response_model=list[ReadingPoint])
async def get_zone_readings(
    zone_id: uuid.UUID,
    user: CurrentViewer,
    session: DbSession,
    dt_from: Annotated[datetime | None, Query(alias="from")] = None,
    dt_to: Annotated[datetime | None, Query(alias="to")] = None,
    agg: Annotated[Literal["raw", "1m", "1h"], Query()] = "raw",
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> list[ReadingPoint]:
    await _get_owned_zone(session, zone_id, user.farm_id)
    now = datetime.now(UTC)
    end_ts = dt_to or now
    start_ts = dt_from or (end_ts - timedelta(hours=6))

    if agg == "raw":
        rows = (
            await session.execute(
                select(Reading)
                .where(Reading.zone_id == zone_id, Reading.ts >= start_ts, Reading.ts <= end_ts)
                .order_by(Reading.ts.asc())
                .limit(limit)
            )
        ).scalars().all()
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
    agg_rows = (
        await session.execute(
            text(
                f"SELECT bucket, air_temp, air_rh, vpd, soil_moisture, lux "  # noqa: S608
                f"FROM {view_name} "
                f"WHERE zone_id = :zid AND bucket >= :start AND bucket <= :end "
                f"ORDER BY bucket ASC LIMIT :lim"
            ),
            {"zid": zone_id, "start": start_ts, "end": end_ts, "lim": limit},
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
    user: CurrentViewer,
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
async def list_crop_profiles(user: CurrentViewer, session: DbSession) -> list[CropProfile]:
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
    profile_id: uuid.UUID, user: CurrentViewer, session: DbSession
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
    user: CurrentOwner,
    session: DbSession,
) -> CropProfile:
    try:
        validated = CropParameters.model_validate(body.parameters_json).model_dump()
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

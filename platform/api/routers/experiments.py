"""Router quản lý thí nghiệm so sánh Fixed vs Adaptive: /api/experiments (spec 8.4, 9)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import desc, func, select, update

from api.deps import CurrentOperator, CurrentViewer, DbSession
from core.crop_templates import DEFAULT_DEMO_PARAMS
from core.models import ActuatorLog, Alert, CropProfile, ExperimentRun, Greenhouse, Reading, Zone
from core.schemas import ExperimentCreateRequest, ExperimentKpiResponse, ExperimentRunResponse

router = APIRouter(prefix="/experiments", tags=["experiments"])


async def _verify_greenhouse_ownership(
    session: DbSession, greenhouse_id: uuid.UUID, farm_id: uuid.UUID
) -> Greenhouse:
    gh = (
        await session.execute(
            select(Greenhouse).where(
                Greenhouse.id == greenhouse_id, Greenhouse.farm_id == farm_id
            )
        )
    ).scalar_one_or_none()
    if gh is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy nhà kính hoặc không có quyền truy cập",
        )
    return gh


@router.get("", response_model=list[ExperimentRunResponse])
async def list_experiments(
    user: CurrentViewer,
    session: DbSession,
    greenhouse_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[ExperimentRun]:
    """Lấy danh sách các đợt thí nghiệm Fixed vs Adaptive của farm."""
    stmt = (
        select(ExperimentRun)
        .join(Greenhouse, ExperimentRun.greenhouse_id == Greenhouse.id)
        .where(Greenhouse.farm_id == user.farm_id)
        .order_by(desc(ExperimentRun.started_at))
    )
    if greenhouse_id is not None:
        stmt = stmt.where(ExperimentRun.greenhouse_id == greenhouse_id)

    return list((await session.execute(stmt)).scalars().all())


@router.post("", response_model=ExperimentRunResponse, status_code=status.HTTP_201_CREATED)
async def start_experiment(
    body: ExperimentCreateRequest,
    user: CurrentOperator,
    session: DbSession,
) -> ExperimentRun:
    """Bắt đầu đợt thí nghiệm mới: chuyển chiến lược điều khiển zone và ghi log thí nghiệm."""
    gh = await _verify_greenhouse_ownership(session, body.greenhouse_id, user.farm_id)
    now = datetime.now(UTC)

    # Đóng mọi thí nghiệm đang chạy của nhà kính này
    close_stmt = (
        update(ExperimentRun)
        .where(
            ExperimentRun.greenhouse_id == gh.id,
            ExperimentRun.ended_at.is_(None),
        )
        .values(ended_at=now)
    )
    await session.execute(close_stmt)

    # Cập nhật chiến lược cho toàn bộ zone thuộc nhà kính
    zone_update = (
        update(Zone)
        .where(Zone.greenhouse_id == gh.id)
        .values(control_strategy=body.strategy)
    )
    await session.execute(zone_update)

    run = ExperimentRun(
        id=uuid.uuid4(),
        greenhouse_id=gh.id,
        strategy=body.strategy,
        started_at=now,
        notes=body.notes,
    )
    session.add(run)
    await session.flush()
    return run


@router.post("/{exp_id}/stop", response_model=ExperimentRunResponse)
async def stop_experiment(
    exp_id: uuid.UUID,
    user: CurrentOperator,
    session: DbSession,
) -> ExperimentRun:
    """Kết thúc đợt thí nghiệm."""
    stmt = (
        select(ExperimentRun)
        .join(Greenhouse, ExperimentRun.greenhouse_id == Greenhouse.id)
        .where(ExperimentRun.id == exp_id, Greenhouse.farm_id == user.farm_id)
    )
    exp = (await session.execute(stmt)).scalar_one_or_none()
    if exp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy đợt thí nghiệm",
        )

    if exp.ended_at is None:
        exp.ended_at = datetime.now(UTC)
        session.add(exp)
        await session.flush()

    return exp


@router.get("/{exp_id}/kpis", response_model=ExperimentKpiResponse)
async def get_experiment_kpis(
    exp_id: uuid.UUID,
    user: CurrentViewer,
    session: DbSession,
) -> ExperimentKpiResponse:
    """Tính toán 5 KPI đánh giá hiệu quả chiến lược (Fixed vs Adaptive) qua truy vấn SQL thuần."""
    stmt = (
        select(ExperimentRun)
        .join(Greenhouse, ExperimentRun.greenhouse_id == Greenhouse.id)
        .where(ExperimentRun.id == exp_id, Greenhouse.farm_id == user.farm_id)
    )
    exp = (await session.execute(stmt)).scalar_one_or_none()
    if exp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy đợt thí nghiệm",
        )

    t_start = exp.started_at
    t_end = exp.ended_at or datetime.now(UTC)
    duration_hours = max((t_end - t_start).total_seconds() / 3600.0, 0.0001)

    # 1. Số lần bật thiết bị / giờ (từ actuator_logs)
    cycle_stmt = (
        select(ActuatorLog.actuator, func.count().label("cnt"))
        .where(
            ActuatorLog.greenhouse_id == exp.greenhouse_id,
            ActuatorLog.created_at >= t_start,
            ActuatorLog.created_at <= t_end,
            ActuatorLog.action == "on",
        )
        .group_by(ActuatorLog.actuator)
    )
    cycles_rows = (await session.execute(cycle_stmt)).all()
    actuator_cycles: dict[str, float] = {"pump_1": 0.0, "pump_2": 0.0, "fan": 0.0, "mist": 0.0}
    for act, cnt in cycles_rows:
        actuator_cycles[str(act)] = round(float(cnt) / duration_hours, 2)

    # 2. Tổng thời gian bơm (giây)
    pump_dur_stmt = (
        select(ActuatorLog.actuator, func.coalesce(func.sum(ActuatorLog.duration_s), 0))
        .where(
            ActuatorLog.greenhouse_id == exp.greenhouse_id,
            ActuatorLog.created_at >= t_start,
            ActuatorLog.created_at <= t_end,
            ActuatorLog.actuator.in_(["pump_1", "pump_2"]),
        )
        .group_by(ActuatorLog.actuator)
    )
    pump_rows = (await session.execute(pump_dur_stmt)).all()
    total_pump_duration_s: dict[str, int] = {"pump_1": 0, "pump_2": 0}
    for act, dur in pump_rows:
        total_pump_duration_s[str(act)] = int(dur)

    # Lấy các zone của greenhouse
    zones_stmt = (
        select(Zone)
        .where(Zone.greenhouse_id == exp.greenhouse_id)
        .order_by(Zone.zone_index)
    )
    zones = list((await session.execute(zones_stmt)).scalars().all())

    # 3. % Thời gian VPD nằm trong dải tối ưu & 4. Overshoot ẩm đất
    vpd_in_range_pct: dict[str, float] = {}
    soil_overshoot_pct: dict[str, float] = {}

    for z in zones:
        z_name = z.name or f"Zone {z.zone_index}"

        # Đọc ngưỡng optimal từ CropProfile
        opt_min, opt_max = 0.5, 1.2
        soil_max = 75.0
        if z.crop_profile_id is not None:
            cp = await session.get(CropProfile, z.crop_profile_id)
            if cp and cp.parameters_json:
                vpd_opt = cp.parameters_json.get("vpd", {}).get("optimal")
                if isinstance(vpd_opt, list | tuple) and len(vpd_opt) == 2:
                    opt_min, opt_max = float(vpd_opt[0]), float(vpd_opt[1])
                soil_params = cp.parameters_json.get("soil_moisture", {})
                soil_max = float(soil_params.get("max", 75.0))
        else:
            vpd_opt = DEFAULT_DEMO_PARAMS.get("vpd", {}).get("optimal", [0.5, 1.2])
            opt_min, opt_max = float(vpd_opt[0]), float(vpd_opt[1])
            soil_max = float(DEFAULT_DEMO_PARAMS.get("soil_moisture", {}).get("max", 75.0))

        readings_stmt = select(Reading).where(
            Reading.zone_id == z.id,
            Reading.quality == "ok",
            Reading.ts >= t_start,
            Reading.ts <= t_end,
        )
        z_readings = list((await session.execute(readings_stmt)).scalars().all())

        if z_readings:
            valid_vpd = [r.vpd for r in z_readings if r.vpd is not None]
            if valid_vpd:
                in_opt = sum(1 for v in valid_vpd if opt_min <= v <= opt_max)
                vpd_in_range_pct[z_name] = round((in_opt / len(valid_vpd)) * 100.0, 1)
            else:
                vpd_in_range_pct[z_name] = 100.0

            valid_soil = [r.soil_moisture for r in z_readings if r.soil_moisture is not None]
            if valid_soil:
                max_s = max(valid_soil)
                soil_overshoot_pct[z_name] = round(max(0.0, max_s - soil_max), 1)
            else:
                soil_overshoot_pct[z_name] = 0.0
        else:
            vpd_in_range_pct[z_name] = 100.0
            soil_overshoot_pct[z_name] = 0.0

    # 5. Cảnh báo sai (false positive alerts)
    false_pos_stmt = select(func.count()).select_from(Alert).where(
        Alert.greenhouse_id == exp.greenhouse_id,
        Alert.created_at >= t_start,
        Alert.created_at <= t_end,
        Alert.feedback == "false_positive",
    )
    false_positives = (await session.execute(false_pos_stmt)).scalar_one()

    return ExperimentKpiResponse(
        experiment_id=exp.id,
        greenhouse_id=exp.greenhouse_id,
        strategy=exp.strategy,
        started_at=t_start,
        ended_at=exp.ended_at,
        duration_hours=round(duration_hours, 2),
        actuator_cycles_per_hour=actuator_cycles,
        vpd_in_range_pct=vpd_in_range_pct,
        soil_overshoot_pct=soil_overshoot_pct,
        total_pump_duration_s=total_pump_duration_s,
        false_positive_alerts=int(false_positives),
    )

"""Router mô hình AI toàn cục & dự báo năng suất: /api/models* và /api/zones/{id}/predictions."""

import statistics
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import desc, select

from api.deps import CurrentViewer, DbSession
from core.climate_features import CLIMATE_FEATURE_NAMES
from core.models import Greenhouse, MlModel, Prediction, Zone
from core.schemas import MlModelResponse, PredictionResponse

router = APIRouter(tags=["models"])


async def _verify_zone_ownership(
    session: DbSession, zone_id: uuid.UUID, farm_id: uuid.UUID
) -> Zone:
    stmt = (
        select(Zone)
        .join(Greenhouse, Zone.greenhouse_id == Greenhouse.id)
        .where(Zone.id == zone_id, Greenhouse.farm_id == farm_id)
    )
    zone = (await session.execute(stmt)).scalar_one_or_none()
    if zone is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy zone hoặc không có quyền truy cập",
        )
    return zone


async def _compute_feature_drift(
    session: DbSession,
    model: MlModel,
    farm_id: uuid.UUID,
    window_days: int = 7,
) -> dict[str, Any]:
    """Tính chênh lệch phân phối đặc trưng 7 ngày gần nhất bằng Python thuần (không nạp ML)."""
    cutoff = datetime.now(UTC) - timedelta(days=window_days)
    stmt = (
        select(Prediction.details)
        .join(Greenhouse, Prediction.greenhouse_id == Greenhouse.id)
        .where(
            Greenhouse.farm_id == farm_id,
            Prediction.ts >= cutoff,
        )
        .order_by(desc(Prediction.ts))
        .limit(500)
    )
    rows = (await session.execute(stmt)).scalars().all()

    train_stats: dict[str, Any] = {}
    if isinstance(model.metrics, dict) and isinstance(model.metrics.get("train_stats"), dict):
        train_stats = model.metrics["train_stats"]

    recent_by_feat: dict[str, list[float]] = {name: [] for name in CLIMATE_FEATURE_NAMES}
    n_predictions = 0
    for details in rows:
        if not isinstance(details, dict):
            continue
        feats = details.get("features")
        if not isinstance(feats, dict):
            continue
        n_predictions += 1
        for name in CLIMATE_FEATURE_NAMES:
            val = feats.get(name)
            if isinstance(val, int | float):
                recent_by_feat[name].append(float(val))

    drift_features: dict[str, dict[str, Any]] = {}
    for name in CLIMATE_FEATURE_NAMES:
        t_stat = train_stats.get(name)
        vals = recent_by_feat[name]
        if not isinstance(t_stat, dict) and not vals:
            continue

        t_mean = float(t_stat.get("mean", 0.0)) if isinstance(t_stat, dict) else None
        t_std = float(t_stat.get("std", 0.0)) if isinstance(t_stat, dict) else None
        recent_mean = round(sum(vals) / len(vals), 4) if vals else None
        recent_std = (
            round(statistics.pstdev(vals), 4)
            if len(vals) >= 2
            else (0.0 if vals else None)
        )

        z_score: float | None = None
        drifted = False
        if t_mean is not None and t_std is not None and recent_mean is not None:
            z_score = round(abs(recent_mean - t_mean) / max(t_std, 1e-6), 2)
            drifted = len(vals) >= 5 and z_score >= 2.0

        drift_features[name] = {
            "train_mean": round(t_mean, 4) if t_mean is not None else None,
            "train_std": round(t_std, 4) if t_std is not None else None,
            "recent_mean": recent_mean,
            "recent_std": recent_std,
            "z_score": z_score,
            "drifted": drifted,
            "n_recent": len(vals),
        }

    return {
        "window_days": window_days,
        "n_predictions": n_predictions,
        "features": drift_features,
    }


def _model_to_response(
    model: MlModel, feature_drift: dict[str, Any] | None = None
) -> MlModelResponse:
    return MlModelResponse(
        id=model.id,
        task=model.task,
        version=model.version,
        feature_version=model.feature_version,
        artifact_path=model.artifact_path,
        trained_at=model.trained_at,
        n_samples=model.n_samples,
        n_greenhouses=model.n_greenhouses,
        source_mix=model.source_mix,
        crops=model.crops,
        metrics=model.metrics,
        baseline_metrics=model.baseline_metrics,
        is_active=model.is_active,
        notes=model.notes,
        feature_drift=feature_drift,
    )


@router.get("/zones/{zone_id}/predictions", response_model=list[PredictionResponse])
async def list_zone_predictions(
    zone_id: uuid.UUID,
    user: CurrentViewer,
    session: DbSession,
    task: Annotated[str, Query(description="yield_forecast")] = "yield_forecast",
    dt_from: Annotated[datetime | None, Query(alias="from")] = None,
    dt_to: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Prediction]:
    """Lấy danh sách các dự báo năng suất (`yield_forecast`) cho zone."""
    if task != "yield_forecast":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="task không hợp lệ cho endpoint cấp zone (chỉ hỗ trợ 'yield_forecast')",
        )
    if dt_from is not None and dt_to is not None and dt_from > dt_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Tham số from phải nhỏ hơn hoặc bằng to",
        )

    await _verify_zone_ownership(session, zone_id, user.farm_id)

    stmt = (
        select(Prediction)
        .where(Prediction.zone_id == zone_id, Prediction.task == "yield_forecast")
        .order_by(desc(Prediction.ts))
        .limit(limit)
    )
    if dt_from is not None:
        stmt = stmt.where(Prediction.ts >= dt_from)
    if dt_to is not None:
        stmt = stmt.where(Prediction.ts <= dt_to)

    return list((await session.execute(stmt)).scalars().all())


@router.get("/models", response_model=list[MlModelResponse])
async def list_models(
    _user: CurrentViewer,
    session: DbSession,
) -> list[MlModelResponse]:
    """Lấy danh sách các phiên bản mô hình AI toàn cục (chỉ số liệu tổng hợp)."""
    stmt = select(MlModel).order_by(desc(MlModel.version))
    models = (await session.execute(stmt)).scalars().all()
    return [_model_to_response(m) for m in models]


@router.get("/models/active", response_model=MlModelResponse | None)
async def get_active_model(
    user: CurrentViewer,
    session: DbSession,
) -> MlModelResponse | None:
    """Lấy mô hình toàn cục đang active kèm feature_drift 7 ngày gần nhất cho farm."""
    stmt = (
        select(MlModel)
        .where(MlModel.task == "yield", MlModel.is_active.is_(True))
        .order_by(desc(MlModel.version))
        .limit(1)
    )
    model = (await session.execute(stmt)).scalar_one_or_none()
    if model is None:
        return None
    drift = await _compute_feature_drift(session, model, user.farm_id)
    return _model_to_response(model, feature_drift=drift)


@router.get("/models/{model_id}", response_model=MlModelResponse)
async def get_model(
    model_id: uuid.UUID,
    user: CurrentViewer,
    session: DbSession,
) -> MlModelResponse:
    """Xem chi tiết thông số, metrics và feature_drift của một mô hình AI."""
    model = (
        await session.execute(select(MlModel).where(MlModel.id == model_id))
    ).scalar_one_or_none()
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy mô hình",
        )
    drift = await _compute_feature_drift(session, model, user.farm_id)
    return _model_to_response(model, feature_drift=drift)

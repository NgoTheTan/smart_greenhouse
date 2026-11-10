"""Router mô hình ML & dự báo: /api/models và /api/zones/{id}/predictions (spec 8.3, 9)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import desc, select, update

from api.deps import CurrentOperator, CurrentViewer, DbSession
from core.models import Greenhouse, MlModel, Prediction, Zone
from core.pubsub import CHANNEL_WORKER, pg_notify
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


@router.get("/zones/{zone_id}/predictions", response_model=list[PredictionResponse])
async def list_zone_predictions(
    zone_id: uuid.UUID,
    user: CurrentViewer,
    session: DbSession,
    task: Annotated[str | None, Query(description="risk_forecast | irrigation_eta")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[Prediction]:
    """Lấy danh sách các dự báo vi khí hậu / rủi ro / thời gian tưới cho zone."""
    await _verify_zone_ownership(session, zone_id, user.farm_id)

    stmt = (
        select(Prediction)
        .where(Prediction.zone_id == zone_id)
        .order_by(desc(Prediction.ts))
        .limit(limit)
    )
    if task is not None:
        stmt = stmt.where(Prediction.task == task)

    return list((await session.execute(stmt)).scalars().all())


@router.get("/models", response_model=list[MlModelResponse])
async def list_models(
    user: CurrentViewer,
    session: DbSession,
    zone_id: Annotated[uuid.UUID | None, Query()] = None,
    task: Annotated[str | None, Query()] = None,
) -> list[MlModel]:
    """Lấy danh sách các mô hình ML đã huấn luyện của farm."""
    # Lấy danh sách zone_id thuộc farm của user
    farm_zone_stmt = (
        select(Zone.id)
        .join(Greenhouse, Zone.greenhouse_id == Greenhouse.id)
        .where(Greenhouse.farm_id == user.farm_id)
    )
    farm_zone_ids = set((await session.execute(farm_zone_stmt)).scalars().all())

    stmt = select(MlModel).order_by(desc(MlModel.trained_at))
    if zone_id is not None:
        if zone_id not in farm_zone_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy zone trong farm của bạn",
            )
        stmt = stmt.where(MlModel.zone_id == zone_id)
    else:
        # Chỉ trả các model thuộc farm_zone_ids hoặc model chung (zone_id IS NULL)
        stmt = stmt.where(
            (MlModel.zone_id.in_(farm_zone_ids)) | (MlModel.zone_id.is_(None))
        )

    if task is not None:
        stmt = stmt.where(MlModel.task == task)

    return list((await session.execute(stmt)).scalars().all())


@router.get("/models/{model_id}", response_model=MlModelResponse)
async def get_model(
    model_id: uuid.UUID,
    user: CurrentViewer,
    session: DbSession,
) -> MlModel:
    """Xem chi tiết thông số và metrics của một mô hình ML."""
    model = (
        await session.execute(select(MlModel).where(MlModel.id == model_id))
    ).scalar_one_or_none()
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy mô hình",
        )

    if model.zone_id is not None:
        await _verify_zone_ownership(session, model.zone_id, user.farm_id)

    return model


@router.post("/models/{model_id}/activate", response_model=MlModelResponse)
async def activate_model(
    model_id: uuid.UUID,
    user: CurrentOperator,
    session: DbSession,
) -> MlModel:
    """Kích hoạt mô hình ML để worker nạp và suy luận thời gian thực."""
    model = (
        await session.execute(select(MlModel).where(MlModel.id == model_id))
    ).scalar_one_or_none()
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy mô hình",
        )

    if model.zone_id is not None:
        await _verify_zone_ownership(session, model.zone_id, user.farm_id)

    # Vô hiệu hoá các model khác cùng task & zone
    deact_stmt = (
        update(MlModel)
        .where(
            MlModel.task == model.task,
            MlModel.zone_id == model.zone_id,
            MlModel.id != model.id,
        )
        .values(is_active=False)
    )
    await session.execute(deact_stmt)

    model.is_active = True
    session.add(model)
    await session.flush()

    # Báo cho worker qua PostgreSQL NOTIFY để hot-reload
    await pg_notify(
        session,
        CHANNEL_WORKER,
        {
            "type": "model_activated",
            "model_id": str(model.id),
            "task": model.task,
            "zone_id": str(model.zone_id) if model.zone_id else None,
        },
    )

    return model

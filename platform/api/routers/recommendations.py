"""Router gợi ý cây trồng theo điều kiện khí hậu nhà kính: /api/greenhouses/{id}/recommendations."""

import uuid

from fastapi import APIRouter, status
from sqlalchemy import desc, select

from api.deps import CurrentOperator, CurrentViewer, DbSession
from api.routers.greenhouses import get_owned_greenhouse
from core.models import Prediction
from core.pubsub import CHANNEL_WORKER, pg_notify
from core.schemas import PredictionResponse, RefreshRecommendationResponse

router = APIRouter(prefix="/greenhouses", tags=["recommendations"])


@router.get("/{gh_id}/recommendations", response_model=PredictionResponse | None)
async def get_greenhouse_recommendations(
    gh_id: uuid.UUID,
    user: CurrentViewer,
    session: DbSession,
) -> Prediction | None:
    """Lấy kết quả gợi ý cây trồng gần nhất của nhà kính (hoặc null nếu chưa có)."""
    await get_owned_greenhouse(session, gh_id, user.farm_id)
    stmt = (
        select(Prediction)
        .where(
            Prediction.greenhouse_id == gh_id,
            Prediction.task == "crop_recommendation",
        )
        .order_by(desc(Prediction.ts))
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


@router.post(
    "/{gh_id}/recommendations/refresh",
    response_model=RefreshRecommendationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_greenhouse_recommendations(
    gh_id: uuid.UUID,
    user: CurrentOperator,
    session: DbSession,
) -> RefreshRecommendationResponse:
    """Yêu cầu worker tính lại ngay gợi ý cây trồng cho nhà kính."""
    await get_owned_greenhouse(session, gh_id, user.farm_id)
    await pg_notify(
        session,
        CHANNEL_WORKER,
        {"type": "recommend", "greenhouse_id": str(gh_id)},
    )
    await session.commit()
    return RefreshRecommendationResponse(status="accepted", greenhouse_id=gh_id)

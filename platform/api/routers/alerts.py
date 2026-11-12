"""Router quản lý cảnh báo: xem danh sách và xác nhận (ack) (spec 6.6, 9)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import desc, select

from api.deps import CurrentOperator, CurrentViewer, DbSession
from core.models import Alert, Greenhouse
from core.pubsub import CHANNEL_WS, pg_notify
from core.schemas import AlertResponse

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertResponse])
async def list_alerts(
    user: CurrentViewer,
    session: DbSession,
    state: Annotated[
        str | None,
        Query(description="Lọc theo trạng thái: open, raised, notified, acknowledged, resolved"),
    ] = None,
    greenhouse_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Alert]:
    """Lấy danh sách cảnh báo của farm, sắp xếp theo thời gian tạo giảm dần."""
    stmt = (
        select(Alert)
        .join(Greenhouse, Alert.greenhouse_id == Greenhouse.id)
        .where(Greenhouse.farm_id == user.farm_id)
        .order_by(desc(Alert.created_at))
        .limit(limit)
    )

    if greenhouse_id is not None:
        stmt = stmt.where(Alert.greenhouse_id == greenhouse_id)

    if state is not None:
        if state == "open":
            stmt = stmt.where(Alert.state != "resolved")
        else:
            stmt = stmt.where(Alert.state == state)

    return list((await session.execute(stmt)).scalars().all())


@router.post("/{alert_id}/ack", response_model=AlertResponse)
async def acknowledge_alert(
    alert_id: uuid.UUID,
    user: CurrentOperator,
    session: DbSession,
) -> Alert:
    """Xác nhận đã tiếp nhận cảnh báo (ngừng leo thang và tắt chuông)."""
    stmt = (
        select(Alert)
        .join(Greenhouse, Alert.greenhouse_id == Greenhouse.id)
        .where(Alert.id == alert_id, Greenhouse.farm_id == user.farm_id)
    )
    alert = (await session.execute(stmt)).scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cảnh báo không tồn tại")

    if alert.state == "resolved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cảnh báo đã được giải quyết",
        )

    now = datetime.now(UTC)
    if alert.state in ("raised", "notified"):
        alert.state = "acknowledged"
        alert.acknowledged_at = now
        alert.acked_by = user.id

        await pg_notify(
            session,
            CHANNEL_WS,
            {
                "farm_id": str(user.farm_id),
                "type": "alert",
                "data": {
                    "id": str(alert.id),
                    "greenhouse_id": str(alert.greenhouse_id),
                    "zone_id": str(alert.zone_id) if alert.zone_id else None,
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "state": alert.state,
                    "dedupe_key": alert.dedupe_key,
                    "payload": alert.payload,
                    "created_at": alert.created_at.isoformat(),
                    "notified_at": alert.notified_at.isoformat() if alert.notified_at else None,
                    "escalated_at": alert.escalated_at.isoformat() if alert.escalated_at else None,
                    "acknowledged_at": alert.acknowledged_at.isoformat(),
                    "acked_by": str(user.id),
                    "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
                },
            },
        )
        await session.commit()

    return alert

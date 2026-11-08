"""Router Web Push & Tuỳ chọn thông báo cá nhân (spec 6.7, 9)."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import delete, select

from api.deps import CurrentViewer, DbSession
from core.config import get_settings
from core.models import NotificationPref, PushSubscription
from core.schemas import (
    NotificationPrefResponse,
    NotificationPrefUpdateRequest,
    PushPublicKeyResponse,
    PushSubscribeRequest,
    PushUnsubscribeRequest,
)

router = APIRouter(tags=["push"])


@router.get("/push/public-key", response_model=PushPublicKeyResponse)
async def get_vapid_public_key(_user: CurrentViewer) -> dict[str, str]:
    """Lấy VAPID public key để trình duyệt đăng ký Web Push."""
    s = get_settings()
    if not s.vapid_public_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="VAPID chưa được cấu hình trên máy chủ",
        )
    return {"public_key": s.vapid_public_key}


@router.post("/push/subscribe", status_code=status.HTTP_201_CREATED)
async def subscribe_push(
    request: Request,
    body: PushSubscribeRequest,
    user: CurrentViewer,
    session: DbSession,
) -> dict[str, str]:
    """Đăng ký subscription Web Push của trình duyệt cho người dùng hiện tại."""
    now = datetime.now(UTC)
    user_agent = request.headers.get("user-agent")

    stmt = select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    sub = (await session.execute(stmt)).scalar_one_or_none()

    if sub is not None:
        sub.user_id = user.id
        sub.p256dh = body.keys.p256dh
        sub.auth = body.keys.auth
        sub.user_agent = user_agent
        sub.last_used_at = now
    else:
        sub = PushSubscription(
            user_id=user.id,
            endpoint=body.endpoint,
            p256dh=body.keys.p256dh,
            auth=body.keys.auth,
            user_agent=user_agent,
            created_at=now,
            last_used_at=now,
        )
        session.add(sub)

    await session.commit()
    return {"status": "ok"}


@router.delete("/push/subscribe")
async def unsubscribe_push(
    body: PushUnsubscribeRequest,
    user: CurrentViewer,
    session: DbSession,
) -> dict[str, str]:
    """Hủy đăng ký subscription Web Push."""
    await session.execute(
        delete(PushSubscription).where(
            PushSubscription.user_id == user.id,
            PushSubscription.endpoint == body.endpoint,
        )
    )
    await session.commit()
    return {"status": "ok"}


@router.get("/me/notification-prefs", response_model=NotificationPrefResponse)
async def get_notification_preferences(
    user: CurrentViewer,
    session: DbSession,
) -> NotificationPref:
    """Lấy tuỳ chọn nhận thông báo của người dùng hiện tại (tạo mặc định nếu chưa có)."""
    pref = await session.get(NotificationPref, user.id)
    if pref is None:
        pref = NotificationPref(
            user_id=user.id,
            push_enabled=True,
            email_enabled=True,
            min_severity="warning",
        )
        session.add(pref)
        await session.commit()
        await session.refresh(pref)
    return pref


@router.put("/me/notification-prefs", response_model=NotificationPrefResponse)
async def update_notification_preferences(
    body: NotificationPrefUpdateRequest,
    user: CurrentViewer,
    session: DbSession,
) -> NotificationPref:
    """Cập nhật tuỳ chọn nhận thông báo (kênh Web Push, Email và mức độ nghiêm trọng tối thiểu)."""
    pref = await session.get(NotificationPref, user.id)
    if pref is None:
        pref = NotificationPref(
            user_id=user.id,
            push_enabled=True,
            email_enabled=True,
            min_severity="warning",
        )
        session.add(pref)

    if body.push_enabled is not None:
        pref.push_enabled = body.push_enabled
    if body.email_enabled is not None:
        pref.email_enabled = body.email_enabled
    if body.min_severity is not None:
        pref.min_severity = body.min_severity

    await session.commit()
    await session.refresh(pref)
    return pref

"""Alert Service: vòng đời raised->notified->acknowledged->resolved, dedupe, leo thang."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.models import Alert
from worker.notify import send_alert_notifications

log = logging.getLogger("worker.alerts")


async def raise_alert(
    session: AsyncSession,
    greenhouse_id: uuid.UUID,
    alert_type: str,
    severity: str,
    dedupe_key: str,
    zone_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> tuple[Alert, bool]:
    """Tạo alert mới hoặc cập nhật alert đang mở theo dedupe_key (tránh spam).

    Trả về (alert, is_new).
    """
    now = now or datetime.now(UTC)
    s = get_settings()

    stmt = select(Alert).where(Alert.dedupe_key == dedupe_key, Alert.state != "resolved")
    alert = (await session.execute(stmt)).scalar_one_or_none()

    if alert is None:
        alert = Alert(
            id=uuid.uuid4(),
            greenhouse_id=greenhouse_id,
            zone_id=zone_id,
            alert_type=alert_type,
            severity=severity,
            dedupe_key=dedupe_key,
            payload=payload,
            state="raised",
            created_at=now,
        )
        session.add(alert)
        await session.flush()

        try:
            await send_alert_notifications(session, alert, is_escalation=False, now=now)
            alert.state = "notified"
            alert.notified_at = now
        except Exception:  # noqa: BLE001
            log.exception("Lỗi gửi thông báo cho alert mới %s", alert.id)

        log.info(
            "Raised alert %s (type=%s, sev=%s, key=%s)",
            alert.id,
            alert_type,
            severity,
            dedupe_key,
        )
        return alert, True

    # Alert đang mở đã tồn tại: cập nhật payload và kiểm tra cooldown
    if payload is not None:
        alert.payload = payload
    if severity != alert.severity:
        alert.severity = severity

    if alert.state == "acknowledged":
        # Người dùng đã xác nhận, không gửi thông báo nhắc lại
        return alert, False

    last_notified = alert.notified_at or alert.created_at
    cooldown = timedelta(minutes=s.alert_cooldown_min)
    if now - last_notified >= cooldown:
        log.info(
            "Gửi lại thông báo nhắc nhở cho alert %s sau cooldown %s phút",
            alert.id,
            s.alert_cooldown_min,
        )
        try:
            await send_alert_notifications(session, alert, is_escalation=False, now=now)
            alert.notified_at = now
            alert.state = "notified"
        except Exception:  # noqa: BLE001
            log.exception("Lỗi gửi thông báo nhắc nhở cho alert %s", alert.id)

    return alert, False


async def resolve_alert(
    session: AsyncSession,
    dedupe_key: str,
    now: datetime | None = None,
) -> Alert | None:
    """Tự động chuyển alert mở có dedupe_key sang resolved khi hết điều kiện (hysteresis)."""
    now = now or datetime.now(UTC)

    stmt = select(Alert).where(Alert.dedupe_key == dedupe_key, Alert.state != "resolved")
    alert = (await session.execute(stmt)).scalar_one_or_none()

    if alert is None:
        return None

    alert.state = "resolved"
    alert.resolved_at = now
    log.info("Resolved alert %s (key=%s)", alert.id, dedupe_key)

    try:
        # Phát WS sự kiện để cập nhật UI/đóng badge ngay
        await send_alert_notifications(session, alert, is_escalation=False, now=now)
    except Exception:  # noqa: BLE001
        log.exception("Lỗi phát thông báo resolved cho alert %s", alert.id)

    return alert


async def escalate_alerts(
    session: AsyncSession,
    now: datetime | None = None,
) -> list[Alert]:
    """Quét các alert critical chưa ack sau escalate_after_min để gửi push và email."""
    now = now or datetime.now(UTC)
    s = get_settings()

    threshold = now - timedelta(minutes=s.escalate_after_min)
    stmt = select(Alert).where(
        Alert.severity == "critical",
        Alert.state.in_(["raised", "notified"]),
        Alert.escalated_at.is_(None),
        Alert.created_at <= threshold,
    )
    alerts = (await session.execute(stmt)).scalars().all()

    escalated: list[Alert] = []
    for a in alerts:
        a.escalated_at = now
        log.warning(
            "Leo thang cảnh báo nghiêm trọng %s (type=%s, key=%s) sau %s phút",
            a.id,
            a.alert_type,
            a.dedupe_key,
            s.escalate_after_min,
        )
        try:
            await send_alert_notifications(session, a, is_escalation=True, now=now)
            escalated.append(a)
        except Exception:  # noqa: BLE001
            log.exception("Lỗi khi leo thang alert %s", a.id)

    return escalated

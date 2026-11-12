"""Notification Service: Web Push (pywebpush), email (aiosmtplib), sự kiện in-app (spec 6.7)."""

import asyncio
import json
import logging
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

import aiosmtplib
from pywebpush import WebPushException, webpush
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.models import Alert, Greenhouse, NotificationPref, PushSubscription, User, Zone
from core.pubsub import CHANNEL_WS, pg_notify

log = logging.getLogger("worker.notify")

SEVERITY_RANK: dict[str, int] = {
    "info": 1,
    "warning": 2,
    "critical": 3,
}

ALERT_TITLES: dict[str, str] = {
    "DISEASE_RISK": "CẢNH BÁO: Nguy cơ nấm bệnh",
    "HEAT_STRESS": "CẢNH BÁO: Sốc nhiệt",
    "SOIL_DRY": "CẢNH BÁO: Đất quá khô",
    "SENSOR_FAULT": "CẢNH BÁO: Lỗi cảm biến",
    "DEVICE_OFFLINE": "CẢNH BÁO: Mất kết nối Gateway",
    "FAILSAFE_ACTIVE": "CẢNH BÁO: Chế độ an toàn (Failsafe)",
    "MAINTENANCE": "THÔNG BÁO: Yêu cầu bảo trì",
    "YIELD_FORECAST_LOW": "THÔNG BÁO: Năng suất dự kiến thấp",
}


def get_alert_title(alert_type: str) -> str:
    return ALERT_TITLES.get(alert_type, f"CẢNH BÁO: {alert_type}")


def format_alert_body(
    alert: Alert,
    greenhouse_name: str | None = None,
    zone_name: str | None = None,
) -> str:
    loc_parts = []
    if greenhouse_name:
        loc_parts.append(greenhouse_name)
    if zone_name:
        loc_parts.append(zone_name)
    location = " - ".join(loc_parts) if loc_parts else "Nhà kính"

    payload: dict[str, Any] = alert.payload or {}
    type_ = alert.alert_type

    if type_ == "DISEASE_RISK":
        vpd = payload.get("vpd")
        rh = payload.get("air_rh")
        mins = payload.get("fungal_minutes")
        details = []
        if vpd is not None:
            details.append(f"VPD {vpd:.2f} kPa")
        if rh is not None:
            details.append(f"RH {rh:.0f}%")
        if mins is not None:
            details.append(f"tích luỹ {mins:.0f} phút")
        detail_str = f" ({', '.join(details)})" if details else ""
        return f"{location}: Nguy cơ nấm bệnh cao{detail_str}. Quạt thông gió đã được kích hoạt."

    if type_ == "YIELD_FORECAST_LOW":
        expected = payload.get("value") or payload.get("expected_kg_m2")
        rel = payload.get("score") or payload.get("relative_yield")
        if expected is not None and rel is not None:
            pct = int(round(float(rel) * 100))
            return (
                f"{location}: Năng suất dự kiến thấp ({float(expected):.2f} kg/m², "
                f"≈ {pct}% mức tham chiếu)."
            )
        return payload.get("body") or f"{location}: Năng suất dự kiến thấp hơn ngưỡng tham chiếu."

    if type_ == "HEAT_STRESS":
        temp = payload.get("air_temp")
        temp_str = f" ({temp:.1f}°C)" if temp is not None else ""
        return f"{location}: Nhiệt độ nguy hiểm{temp_str}. Đang bật thông gió giải nhiệt."

    if type_ == "SOIL_DRY":
        soil = payload.get("soil_moisture")
        soil_str = f" ({soil:.1f}%)" if soil is not None else ""
        return f"{location}: Độ ẩm đất xuống quá thấp{soil_str}. Cần kiểm tra hệ thống tưới."

    if type_ == "SENSOR_FAULT":
        quality = payload.get("quality", "lỗi")
        return (
            f"{location}: Cảm biến bất thường ({quality}). "
            "Hệ thống tạm dừng điều khiển tự động cho zone."
        )

    if type_ == "DEVICE_OFFLINE":
        return f"{location}: Gateway mất kết nối. Hệ thống chuyển sang failsafe cục bộ."

    if type_ == "FAILSAFE_ACTIVE":
        reason = payload.get("reason", "mất tín hiệu")
        return f"{location}: Gateway kích hoạt chế độ an toàn cục bộ ({reason})."

    return f"{location}: Phát hiện sự cố mức {alert.severity} ({type_})."


def _send_single_webpush_sync(
    sub_info: dict[str, Any],
    payload_str: str,
    private_key: str,
    subject: str,
) -> None:
    claims = {"sub": subject}
    webpush(
        subscription_info=sub_info,
        data=payload_str,
        vapid_private_key=private_key,
        vapid_claims=claims,
    )


async def send_webpush_to_subscription(
    session: AsyncSession,
    sub: PushSubscription,
    payload_dict: dict[str, Any],
    private_key: str,
    subject: str,
    now: datetime,
) -> bool:
    sub_info = {
        "endpoint": sub.endpoint,
        "keys": {
            "p256dh": sub.p256dh,
            "auth": sub.auth,
        },
    }
    payload_str = json.dumps(payload_dict, ensure_ascii=False)

    try:
        await asyncio.to_thread(
            _send_single_webpush_sync,
            sub_info=sub_info,
            payload_str=payload_str,
            private_key=private_key,
            subject=subject,
        )
        sub.last_used_at = now
        return True
    except WebPushException as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (404, 410):
            log.info("Xoá subscription hết hạn hoặc bị hủy (HTTP %s): %s", status, sub.endpoint)
            await session.execute(
                delete(PushSubscription).where(PushSubscription.id == sub.id)
            )
        else:
            log.warning("Lỗi WebPush (HTTP %s): %s", status, exc)
        return False
    except Exception as exc:  # noqa: BLE001
        log.warning("Lỗi không mong muốn khi gửi WebPush tới %s: %s", sub.endpoint, exc)
        return False


async def send_escalation_email(
    recipients: list[str],
    subject_text: str,
    body_text: str,
) -> None:
    s = get_settings()
    if not s.smtp_host or not recipients:
        log.debug("Bỏ qua gửi email: smtp_host chưa cấu hình hoặc không có người nhận")
        return

    msg = EmailMessage()
    msg["Subject"] = f"[GreenHub] {subject_text}"
    msg["From"] = s.alert_email_from
    msg["To"] = ", ".join(recipients)
    msg.set_content(body_text)

    try:
        await aiosmtplib.send(
            msg,
            hostname=s.smtp_host,
            port=s.smtp_port,
            username=s.smtp_user or None,
            password=s.smtp_password or None,
            use_tls=s.smtp_tls,
        )
        log.info("Đã gửi email leo thang tới %d người nhận", len(recipients))
    except Exception as exc:  # noqa: BLE001
        log.warning("Không thể gửi email leo thang qua SMTP %s: %s", s.smtp_host, exc)


async def send_alert_notifications(
    session: AsyncSession,
    alert: Alert,
    is_escalation: bool = False,
    now: datetime | None = None,
) -> int:
    """Gửi thông báo đa tầng: WebSocket in-app + Web Push + Email (khi leo thang)."""
    now = now or datetime.now(UTC)
    s = get_settings()

    gh = await session.get(Greenhouse, alert.greenhouse_id)
    if gh is None:
        log.warning("Không tìm thấy Greenhouse %s cho alert %s", alert.greenhouse_id, alert.id)
        return 0

    zone: Zone | None = None
    if alert.zone_id is not None:
        zone = await session.get(Zone, alert.zone_id)

    gh_name = gh.name
    zone_name = zone.name if zone is not None else None
    title = get_alert_title(alert.alert_type)
    body = format_alert_body(alert, greenhouse_name=gh_name, zone_name=zone_name)
    target_url = f"/zones/{alert.zone_id}" if alert.zone_id else f"/greenhouses/{gh.id}"

    # 1. Kênh In-app WebSocket
    await pg_notify(
        session,
        CHANNEL_WS,
        {
            "farm_id": str(gh.farm_id),
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
                "acknowledged_at": (
                    alert.acknowledged_at.isoformat() if alert.acknowledged_at else None
                ),
                "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
                "title": title,
                "body": body,
                "url": target_url,
            },
        },
    )

    # Lấy danh sách Users thuộc farm và kiểm tra NotificationPref
    users_stmt = (
        select(User, NotificationPref)
        .outerjoin(NotificationPref, NotificationPref.user_id == User.id)
        .where(User.farm_id == gh.farm_id)
    )
    user_rows = (await session.execute(users_stmt)).all()

    alert_sev_rank = SEVERITY_RANK.get(alert.severity, 1)
    eligible_user_ids: list[Any] = []
    email_recipients: list[str] = []

    for u, pref in user_rows:
        push_enabled = pref.push_enabled if pref is not None else True
        email_enabled = pref.email_enabled if pref is not None else True
        min_sev = pref.min_severity if pref is not None else "warning"
        min_rank = SEVERITY_RANK.get(min_sev, 2)

        if push_enabled and alert_sev_rank >= min_rank:
            eligible_user_ids.append(u.id)

        if is_escalation and email_enabled and alert_sev_rank >= min_rank and u.email:
            email_recipients.append(u.email)

    push_sent_count = 0
    if eligible_user_ids and s.vapid_private_key and s.vapid_subject:
        subs_stmt = select(PushSubscription).where(
            PushSubscription.user_id.in_(eligible_user_ids)
        )
        subs = (await session.execute(subs_stmt)).scalars().all()

        push_payload = {
            "title": title,
            "body": body,
            "tag": alert.dedupe_key,
            "severity": alert.severity,
            "url": target_url,
        }

        for sub in subs:
            success = await send_webpush_to_subscription(
                session=session,
                sub=sub,
                payload_dict=push_payload,
                private_key=s.vapid_private_key,
                subject=s.vapid_subject,
                now=now,
            )
            if success:
                push_sent_count += 1

    # 3. Kênh Email (chỉ khi leo thang critical)
    if is_escalation and email_recipients:
        email_subject = f"LEO THANG: {title}"
        email_body = (
            f"Hệ thống GreenHub phát hiện cảnh báo nghiêm trọng chưa được xác nhận:\n\n"
            f"Loại cảnh báo: {alert.alert_type} (Mức độ: {alert.severity.upper()})\n"
            f"Vị trí: {gh_name}" + (f" - {zone_name}" if zone_name else "") + "\n"
            f"Nội dung: {body}\n"
            f"Thời điểm phát hiện: {alert.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
            f"Vui lòng truy cập Web Console để kiểm tra và xử lý kịp thời: {s.domain}{target_url}"
        )
        await send_escalation_email(
            recipients=email_recipients,
            subject_text=email_subject,
            body_text=email_body,
        )

    return push_sent_count

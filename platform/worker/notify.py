"""Notification Service: phát sự kiện cảnh báo thời gian thực In-app qua WebSocket (spec 6.7)."""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Alert, Greenhouse, Zone
from core.pubsub import CHANNEL_WS, pg_notify

log = logging.getLogger("worker.notify")

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


async def send_alert_notifications(
    session: AsyncSession,
    alert: Alert,
    now: datetime | None = None,
) -> int:
    """Phát sự kiện cảnh báo In-app qua kênh PostgreSQL ws_events tới WebSocket của farm."""
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
    return 1

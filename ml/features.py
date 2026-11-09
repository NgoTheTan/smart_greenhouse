"""Trích xuất đặc trưng cho các mô hình AI/ML của GreenHub (spec mục 8).

Bao gồm:
- Tầng A2: Đặc trưng dự báo tưới (irrigation_eta), độ nhạy bơm (pump_response), quạt (fan_response).
- Tầng A3: Đặc trưng dự báo nguy cơ nấm / vi khí hậu (risk_forecast).
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any


def calculate_vpd(temp_c: float, rh_pct: float) -> float:
    """Tính VPD (kPa) theo công thức Tetens."""
    if temp_c is None or rh_pct is None:
        return 0.0
    vp_sat = 0.61078 * math.exp((17.27 * temp_c) / (temp_c + 237.3))
    vpd = vp_sat * (1.0 - (rh_pct / 100.0))
    return max(0.0, round(vpd, 3))


def extract_slope(values: list[float], interval_minutes: float = 1.0) -> float:
    """Tính tốc độ thay đổi (độ dốc slope) của chuỗi giá trị theo thời gian."""
    if len(values) < 2:
        return 0.0
    n = len(values)
    x = [i * interval_minutes for i in range(n)]
    x_mean = sum(x) / n
    y_mean = sum(values) / n
    numerator = sum((x[i] - x_mean) * (values[i] - y_mean) for i in range(n))
    denominator = sum((x[i] - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def extract_irrigation_eta_features(
    readings_window: list[dict[str, Any]],
    soil_min: float = 45.0,
) -> dict[str, float] | None:
    """Trích xuất vector đặc trưng cho bài toán irrigation_eta.

    Input: danh sách readings gần nhất được sắp xếp theo thời gian tăng dần.
    Đặc trưng:
    - soil_now: độ ẩm đất hiện tại (%)
    - soil_slope: tốc độ giảm ẩm (% / phút)
    - air_t: nhiệt độ không khí (°C)
    - vpd: áp suất hơi nước thiếu hụt (kPa)
    - lux: cường độ sáng
    - hour_of_day: giờ trong ngày (0 - 23)
    """
    if not readings_window:
        return None

    latest = readings_window[-1]
    soil_values = [
        r["soil_moisture"]
        for r in readings_window
        if r.get("soil_moisture") is not None
    ]
    if len(soil_values) < 3:
        return None

    soil_now = soil_values[-1]
    soil_slope = extract_slope(soil_values)

    # Lấy giờ trong ngày từ timestamp
    ts = latest.get("ts")
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    elif not isinstance(ts, datetime):
        ts = datetime.utcnow()
    hour = ts.hour

    temp = latest.get("air_temp", 25.0)
    rh = latest.get("air_rh", 70.0)
    vpd = latest.get("vpd") or calculate_vpd(temp, rh)
    lux = latest.get("lux", 0.0) or 0.0

    return {
        "soil_now": float(soil_now),
        "soil_slope": float(soil_slope),
        "air_t": float(temp),
        "vpd": float(vpd),
        "lux": float(lux),
        "hour_of_day": float(hour),
    }


def extract_risk_forecast_features(
    readings_window: list[dict[str, Any]],
) -> dict[str, float] | None:
    """Trích xuất vector đặc trưng cho bài toán dự báo rủi ro (risk_forecast) trong 15 phút tới.

    Đặc trưng:
    - vpd_now, vpd_slope
    - temp_now, temp_slope
    - rh_now, rh_slope
    - lux_now
    - hour_of_day
    """
    if len(readings_window) < 3:
        return None

    latest = readings_window[-1]
    vpds = [
        r.get("vpd") or calculate_vpd(r.get("air_temp", 25.0), r.get("air_rh", 70.0))
        for r in readings_window
    ]
    temps = [r.get("air_temp", 25.0) for r in readings_window]
    rhs = [r.get("air_rh", 70.0) for r in readings_window]

    ts = latest.get("ts")
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    elif not isinstance(ts, datetime):
        ts = datetime.utcnow()

    return {
        "vpd_now": float(vpds[-1]),
        "vpd_slope": float(extract_slope(vpds)),
        "temp_now": float(temps[-1]),
        "temp_slope": float(extract_slope(temps)),
        "rh_now": float(rhs[-1]),
        "rh_slope": float(extract_slope(rhs)),
        "lux_now": float(latest.get("lux") or 0.0),
        "hour_of_day": float(ts.hour),
    }


def extract_actuator_response(
    events: list[dict[str, Any]],
    actuator: str = "pump_1",
) -> float:
    """Tính gain trung vị (median) của actuator:

    - pump: Δsoil / duration_s (% / giây)
    - fan: ΔVPD / duration_s (kPa / giây)
    """
    gains: list[float] = []
    for ev in events:
        if ev.get("actuator") != actuator:
            continue
        duration = ev.get("duration_s", 0)
        delta = ev.get("delta", 0.0)
        if duration > 0 and delta > 0:
            gains.append(delta / duration)

    if not gains:
        return 0.5 if "pump" in actuator else 0.01  # Giá trị khởi tạo an toàn

    gains.sort()
    mid = len(gains) // 2
    return gains[mid]

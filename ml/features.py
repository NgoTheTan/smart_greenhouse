"""Trích xuất đặc trưng cho các mô hình AI/ML của GreenHub (spec mục 8).

Bao gồm:
- Tầng A2: Đặc trưng dự báo tưới (irrigation_eta), độ nhạy bơm (pump_response), quạt (fan_response).
- Tầng A3: Đặc trưng dự báo nguy cơ nấm / vi khí hậu (risk_forecast).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def calculate_vpd(temp_c: float, rh_pct: float) -> float:
    """Tính VPD (kPa) theo công thức Tetens.

    Giả định T_lá = T_khí (ghi rõ trong báo cáo per spec mục 17).
    RH được clamp vào [0, 100] để tránh VPD âm (khi RH > 100%) hoặc bùng nổ (khi RH âm).
    """
    if temp_c is None or rh_pct is None:
        return 0.0
    rh_safe = max(0.0, min(100.0, float(rh_pct)))
    vp_sat = 0.61078 * math.exp((17.27 * float(temp_c)) / (float(temp_c) + 237.3))
    vpd = vp_sat * (1.0 - (rh_safe / 100.0))
    return max(0.0, round(vpd, 3))


def _infer_interval_minutes(readings_window: list[dict[str, Any]]) -> float:
    """Suy luận khoảng cách thời gian giữa các điểm đo (phút) từ timestamps.

    Dùng trung bình giữa 2 điểm đầu và cuối để tránh outlier.
    Fallback: 1 phút nếu không có timestamps hoặc window < 2 phần tử.
    """
    if len(readings_window) < 2:
        return 1.0
    ts_first = readings_window[0].get("ts")
    ts_last = readings_window[-1].get("ts")
    if not (ts_first and ts_last):
        return 1.0
    if isinstance(ts_first, str):
        ts_first = datetime.fromisoformat(ts_first)
    if isinstance(ts_last, str):
        ts_last = datetime.fromisoformat(ts_last)
    total_minutes = (ts_last - ts_first).total_seconds() / 60.0
    n_intervals = len(readings_window) - 1
    if total_minutes <= 0 or n_intervals <= 0:
        return 1.0
    return total_minutes / n_intervals


def extract_slope(values: list[float], interval_minutes: float = 1.0) -> float:
    """Tính tốc độ thay đổi (độ dốc slope) của chuỗi giá trị theo thời gian (đơn vị/phút).

    QUAN TRỌNG: interval_minutes phải khớp với khoảng cách đo thực tế.
    Nếu cảm biến đo mỗi 5 phút thì truyền interval_minutes=5.0.
    Kết quả trả về có đơn vị: (đơn vị_Y) / phút.
    """
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
    Trả về None nếu không đủ dữ liệu tốt.

    Đặc trưng:
    - soil_now: độ ẩm đất hiện tại (%)
    - soil_slope: tốc độ giảm ẩm (% / phút) — âm là đang khô
    - air_t: nhiệt độ không khí (°C)
    - vpd: áp suất hơi nước thiếu hụt (kPa)
    - lux: cường độ sáng (lux)
    - hour_of_day: giờ trong ngày (0 – 23)
    """
    if not readings_window:
        return None

    latest = readings_window[-1]
    soil_values = [
        r["soil_moisture"]
        for r in readings_window
        if r.get("soil_moisture") is not None and r.get("quality", "ok") == "ok"
    ]
    if len(soil_values) < 3:
        return None

    # BUG FIX: suy luận interval thực tế từ timestamps, không dùng mặc định 1 phút
    interval_min = _infer_interval_minutes(readings_window)
    soil_now = soil_values[-1]
    soil_slope = extract_slope(soil_values, interval_minutes=interval_min)

    # Lấy giờ trong ngày từ timestamp
    ts = latest.get("ts")
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    elif not isinstance(ts, datetime):
        ts = datetime.now(timezone.utc)
    hour = ts.hour

    temp = latest.get("air_temp", 25.0) or 25.0
    rh = latest.get("air_rh", 70.0) or 70.0
    vpd = latest.get("vpd") or calculate_vpd(temp, rh)
    lux = latest.get("lux", 0.0) or 0.0

    return {
        "soil_now": float(soil_now),
        "soil_slope": float(soil_slope),
        "air_t": float(temp),
        "vpd": float(vpd),
        "lux": float(lux),
        "hour_of_day": float(hour),
        "interval_minutes": float(interval_min),  # giữ lại cho debug/logging
    }


def extract_risk_forecast_features(
    readings_window: list[dict[str, Any]],
) -> dict[str, float] | None:
    """Trích xuất vector đặc trưng cho bài toán dự báo rủi ro (risk_forecast) trong 15 phút tới.

    Chỉ dùng bản ghi có quality='ok'. Trả về None nếu không đủ 3 điểm sạch.

    Đặc trưng:
    - vpd_now, vpd_slope (kPa, kPa/phút)
    - temp_now, temp_slope (°C, °C/phút)
    - rh_now, rh_slope (%, %/phút)
    - lux_now (lux)
    - hour_of_day (0 – 23)
    """
    clean = [r for r in readings_window if r.get("quality", "ok") == "ok"]
    if len(clean) < 3:
        return None

    latest = clean[-1]
    interval_min = _infer_interval_minutes(clean)

    vpds = [
        r.get("vpd") or calculate_vpd(r.get("air_temp", 25.0), r.get("air_rh", 70.0))
        for r in clean
    ]
    temps = [r.get("air_temp", 25.0) or 25.0 for r in clean]
    rhs = [r.get("air_rh", 70.0) or 70.0 for r in clean]

    ts = latest.get("ts")
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    elif not isinstance(ts, datetime):
        ts = datetime.now(timezone.utc)

    return {
        "vpd_now": float(vpds[-1]),
        "vpd_slope": float(extract_slope(vpds, interval_minutes=interval_min)),
        "temp_now": float(temps[-1]),
        "temp_slope": float(extract_slope(temps, interval_minutes=interval_min)),
        "rh_now": float(rhs[-1]),
        "rh_slope": float(extract_slope(rhs, interval_minutes=interval_min)),
        "lux_now": float(latest.get("lux") or 0.0),
        "hour_of_day": float(ts.hour),
    }


def extract_actuator_response(
    events: list[dict[str, Any]],
    actuator: str = "pump_1",
) -> float:
    """Tính gain trung vị (median) của actuator từ lịch sử sự kiện đã ACK.

    Đơn vị:
    - pump: Δsoil / duration_s  → % / giây
    - fan:  ΔVPD  / duration_s  → kPa / giây

    Yêu cầu tối thiểu 5 sự kiện (spec min_events=5) để kết quả đáng tin cậy.
    Fallback khi chưa đủ dữ liệu: giá trị khởi tạo an toàn.
    """
    MIN_EVENTS = 5
    gains: list[float] = []
    for ev in events:
        if ev.get("actuator") != actuator:
            continue
        duration = ev.get("duration_s", 0)
        delta = ev.get("delta", 0.0)
        if duration > 0 and delta > 0:
            gains.append(float(delta) / float(duration))

    if len(gains) < MIN_EVENTS:
        # Chưa đủ sự kiện → dùng giá trị khởi tạo an toàn
        return 0.5 if "pump" in actuator else 0.01

    gains.sort()
    mid = len(gains) // 2
    return gains[mid]

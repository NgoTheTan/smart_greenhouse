"""Công thức vi khí hậu: VPsat, VPD, PPFD, DLI và chỉ số rủi ro chuẩn hoá (spec 6.4, Phụ lục B)."""

import math
from collections.abc import Sequence
from datetime import datetime

PPFD_PER_LUX = 0.0185


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def calc_vpsat(temp_c: float) -> float:
    """Áp suất hơi bão hoà theo công thức Tetens (kPa, T tính bằng °C)."""
    return 0.61078 * math.exp((17.27 * temp_c) / (temp_c + 237.3))


def calc_vpd(air_temp_c: float, air_rh: float, leaf_offset_c: float = 1.0) -> float:
    """Chênh lệch áp suất hơi nước giữa lá và không khí (kPa).

    T_lá = T_khí - leaf_offset_c. Khi xảy ra ngưng tụ (VPair > VPsat(T_lá)), kẹp biên dưới tại 0.0.
    """
    rh_clamped = clamp(air_rh, 0.0, 100.0)
    vp_air = calc_vpsat(air_temp_c) * (rh_clamped / 100.0)
    vp_leaf = calc_vpsat(air_temp_c - leaf_offset_c)
    return max(0.0, vp_leaf - vp_air)


def lux_to_ppfd(lux: float | None) -> float | None:
    """Xấp xỉ mật độ thông lượng photon quang hợp (µmol/m²/s) cho ánh sáng mặt trời."""
    if lux is None or lux < 0:
        return None
    return lux * PPFD_PER_LUX


def integrate_dli(
    samples: Sequence[tuple[datetime, float | None]],
    max_gap_s: float = 180.0,
) -> float:
    """Tích luỹ ánh sáng ngày DLI (mol/m²/ngày) từ chuỗi (ts, lux) đã sắp xếp tăng dần.

    Khoảng cách Δt giữa hai bản tin liên tiếp bị chặn trên bởi `max_gap_s` (mặc định 3 * 60s)
    để việc mất kết nối kéo dài không cộng dồn giả tạo ánh sáng buổi trưa.
    """
    if len(samples) < 2:
        return 0.0

    total_umol = 0.0
    prev_ts, prev_lux = samples[0]
    for ts, lux in samples[1:]:
        dt_s = (ts - prev_ts).total_seconds()
        if dt_s > 0 and prev_lux is not None and lux is not None:
            eff_dt = min(dt_s, max_gap_s)
            avg_ppfd = 0.5 * ((prev_lux + lux) * PPFD_PER_LUX)
            total_umol += max(0.0, avg_ppfd) * eff_dt
        prev_ts, prev_lux = ts, lux

    return total_umol / 1_000_000.0


def calc_risk_vpd_low(vpd: float, vpd_opt_low: float, vpd_low_crit: float) -> float:
    """Rủi ro chuẩn hoá VPD thấp [0..1] (Phụ lục B)."""
    denom = vpd_opt_low - vpd_low_crit
    if denom <= 0:
        return 1.0 if vpd <= vpd_low_crit else 0.0
    return clamp((vpd_opt_low - vpd) / denom, 0.0, 1.0)


def calc_risk_heat(air_t: float, temp_opt_high: float, temp_crit_high: float) -> float:
    """Rủi ro chuẩn hoá nhiệt cao [0..1] (Phụ lục B)."""
    denom = temp_crit_high - temp_opt_high
    if denom <= 0:
        return 1.0 if air_t >= temp_crit_high else 0.0
    return clamp((air_t - temp_opt_high) / denom, 0.0, 1.0)

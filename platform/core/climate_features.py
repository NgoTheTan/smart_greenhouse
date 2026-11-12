"""Trích xuất đặc trưng khí hậu dùng chung (feature_version = 1) bằng Python thuần.

Module này KHÔNG import pandas, numpy, scikit-learn hay lightgbm để dùng chung an toàn
giữa `worker`, `ml/` và `tools/simulator` mà không làm phình bộ nhớ tiến trình khác.
"""

import math
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from core.vpd import PPFD_PER_LUX, calc_vpd, clamp

FEATURE_VERSION = 1

CLIMATE_FEATURE_NAMES: tuple[str, ...] = (
    "t_mean",
    "t_day_mean",
    "t_night_mean",
    "t_p95",
    "t_p05",
    "rh_mean",
    "vpd_mean",
    "vpd_std",
    "frac_vpd_low",
    "frac_vpd_high",
    "frac_t_gt_30",
    "frac_t_lt_12",
    "gdd_per_day",
    "dli_mean",
    "soil_mean",
    "soil_std",
)


@dataclass(frozen=True)
class ClimateBucket:
    """Một bucket dữ liệu đã tổng hợp (`readings_1h` hoặc `readings_1m` với `quality = 'ok'`)."""

    ts: datetime
    air_temp: float | None
    air_rh: float | None
    vpd: float | None = None
    soil_moisture: float | None = None
    lux: float | None = None


@dataclass(frozen=True)
class ClimateFeatureResult:
    feature_version: int
    features: dict[str, float | None]
    coverage: float
    valid_buckets: int
    expected_buckets: int
    window_hours: float


def _normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _linear_percentile(sorted_vals: Sequence[float], q: float) -> float:
    """Nội suy tuyến tính phân vị q ∈ [0, 1] trên danh sách đã sắp xếp tăng dần."""
    n = len(sorted_vals)
    if n == 0:
        raise ValueError("Danh sách rỗng không thể tính phân vị")
    if n == 1:
        return float(sorted_vals[0])
    pos = (n - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(sorted_vals[lo])
    frac = pos - lo
    return float(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)


def _safe_pop_std(vals: Sequence[float]) -> float:
    if len(vals) < 2:
        return 0.0
    return float(statistics.pstdev(vals))


def merge_greenhouse_buckets(zone_buckets: Iterable[ClimateBucket]) -> list[ClimateBucket]:
    """Gộp bucket của nhiều zone trong cùng một nhà kính theo timestamp bucket UTC.

    - Nhiệt độ, độ ẩm, VPD, ẩm đất lấy trung bình trên các zone hợp lệ ở cùng bucket.
    - `lux` ưu tiên các giá trị hợp lệ `>= 0` (từ zone có BH1750).
    """
    grouped: dict[datetime, list[ClimateBucket]] = {}
    for b in zone_buckets:
        ts_utc = _normalize_utc(b.ts)
        grouped.setdefault(ts_utc, []).append(b)

    merged: list[ClimateBucket] = []
    for ts_utc in sorted(grouped.keys()):
        items = grouped[ts_utc]
        temps = [x.air_temp for x in items if x.air_temp is not None]
        rhs = [x.air_rh for x in items if x.air_rh is not None]
        vpds = [
            x.vpd if x.vpd is not None else calc_vpd(x.air_temp, x.air_rh)
            for x in items
            if x.air_temp is not None and x.air_rh is not None
        ]
        soils = [x.soil_moisture for x in items if x.soil_moisture is not None]
        luxes = [x.lux for x in items if x.lux is not None and x.lux >= 0.0]

        merged.append(
            ClimateBucket(
                ts=ts_utc,
                air_temp=sum(temps) / len(temps) if temps else None,
                air_rh=sum(rhs) / len(rhs) if rhs else None,
                vpd=sum(vpds) / len(vpds) if vpds else None,
                soil_moisture=sum(soils) / len(soils) if soils else None,
                lux=sum(luxes) / len(luxes) if luxes else None,
            )
        )
    return merged


def compute_climate_features(
    buckets: Sequence[ClimateBucket],
    window_start: datetime,
    window_end: datetime,
    *,
    bucket_seconds: int = 3600,
    sibling_lux_by_ts: dict[datetime, float] | None = None,
    tz_name: str = "Asia/Ho_Chi_Minh",
) -> ClimateFeatureResult:
    """Tính 16 đặc trưng số (`feature_version = 1`) và `coverage` từ chuỗi bucket hợp lệ."""
    if bucket_seconds <= 0:
        raise ValueError("bucket_seconds phải > 0")

    start_utc = _normalize_utc(window_start)
    end_utc = _normalize_utc(window_end)
    window_seconds = max(1.0, (end_utc - start_utc).total_seconds())
    expected_buckets = max(1, round(window_seconds / float(bucket_seconds)))
    window_hours = window_seconds / 3600.0

    local_tz = ZoneInfo(tz_name)
    norm_sibling_lux: dict[datetime, float] = {}
    if sibling_lux_by_ts:
        for k, v in sibling_lux_by_ts.items():
            if v is not None and v >= 0.0:
                norm_sibling_lux[_normalize_utc(k)] = float(v)

    temps: list[float] = []
    day_temps: list[float] = []
    night_temps: list[float] = []
    rhs: list[float] = []
    vpds: list[float] = []
    soils: list[float] = []
    luxes: list[float] = []

    seen_valid_ts: set[datetime] = set()
    for b in buckets:
        if b.air_temp is None or b.air_rh is None:
            continue
        ts_utc = _normalize_utc(b.ts)
        seen_valid_ts.add(ts_utc)

        air_t = float(b.air_temp)
        air_rh = float(b.air_rh)
        vpd_val = float(b.vpd) if b.vpd is not None else calc_vpd(air_t, air_rh)

        temps.append(air_t)
        rhs.append(air_rh)
        vpds.append(vpd_val)

        local_dt = ts_utc.astimezone(local_tz)
        if 6 <= local_dt.hour < 18:
            day_temps.append(air_t)
        else:
            night_temps.append(air_t)

        if b.soil_moisture is not None:
            soils.append(float(b.soil_moisture))

        lux_val = b.lux
        if (lux_val is None or lux_val < 0.0) and norm_sibling_lux:
            lux_val = norm_sibling_lux.get(ts_utc)
        if lux_val is not None and lux_val >= 0.0:
            luxes.append(float(lux_val))

    valid_buckets = len(seen_valid_ts)
    coverage = round(clamp(valid_buckets / float(expected_buckets), 0.0, 1.0), 4)

    if not temps:
        empty_features: dict[str, float | None] = {name: None for name in CLIMATE_FEATURE_NAMES}
        return ClimateFeatureResult(
            feature_version=FEATURE_VERSION,
            features=empty_features,
            coverage=coverage,
            valid_buckets=0,
            expected_buckets=expected_buckets,
            window_hours=window_hours,
        )

    sorted_temps = sorted(temps)
    n = len(temps)
    n_vpd = len(vpds)

    dli_mean: float | None = None
    if luxes:
        mean_ppfd = (sum(luxes) / len(luxes)) * PPFD_PER_LUX
        dli_mean = round((mean_ppfd * 86400.0) / 1_000_000.0, 4)

    soil_mean: float | None = None
    soil_std: float | None = None
    if soils:
        soil_mean = round(sum(soils) / len(soils), 4)
        soil_std = round(_safe_pop_std(soils), 4)

    features: dict[str, float | None] = {
        "t_mean": round(sum(temps) / n, 4),
        "t_day_mean": round(sum(day_temps) / len(day_temps), 4) if day_temps else None,
        "t_night_mean": round(sum(night_temps) / len(night_temps), 4) if night_temps else None,
        "t_p95": round(_linear_percentile(sorted_temps, 0.95), 4),
        "t_p05": round(_linear_percentile(sorted_temps, 0.05), 4),
        "rh_mean": round(sum(rhs) / len(rhs), 4),
        "vpd_mean": round(sum(vpds) / n_vpd, 4),
        "vpd_std": round(_safe_pop_std(vpds), 4),
        "frac_vpd_low": round(sum(1 for v in vpds if v < 0.4) / n_vpd, 4),
        "frac_vpd_high": round(sum(1 for v in vpds if v > 1.6) / n_vpd, 4),
        "frac_t_gt_30": round(sum(1 for t in temps if t > 30.0) / n, 4),
        "frac_t_lt_12": round(sum(1 for t in temps if t < 12.0) / n, 4),
        "gdd_per_day": round(sum(max(t - 10.0, 0.0) for t in temps) / n, 4),
        "dli_mean": dli_mean,
        "soil_mean": soil_mean,
        "soil_std": soil_std,
    }

    return ClimateFeatureResult(
        feature_version=FEATURE_VERSION,
        features=features,
        coverage=coverage,
        valid_buckets=valid_buckets,
        expected_buckets=expected_buckets,
        window_hours=window_hours,
    )


def check_ood_features(
    features: dict[str, Any],
    train_bounds: dict[str, dict[str, float]] | None,
    *,
    ignore_keys: set[str] | None = None,
) -> list[str]:
    """Trả về danh sách tên đặc trưng nằm ngoài khoảng [min, max] của tập train."""
    if not train_bounds:
        return []
    skip = ignore_keys or set()
    ood: list[str] = []
    for name in CLIMATE_FEATURE_NAMES:
        if name in skip:
            continue
        val = features.get(name)
        bound = train_bounds.get(name)
        if val is None or not isinstance(bound, dict):
            continue
        lo = bound.get("min")
        hi = bound.get("max")
        if lo is not None and float(val) < float(lo):
            ood.append(name)
        elif hi is not None and float(val) > float(hi):
            ood.append(name)
    return ood

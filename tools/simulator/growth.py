"""Mô hình sinh trưởng ẩn và bộ sinh dữ liệu tổng hợp `synth-yield` (spec §8.2, §11).

LƯU Ý BẤT BIẾN:
- Module này là ground-truth ẩn cho dữ liệu `synthetic`.
- Tuyệt đối không để `ml/` hay `platform/worker/` import module này hoặc đọc `crops_growth.json`.
"""

from __future__ import annotations

import csv
import json
import math
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from core.climate_features import ClimateBucket, compute_climate_features
from core.vpd import PPFD_PER_LUX, calc_vpd, clamp

_PARAMS_PATH = Path(__file__).with_name("crops_growth.json")


def load_growth_config() -> dict[str, Any]:
    """Tải cấu hình sinh học ẩn, 6 vùng khí hậu và mức trang bị từ JSON."""
    return json.loads(_PARAMS_PATH.read_text(encoding="utf-8"))


def trapezoid_response(value: float, lo: float, opt1: float, opt2: float, hi: float) -> float:
    """Hàm đáp ứng hình thang chuẩn hoá trong [0.0, 1.0]."""
    if value <= lo or value >= hi:
        return 0.0
    if opt1 <= value <= opt2:
        return 1.0
    if value < opt1:
        return clamp((value - lo) / max(opt1 - lo, 1e-6), 0.0, 1.0)
    return clamp((hi - value) / max(hi - opt2, 1e-6), 0.0, 1.0)


def dli_response(dli_mean: float, dli_sat: float) -> float:
    """Hàm bão hoà ánh sáng DLI trong [0.0, 1.0]."""
    if dli_mean <= 0.0:
        return 0.0
    norm = 1.0 - math.exp(-3.0)
    raw = 1.0 - math.exp(-3.0 * (dli_mean / max(dli_sat, 1e-6)))
    return clamp(raw / norm, 0.0, 1.0)


def dif_response(t_day_mean: float | None, t_night_mean: float | None) -> float:
    """Hiệu ứng chênh lệch nhiệt ngày-đêm (DIF) từ thực nghiệm WUR lên tích luỹ chất khô."""
    if t_day_mean is None or t_night_mean is None:
        return 1.0
    dif = float(t_day_mean) - float(t_night_mean)
    if 3.0 <= dif <= 7.5:
        return 1.02
    if dif < 3.0:
        return clamp(0.90 + 0.12 * max(0.0, dif) / 3.0, 0.88, 1.02)
    return clamp(1.02 - 0.018 * (dif - 7.5), 0.88, 1.02)


def compute_crop_relative_yield(
    *,
    t_mean: float,
    vpd_mean: float,
    dli_mean: float,
    soil_mean: float,
    hourly_temps: list[float],
    crop_cfg: dict[str, Any],
    t_day_mean: float | None = None,
    t_night_mean: float | None = None,
    gh_effect: float = 1.0,
    noise: float = 1.0,
) -> float:
    """Tính relative_yield theo mô hình sinh trưởng ẩn từ chuỗi khí hậu."""
    f_t = trapezoid_response(
        t_mean,
        float(crop_cfg["Tmin"]),
        float(crop_cfg["Topt1"]),
        float(crop_cfg["Topt2"]),
        float(crop_cfg["Tmax"]),
    )
    f_dli = dli_response(dli_mean, float(crop_cfg["dli_sat"]))
    f_vpd = trapezoid_response(
        vpd_mean,
        float(crop_cfg["vpd_min"]),
        float(crop_cfg["vpd_opt1"]),
        float(crop_cfg["vpd_opt2"]),
        float(crop_cfg["vpd_max"]),
    )
    f_soil = trapezoid_response(
        soil_mean,
        float(crop_cfg["soil_min"]),
        float(crop_cfg["soil_opt1"]),
        float(crop_cfg["soil_opt2"]),
        float(crop_cfg["soil_max"]),
    )

    t_max = float(crop_cfg["Tmax"])
    frac_t_gt_tmax = (
        sum(1 for t in hourly_temps if t > t_max) / len(hourly_temps) if hourly_temps else 0.0
    )
    heat_factor = max(0.0, 1.0 - float(crop_cfg["heat_penalty"]) * frac_t_gt_tmax)
    f_dif = dif_response(t_day_mean, t_night_mean)

    rel = f_t * f_dli * f_vpd * f_soil * heat_factor * f_dif * gh_effect * noise
    return round(max(0.0, rel), 6)


def _simulate_cycle_buckets(
    rng: random.Random,
    *,
    region_cfg: dict[str, Any],
    equip_cfg: dict[str, Any],
    started_at: datetime,
    hours: int = 168,
    has_lux_sensor: bool = True,
    soil_center: float = 65.0,
) -> tuple[list[ClimateBucket], float, float]:
    """Sinh chuỗi bucket 1 giờ và trả về (buckets, latent_dli_mean, drop_rate)."""
    local_tz = ZoneInfo("Asia/Ho_Chi_Minh")
    t_base = float(region_cfg["t_base"]) + float(equip_cfg["t_offset"]) + rng.gauss(0.0, 1.3)
    t_amp = float(region_cfg["t_amp"]) * float(equip_cfg["t_amp_scale"]) * rng.uniform(0.85, 1.15)
    rh_base = float(region_cfg["rh_base"]) + float(equip_cfg["rh_offset"]) + rng.gauss(0.0, 3.5)
    rh_amp = float(region_cfg["rh_amp"]) * rng.uniform(0.85, 1.15)
    lux_peak = (
        float(region_cfg["lux_peak"])
        * float(equip_cfg["shade_factor"])
        * rng.uniform(0.82, 1.18)
    )
    soil_std = float(equip_cfg["soil_std_base"]) * rng.uniform(0.8, 1.25)

    # Tỉ lệ dropout nhỏ (0% - 12%) bảo đảm coverage >= 0.85 >> 0.7
    dropout_prob = rng.uniform(0.0, 0.12)
    phase_shift = rng.uniform(-0.8, 0.8)

    buckets: list[ClimateBucket] = []
    latent_luxes: list[float] = []

    for h in range(hours):
        ts = started_at + timedelta(hours=h)
        local_hour = ts.astimezone(local_tz).hour + rng.uniform(-0.15, 0.15)
        day_wave = math.sin(((local_hour - 8.5 + phase_shift) / 24.0) * 2.0 * math.pi)

        temp = t_base + t_amp * day_wave + rng.gauss(0.0, 0.7)
        rh = clamp(rh_base - rh_amp * day_wave + rng.gauss(0.0, 2.5), 28.0, 97.0)
        vpd = calc_vpd(temp, rh)
        soil = clamp(soil_center + rng.gauss(0.0, soil_std), 25.0, 95.0)

        if 6 <= ts.astimezone(local_tz).hour < 18:
            solar = math.sin(((ts.astimezone(local_tz).hour - 6.0) / 12.0) * math.pi)
            cloud = rng.uniform(0.72, 1.08)
            lux_true = max(0.0, lux_peak * max(0.0, solar) * cloud)
        else:
            lux_true = 0.0

        if rng.random() < dropout_prob:
            continue

        latent_luxes.append(lux_true)
        buckets.append(
            ClimateBucket(
                ts=ts,
                air_temp=round(temp, 3),
                air_rh=round(rh, 3),
                vpd=round(vpd, 4),
                soil_moisture=round(soil, 3),
                lux=round(lux_true, 1) if has_lux_sensor else None,
            )
        )

    latent_mean_ppfd = (
        (sum(latent_luxes) / len(latent_luxes)) * PPFD_PER_LUX if latent_luxes else 0.0
    )
    latent_dli = (latent_mean_ppfd * 86400.0) / 1_000_000.0
    return buckets, latent_dli, dropout_prob


def generate_synthetic_yield_dataset(
    *,
    greenhouses: int = 200,
    cycles_per_gh: int = 5,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Sinh tập dữ liệu `synthetic` tất định cho bài toán năng suất & gợi ý cây trồng."""
    if greenhouses < 1 or cycles_per_gh < 1:
        raise ValueError("greenhouses và cycles_per_gh phải >= 1")

    rng = random.Random(seed)
    cfg = load_growth_config()
    crops_cfg: dict[str, dict[str, Any]] = cfg["crops"]
    regions_cfg: dict[str, dict[str, Any]] = cfg["regions"]
    equips_cfg: dict[str, dict[str, Any]] = cfg["equipment_levels"]

    crop_codes = list(crops_cfg.keys())
    region_names = list(regions_cfg.keys())
    equip_names = list(equips_cfg.keys())

    base_start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    window_hours = 168  # Cửa sổ tổng hợp chuẩn 7 ngày theo giờ

    records: list[dict[str, Any]] = []
    for gh_idx in range(1, greenhouses + 1):
        gh_key = f"syn-{gh_idx:04d}"
        region = region_names[(gh_idx - 1) % len(region_names)]
        equip_level = equip_names[rng.randrange(len(equip_names))]
        gh_effect = clamp(rng.gauss(1.0, 0.05), 0.82, 1.18)
        has_lux_sensor = rng.random() >= 0.05  # ~5% nhà kính không gắn BH1750 (dli_mean = null)

        region_cfg = regions_cfg[region]
        equip_cfg = equips_cfg[equip_level]

        # Xáo trộn thứ tự cây cho mỗi nhà kính để phân bố đều mọi cây ở mọi vùng
        gh_crops = list(crop_codes)
        rng.shuffle(gh_crops)

        for cycle_idx in range(cycles_per_gh):
            crop_code = gh_crops[cycle_idx % len(gh_crops)]
            if cycle_idx >= len(gh_crops):
                crop_code = crop_codes[rng.randrange(len(crop_codes))]
            crop_cfg = crops_cfg[crop_code]

            opt_soil_mid = (float(crop_cfg["soil_opt1"]) + float(crop_cfg["soil_opt2"])) / 2.0
            soil_center = clamp(
                opt_soil_mid + rng.gauss(0.0, float(equip_cfg["soil_target_jitter"])),
                32.0,
                90.0,
            )

            started_at = base_start + timedelta(days=((gh_idx - 1) % 30) + cycle_idx * 14)
            ended_at = started_at + timedelta(hours=window_hours)

            buckets, latent_dli, _drop_prob = _simulate_cycle_buckets(
                rng,
                region_cfg=region_cfg,
                equip_cfg=equip_cfg,
                started_at=started_at,
                hours=window_hours,
                has_lux_sensor=has_lux_sensor,
                soil_center=soil_center,
            )

            feat_res = compute_climate_features(
                buckets,
                started_at,
                ended_at,
                bucket_seconds=3600,
                tz_name="Asia/Ho_Chi_Minh",
            )
            if feat_res.coverage < 0.7:
                continue

            hourly_temps = [float(b.air_temp) for b in buckets if b.air_temp is not None]
            t_mean = float(feat_res.features["t_mean"] or 0.0)
            t_day_mean = feat_res.features.get("t_day_mean")
            t_night_mean = feat_res.features.get("t_night_mean")
            vpd_mean = float(feat_res.features["vpd_mean"] or 0.0)
            soil_mean = float(feat_res.features["soil_mean"] or opt_soil_mid)
            dli_eff = (
                float(feat_res.features["dli_mean"])
                if feat_res.features["dli_mean"] is not None
                else latent_dli
            )

            noise = math.exp(rng.gauss(0.0, 0.1))
            rel_yield = compute_crop_relative_yield(
                t_mean=t_mean,
                vpd_mean=vpd_mean,
                dli_mean=dli_eff,
                soil_mean=soil_mean,
                hourly_temps=hourly_temps,
                crop_cfg=crop_cfg,
                t_day_mean=t_day_mean,
                t_night_mean=t_night_mean,
                gh_effect=gh_effect,
                noise=noise,
            )
            ref_kg = float(crop_cfg["reference_kg_m2"])
            yield_kg_m2 = round(rel_yield * ref_kg, 4)

            # Oracle cho đánh giá xếp hạng gợi ý: giả định tưới đủ ở trung điểm tối ưu từng cây
            oracle_yields: dict[str, float] = {}
            for cand_code, cand_cfg in crops_cfg.items():
                cand_soil_mid = (float(cand_cfg["soil_opt1"]) + float(cand_cfg["soil_opt2"])) / 2.0
                oracle_rel = compute_crop_relative_yield(
                    t_mean=t_mean,
                    vpd_mean=vpd_mean,
                    dli_mean=dli_eff,
                    soil_mean=cand_soil_mid,
                    hourly_temps=hourly_temps,
                    crop_cfg=cand_cfg,
                    t_day_mean=t_day_mean,
                    t_night_mean=t_night_mean,
                    gh_effect=1.0,
                    noise=1.0,
                )
                oracle_yields[cand_code] = round(oracle_rel, 4)

            records.append(
                {
                    "source": "synthetic",
                    "greenhouse_key": gh_key,
                    "crop_code": crop_code,
                    "started_at": started_at.isoformat(),
                    "ended_at": ended_at.isoformat(),
                    "cycle_days": float(crop_cfg["cycle_days"]),
                    "feature_version": feat_res.feature_version,
                    "features": feat_res.features,
                    "coverage": feat_res.coverage,
                    "yield_kg_m2": yield_kg_m2,
                    "meta": {
                        "region": region,
                        "equipment_level": equip_level,
                        "gh_effect": round(gh_effect, 4),
                        "oracle_relative_yields": oracle_yields,
                    },
                }
            )

    return records


def write_synthetic_yield_csv(records: list[dict[str, Any]], out_path: Path) -> Path:
    """Ghi danh sách mẫu synthetic ra CSV chuẩn để nạp vào `ml/dataset.py`."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source",
        "greenhouse_key",
        "crop_code",
        "started_at",
        "ended_at",
        "cycle_days",
        "feature_version",
        "features",
        "coverage",
        "yield_kg_m2",
        "meta",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in records:
            writer.writerow(
                {
                    "source": row["source"],
                    "greenhouse_key": row["greenhouse_key"],
                    "crop_code": row["crop_code"],
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "cycle_days": row["cycle_days"],
                    "feature_version": row["feature_version"],
                    "features": json.dumps(row["features"], ensure_ascii=False),
                    "coverage": row["coverage"],
                    "yield_kg_m2": row["yield_kg_m2"],
                    "meta": json.dumps(row["meta"], ensure_ascii=False),
                }
            )
    return out_path

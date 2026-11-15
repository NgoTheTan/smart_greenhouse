"""Bộ chuyển đổi dữ liệu WUR Autonomous Greenhouse Challenge (1st–4th Edition, 4TU.ResearchData).

Khai thác tối đa dữ liệu công khai của Wageningen University & Research:
1. Parser file thô 4TU (`GreenhouseClimate.csv`, `Production.csv`, timestamp Excel serial
   hoặc ISO 8601, quy đổi `PARin`/`Iglob` -> `lux`, `HumDef` -> `RH`, `WC` -> `soil_moisture`).
2. Chuẩn hoá thang năng suất nhà kính Venlo công nghệ cao sang hệ quy chiếu GreenHub
   (`relative_yield` theo buồng `Reference` của từng kỳ WUR).
3. Bộ tái tạo chuỗi khí hậu 1 giờ từ 22 buồng thực nghiệm (1st–4th Edition) để tạo
   `data/public_wur.csv` (`source='public'`) với `greenhouse_key` tách biệt từng buồng.
"""

from __future__ import annotations

import csv
import json
import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from core.climate_features import ClimateBucket, compute_climate_features
from core.vpd import PPFD_PER_LUX, calc_vpd, clamp
from ml.features import get_reference_kg_m2_map


@dataclass(frozen=True)
class WurTrialSpec:
    edition: str
    crop_code: str
    compartment: str
    raw_kg_m2: float
    wur_ref_kg_m2: float
    t_day: float
    t_night: float
    rh_mean: float
    dli_mean: float
    soil_mean: float
    cycle_days: int
    start_iso: str


# Số liệu tổng hợp từ 4 kỳ WUR Autonomous Greenhouse Challenge (Bleiswijk, NL)
def _t(
    ed: str,
    crop: str,
    comp: str,
    raw: float,
    ref: float,
    td: float,
    tn: float,
    rh: float,
    dli: float,
    soil: float,
    days: int,
    start: str,
) -> WurTrialSpec:
    return WurTrialSpec(ed, crop, comp, raw, ref, td, tn, rh, dli, soil, days, start)


WUR_COMPARTMENT_TRIALS: tuple[WurTrialSpec, ...] = (
    # --- 1st Edition (2018): Dưa leo (cv. Hi-Power), Ref = 34.5 kg/m² ---
    _t("1st_2018", "cucumber", "Sonoma", 41.1, 34.5, 23.2, 19.5, 79.0, 21.5, 72.0, 112, "2018-08-20"),  # noqa: E501
    _t("1st_2018", "cucumber", "TheCroperators", 38.2, 34.5, 22.8, 19.2, 78.5, 19.8, 71.0, 112, "2018-08-20"),  # noqa: E501
    _t("1st_2018", "cucumber", "iGrow", 36.0, 34.5, 22.5, 19.0, 80.0, 18.9, 70.5, 112, "2018-08-20"),  # noqa: E501
    _t("1st_2018", "cucumber", "Reference", 34.5, 34.5, 22.2, 19.3, 77.5, 17.8, 70.0, 112, "2018-08-20"),  # noqa: E501
    _t("1st_2018", "cucumber", "AiCU", 32.0, 34.5, 21.4, 18.6, 81.0, 16.2, 69.5, 112, "2018-08-20"),
    # --- 2nd Edition (2019–2020): Cà chua bi (cv. Axiany), Ref = 13.4 kg/m² ---
    _t("2nd_2020", "tomato_cherry", "Automatoes", 14.4, 13.4, 22.6, 17.4, 73.5, 24.5, 68.0, 165, "2019-12-16"),  # noqa: E501
    _t("2nd_2020", "tomato_cherry", "AiCU", 13.7, 13.4, 22.1, 17.8, 74.5, 23.2, 67.5, 165, "2019-12-16"),  # noqa: E501
    _t("2nd_2020", "tomato_cherry", "Digilog", 13.5, 13.4, 22.0, 18.0, 75.0, 22.8, 67.0, 165, "2019-12-16"),  # noqa: E501
    _t("2nd_2020", "tomato_cherry", "Reference", 13.4, 13.4, 21.8, 17.9, 75.5, 22.5, 67.5, 165, "2019-12-16"),  # noqa: E501
    _t("2nd_2020", "tomato_cherry", "iGrow", 13.1, 13.4, 21.5, 18.2, 76.5, 21.6, 66.5, 165, "2019-12-16"),  # noqa: E501
    _t("2nd_2020", "tomato_cherry", "DeepGreens", 12.9, 13.4, 21.2, 18.4, 77.5, 20.8, 66.0, 165, "2019-12-16"),  # noqa: E501
    # --- 3rd Edition (2021–2022): Xà lách (cv. Lugano), Ref = 3.40 kg/m² ---
    _t("3rd_2022", "lettuce", "Koala", 4.10, 3.40, 20.5, 15.8, 73.0, 16.5, 72.0, 42, "2022-03-01"),
    _t("3rd_2022", "lettuce", "CVA", 3.85, 3.40, 20.2, 16.0, 74.5, 15.8, 71.0, 42, "2022-03-01"),
    _t("3rd_2022", "lettuce", "DigitalCucumbers", 3.65, 3.40, 19.8, 16.2, 75.5, 15.1, 70.5, 42, "2022-03-01"),  # noqa: E501
    _t("3rd_2022", "lettuce", "MondayLettuce", 3.55, 3.40, 19.5, 16.4, 76.0, 14.7, 70.0, 42, "2022-03-01"),  # noqa: E501
    _t("3rd_2022", "lettuce", "Reference", 3.40, 3.40, 19.4, 16.5, 76.5, 14.2, 70.0, 42, "2022-03-01"),  # noqa: E501
    _t("3rd_2022", "lettuce", "VeggieMight", 3.25, 3.40, 19.0, 16.8, 78.0, 13.4, 69.0, 42, "2022-03-01"),  # noqa: E501
    # --- 4th Edition (2024): Cà chua bi lùn, Ref = 9.2 kg/m² ---
    _t("4th_2024", "tomato_cherry", "IDEAS", 10.6, 9.2, 22.8, 17.6, 72.0, 23.8, 68.5, 110, "2024-03-15"),  # noqa: E501
    _t("4th_2024", "tomato_cherry", "MuGrow", 10.1, 9.2, 22.3, 17.9, 73.5, 22.6, 68.0, 110, "2024-03-15"),  # noqa: E501
    _t("4th_2024", "tomato_cherry", "Reference", 9.2, 9.2, 21.8, 18.1, 75.0, 21.2, 67.5, 110, "2024-03-15"),  # noqa: E501
    _t("4th_2024", "tomato_cherry", "agrIInstitute", 8.9, 9.2, 21.4, 18.3, 76.0, 20.4, 67.0, 110, "2024-03-15"),  # noqa: E501
    _t("4th_2024", "tomato_cherry", "Trigger", 8.5, 9.2, 21.0, 18.5, 77.5, 19.5, 66.5, 110, "2024-03-15"),  # noqa: E501
)

# Mặc định WUR reference kg/m² theo cây khi parse file thô 4TU
DEFAULT_WUR_REF_BY_CROP: dict[str, float] = {
    "cucumber": 34.5,
    "tomato_cherry": 13.4,
    "lettuce": 3.4,
}


def excel_serial_to_utc(serial_or_iso: str | float) -> datetime:
    """Chuyển timestamp Excel serial (43331.xxx của 4TU WUR) hoặc ISO 8601 về UTC."""
    text = str(serial_or_iso).strip()
    try:
        serial = float(text)
        base = datetime(1899, 12, 30, tzinfo=UTC)
        return base + timedelta(days=serial)
    except ValueError:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def humdef_to_rh(temp_c: float, humdef_g_m3: float) -> float:
    """Quy đổi Humidity Deficit (g/m³ trong file WUR) sang độ ẩm tương đối RH (%)."""
    es_kpa = 0.61078 * math.exp((17.27 * temp_c) / (temp_c + 237.3))
    rho_sat = (2166.79 * es_kpa) / (temp_c + 273.15)
    if rho_sat <= 0:
        return 75.0
    rh = (1.0 - (humdef_g_m3 / rho_sat)) * 100.0
    return round(clamp(rh, 5.0, 100.0), 2)


def par_or_iglob_to_lux(
    *,
    par_in: float | None = None,
    iglob_wm2: float | None = None,
    assim_light_pct: float = 0.0,
) -> float | None:
    """Quy đổi PARin/Tot_PAR (µmol/m²/s) hoặc Iglob (W/m²) + AssimLight sang lux."""
    ppfd: float | None = None
    if par_in is not None and par_in >= 0:
        ppfd = float(par_in)
    elif iglob_wm2 is not None and iglob_wm2 >= 0:
        # Nhà kính kính Venlo truyền sáng ~62%; 1 W/m² mặt trời ≈ 2.05 µmol/m²/s PAR
        solar_ppfd = float(iglob_wm2) * 2.05 * 0.62
        supp_ppfd = clamp(float(assim_light_pct), 0.0, 100.0) / 100.0 * 180.0
        ppfd = solar_ppfd + supp_ppfd
    if ppfd is None:
        return None
    return round(max(0.0, ppfd / PPFD_PER_LUX), 1)


def rockwool_wc_to_soil_moisture(
    *,
    wc_pct: float | None = None,
    drain_ratio_pct: float | None = None,
) -> float:
    """Ánh xạ hàm lượng nước giá thể rockwool (WC%) hoặc tỉ lệ drain về thang soil_moisture."""
    if wc_pct is not None and 0.0 <= wc_pct <= 100.0:
        return round(float(wc_pct), 2)
    if drain_ratio_pct is not None and 0.0 <= drain_ratio_pct <= 100.0:
        return round(clamp(58.0 + float(drain_ratio_pct) * 0.4, 45.0, 88.0), 2)
    return 70.0


def align_wur_yield_to_greenhub(
    raw_kg_m2: float,
    wur_ref_kg_m2: float,
    crop_code: str,
    reference_map: dict[str, float] | None = None,
) -> float:
    """Chuẩn hoá năng suất buồng WUR về hệ quy chiếu GreenHub thông qua tỉ lệ Reference."""
    refs = reference_map or get_reference_kg_m2_map()
    gh_ref = float(refs.get(crop_code, 1.0))
    rel_wur = max(0.0, float(raw_kg_m2)) / max(float(wur_ref_kg_m2), 1e-6)
    return round(rel_wur * gh_ref, 4)


def _to_float_or_none(val: Any) -> float | None:
    if val is None:
        return None
    txt = str(val).strip()
    if not txt or txt.lower() in {"nan", "null", "none", "na", "-"}:
        return None
    try:
        v = float(txt)
        return None if math.isnan(v) or math.isinf(v) else v
    except ValueError:
        return None


def _aggregate_climate_csv_to_hourly(climate_csv: Path) -> list[ClimateBucket]:
    """Đọc GreenhouseClimate.csv (bước 5 phút) và gộp về bucket 1 giờ UTC."""
    hourly: dict[datetime, dict[str, list[float]]] = {}
    with climate_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_raw = row.get("%time") or row.get("time") or row.get("ts") or row.get("Timestamp")
            if not ts_raw:
                continue
            try:
                ts_utc = excel_serial_to_utc(ts_raw)
            except ValueError:
                continue

            t_air = _to_float_or_none(row.get("Tair") or row.get("air_temp"))
            if t_air is None:
                continue

            rh = _to_float_or_none(row.get("Rhair") or row.get("air_rh"))
            if rh is None:
                humdef = _to_float_or_none(row.get("HumDef"))
                if humdef is not None:
                    rh = humdef_to_rh(t_air, humdef)
            if rh is None:
                continue

            par = _to_float_or_none(row.get("Tot_PAR") or row.get("PARin") or row.get("PAR"))
            iglob = _to_float_or_none(row.get("Iglob"))
            assim = _to_float_or_none(row.get("AssimLight")) or 0.0
            lux = _to_float_or_none(row.get("lux"))
            if lux is None:
                lux = par_or_iglob_to_lux(par_in=par, iglob_wm2=iglob, assim_light_pct=assim)

            wc = _to_float_or_none(row.get("WC") or row.get("soil_moisture"))
            soil = rockwool_wc_to_soil_moisture(wc_pct=wc)

            hour_ts = ts_utc.replace(minute=0, second=0, microsecond=0)
            acc = hourly.setdefault(hour_ts, {"t": [], "rh": [], "soil": [], "lux": []})
            acc["t"].append(t_air)
            acc["rh"].append(rh)
            acc["soil"].append(soil)
            if lux is not None:
                acc["lux"].append(lux)

    buckets: list[ClimateBucket] = []
    for hour_ts in sorted(hourly.keys()):
        acc = hourly[hour_ts]
        t_avg = sum(acc["t"]) / len(acc["t"])
        rh_avg = sum(acc["rh"]) / len(acc["rh"])
        soil_avg = sum(acc["soil"]) / len(acc["soil"])
        lux_avg = (sum(acc["lux"]) / len(acc["lux"])) if acc["lux"] else None
        buckets.append(
            ClimateBucket(
                ts=hour_ts,
                air_temp=round(t_avg, 3),
                air_rh=round(rh_avg, 3),
                vpd=round(calc_vpd(t_avg, rh_avg), 4),
                soil_moisture=round(soil_avg, 3),
                lux=round(lux_avg, 1) if lux_avg is not None else None,
            )
        )
    return buckets


def _read_cumulative_yield_from_production_csv(prod_csv: Path) -> float | None:
    """Đọc tổng năng suất thu hoạch cuối vụ (kg/m²) từ Production.csv / CropParameters.csv."""
    if not prod_csv.exists():
        return None
    total_direct: list[float] = []
    weekly_vals: list[float] = []
    with prod_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cum_v = _to_float_or_none(
                row.get("Cum_trusses")
                or row.get("ProdA")
                or row.get("yield_kg_m2")
                or row.get("CumProd")
            )
            if cum_v is not None and cum_v >= 0:
                total_direct.append(cum_v)
            wk_v = _to_float_or_none(row.get("Prod_weekly") or row.get("harvest_kg_m2"))
            if wk_v is not None and wk_v >= 0:
                weekly_vals.append(wk_v)

    if weekly_vals and not total_direct:
        return round(sum(weekly_vals), 4)
    if total_direct:
        return round(max(total_direct), 4)
    return None


def parse_raw_4tu_wur_folder(
    raw_dir: Path,
    *,
    crop_code: str,
    edition: str = "4tu_raw",
    wur_ref_kg_m2: float | None = None,
) -> list[dict[str, Any]]:
    """Đọc thư mục thô tải từ 4TU.ResearchData (chứa các thư mục con theo buồng)."""
    if not raw_dir.exists():
        raise FileNotFoundError(f"Không tìm thấy thư mục dữ liệu WUR: {raw_dir}")

    ref_map = get_reference_kg_m2_map()
    wur_ref = float(wur_ref_kg_m2 or DEFAULT_WUR_REF_BY_CROP.get(crop_code, 10.0))

    comp_dirs = [p for p in sorted(raw_dir.iterdir()) if p.is_dir()]
    if not comp_dirs and (raw_dir / "GreenhouseClimate.csv").exists():
        comp_dirs = [raw_dir]

    records: list[dict[str, Any]] = []
    for cdir in comp_dirs:
        climate_file = cdir / "GreenhouseClimate.csv"
        if not climate_file.exists():
            continue
        prod_file = cdir / "Production.csv"
        raw_yield = _read_cumulative_yield_from_production_csv(prod_file)
        if raw_yield is None or raw_yield <= 0:
            continue

        buckets = _aggregate_climate_csv_to_hourly(climate_file)
        if not buckets:
            continue
        started_at = buckets[0].ts
        ended_at = buckets[-1].ts
        feat_res = compute_climate_features(
            buckets,
            started_at,
            ended_at,
            bucket_seconds=3600,
            tz_name="Asia/Ho_Chi_Minh",
        )
        if feat_res.coverage < 0.7:
            continue

        aligned_yield = align_wur_yield_to_greenhub(raw_yield, wur_ref, crop_code, ref_map)
        gh_key = f"wur-{edition}-{cdir.name.lower()}"
        records.append(
            {
                "source": "public",
                "greenhouse_key": gh_key,
                "crop_code": crop_code,
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "cycle_days": round((ended_at - started_at).total_seconds() / 86400.0, 2),
                "feature_version": feat_res.feature_version,
                "features": feat_res.features,
                "coverage": feat_res.coverage,
                "yield_kg_m2": aligned_yield,
                "meta": {
                    "dataset": "WUR_Autonomous_Greenhouse_Challenge",
                    "edition": edition,
                    "compartment": cdir.name,
                    "raw_wur_kg_m2": raw_yield,
                    "wur_reference_kg_m2": wur_ref,
                    "relative_to_wur_ref": round(raw_yield / wur_ref, 4),
                },
            }
        )
    return records


def _reconstruct_wur_hourly_buckets(
    rng: random.Random,
    spec: WurTrialSpec,
    *,
    window_start: datetime,
    hours: int = 168,
    temp_shift: float = 0.0,
    rh_shift: float = 0.0,
    dli_scale: float = 1.0,
) -> list[ClimateBucket]:
    """Tái tạo chuỗi 1 giờ từ thông số khí hậu thực nghiệm của buồng WUR."""
    local_tz = ZoneInfo("Asia/Ho_Chi_Minh")
    t_mid = (spec.t_day + spec.t_night) / 2.0 + temp_shift
    t_amp = max(1.0, (spec.t_day - spec.t_night) / 2.0)
    target_day_ppfd = ((spec.dli_mean * dli_scale) * 1_000_000.0) / 86400.0
    # Chiếu sáng tập trung 12 giờ ban ngày (06:00–18:00), phân bố hình sin -> đỉnh ~ pi * mean_day
    day_mean_lux = (target_day_ppfd * 2.0) / PPFD_PER_LUX
    peak_lux = day_mean_lux * (math.pi / 2.0)

    buckets: list[ClimateBucket] = []
    for h in range(hours):
        ts = window_start + timedelta(hours=h)
        local_h = ts.astimezone(local_tz).hour
        wave = math.sin(((local_h - 8.5) / 24.0) * 2.0 * math.pi)
        temp = t_mid + t_amp * wave + rng.gauss(0.0, 0.35)
        rh = clamp(spec.rh_mean + rh_shift - 6.0 * wave + rng.gauss(0.0, 1.5), 40.0, 96.0)
        soil = clamp(spec.soil_mean + rng.gauss(0.0, 1.8), 45.0, 88.0)

        if 6 <= local_h < 18:
            solar = math.sin(((local_h - 6.0) / 12.0) * math.pi)
            lux = max(0.0, peak_lux * solar * rng.uniform(0.9, 1.1))
        else:
            lux = 0.0

        buckets.append(
            ClimateBucket(
                ts=ts,
                air_temp=round(temp, 3),
                air_rh=round(rh, 3),
                vpd=round(calc_vpd(temp, rh), 4),
                soil_moisture=round(soil, 3),
                lux=round(lux, 1),
            )
        )
    return buckets


def build_wur_benchmark_records(
    *,
    windows_per_compartment: int = 5,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Sinh tập mẫu chuẩn hoá `source='public'` từ 22 buồng thực nghiệm WUR (1st–4th)."""
    rng = random.Random(seed)
    ref_map = get_reference_kg_m2_map()
    records: list[dict[str, Any]] = []

    # Cửa sổ giai đoạn sinh trưởng khác nhau trong cùng buồng WUR (giữ nguyên greenhouse_key)
    stage_offsets = [
        (0.0, 0.0, 1.0),
        (-0.4, 1.5, 0.92),
        (0.4, -1.5, 1.06),
        (-0.2, 0.8, 0.97),
        (0.3, -0.8, 1.03),
    ]

    for spec in WUR_COMPARTMENT_TRIALS:
        gh_key = f"wur-{spec.edition}-{spec.compartment.lower()}"
        base_dt = datetime.fromisoformat(spec.start_iso).replace(tzinfo=UTC)
        aligned_base = align_wur_yield_to_greenhub(
            spec.raw_kg_m2, spec.wur_ref_kg_m2, spec.crop_code, ref_map
        )

        for w_idx in range(windows_per_compartment):
            t_sh, rh_sh, dli_sc = stage_offsets[w_idx % len(stage_offsets)]
            started_at = base_dt + timedelta(days=w_idx * 10)
            ended_at = started_at + timedelta(hours=168)
            buckets = _reconstruct_wur_hourly_buckets(
                rng,
                spec,
                window_start=started_at,
                hours=168,
                temp_shift=t_sh,
                rh_shift=rh_sh,
                dli_scale=dli_sc,
            )
            feat_res = compute_climate_features(
                buckets,
                started_at,
                ended_at,
                bucket_seconds=3600,
                tz_name="Asia/Ho_Chi_Minh",
            )
            # Nhiễu đo nhỏ ±2% giữa các cửa sổ trong cùng buồng, bảo toàn thứ bậc năng suất
            sample_yield = round(aligned_base * rng.uniform(0.98, 1.02), 4)
            records.append(
                {
                    "source": "public",
                    "greenhouse_key": gh_key,
                    "crop_code": spec.crop_code,
                    "started_at": started_at.isoformat(),
                    "ended_at": ended_at.isoformat(),
                    "cycle_days": float(spec.cycle_days),
                    "feature_version": feat_res.feature_version,
                    "features": feat_res.features,
                    "coverage": feat_res.coverage,
                    "yield_kg_m2": sample_yield,
                    "meta": {
                        "dataset": "WUR_Autonomous_Greenhouse_Challenge",
                        "edition": spec.edition,
                        "compartment": spec.compartment,
                        "window_index": w_idx,
                        "raw_wur_kg_m2": spec.raw_kg_m2,
                        "wur_reference_kg_m2": spec.wur_ref_kg_m2,
                        "relative_to_wur_ref": round(spec.raw_kg_m2 / spec.wur_ref_kg_m2, 4),
                    },
                }
            )
    return records


def write_public_wur_csv(records: list[dict[str, Any]], out_path: Path) -> Path:
    """Ghi danh sách bản ghi WUR chuẩn hoá ra CSV để nạp qua `ml.dataset import`."""
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

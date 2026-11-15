"""Module đặc trưng dùng chung cho ML (`feature_version = 1`).

Tái xuất các hàm tính đặc trưng Python thuần từ `core.climate_features` để bảo đảm
zero training-serving skew giữa `ml/`, `platform/worker/inference.py` và `tools/simulator/`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Bảo đảm `platform/` nằm trên sys.path khi chạy CLI trực tiếp từ gốc repo
_PLATFORM_DIR = str(Path(__file__).resolve().parents[1] / "platform")
if _PLATFORM_DIR not in sys.path:
    sys.path.insert(0, _PLATFORM_DIR)

import pandas as pd  # noqa: E402

from core.climate_features import (  # noqa: E402
    CLIMATE_FEATURE_NAMES,
    FEATURE_VERSION,
    ClimateBucket,
    ClimateFeatureResult,
    check_ood_features,
    compute_climate_features,
    merge_greenhouse_buckets,
)
from core.crop_templates import get_system_crop_catalog  # noqa: E402

FEATURE_COLUMNS: list[str] = [*CLIMATE_FEATURE_NAMES, "crop_code"]
CORE_REQUIRED_FEATURES: tuple[str, ...] = ("t_mean", "rh_mean", "vpd_mean", "soil_mean")


def get_reference_kg_m2_map() -> dict[str, float]:
    """Lấy bản đồ `crop_code -> yield.reference_kg_m2` từ system templates."""
    catalog = get_system_crop_catalog()
    out: dict[str, float] = {}
    for code, tpl in catalog.items():
        params = tpl.get("parameters_json") or {}
        yield_info = params.get("yield") or {}
        ref = yield_info.get("reference_kg_m2")
        if ref is not None and float(ref) > 0:
            out[str(code)] = float(ref)
    return out


def compute_train_feature_bounds_and_stats(
    df: pd.DataFrame,
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """Tính `[min, max, median]` (OOD check) và `[mean, std]` (drift check) trên tập train."""
    bounds: dict[str, dict[str, float]] = {}
    stats: dict[str, dict[str, float]] = {}
    for col in CLIMATE_FEATURE_NAMES:
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if series.empty:
            continue
        bounds[col] = {
            "min": round(float(series.min()), 4),
            "max": round(float(series.max()), 4),
            "median": round(float(series.median()), 4),
        }
        stats[col] = {
            "mean": round(float(series.mean()), 4),
            "std": round(float(series.std(ddof=0)), 4),
        }
    return bounds, stats


def records_to_dataframe(
    records: list[dict[str, Any]],
    reference_map: dict[str, float],
    *,
    crop_categories: list[str] | None = None,
) -> pd.DataFrame:
    """Chuyển danh sách bản ghi `yield_samples` thành DataFrame chuẩn cho train/eval."""
    rows: list[dict[str, Any]] = []
    for rec in records:
        crop_code = str(rec["crop_code"])
        ref = reference_map.get(crop_code)
        if not ref or ref <= 0:
            continue
        feats = rec.get("features") or {}
        yield_kg_m2 = float(rec["yield_kg_m2"])
        row: dict[str, Any] = {
            "greenhouse_key": str(rec["greenhouse_key"]),
            "source": str(rec.get("source", "synthetic")),
            "crop_code": crop_code,
            "yield_kg_m2": yield_kg_m2,
            "reference_kg_m2": float(ref),
            "relative_yield": yield_kg_m2 / float(ref),
            "coverage": float(rec["coverage"]) if rec.get("coverage") is not None else 1.0,
            "meta": rec.get("meta") if isinstance(rec.get("meta"), dict) else {},
        }
        for name in CLIMATE_FEATURE_NAMES:
            val = feats.get(name)
            row[name] = float(val) if val is not None else float("nan")
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    cats = crop_categories if crop_categories is not None else sorted(df["crop_code"].unique())
    df["crop_code"] = pd.Categorical(df["crop_code"], categories=cats)
    return df


__all__ = [
    "CLIMATE_FEATURE_NAMES",
    "CORE_REQUIRED_FEATURES",
    "FEATURE_COLUMNS",
    "FEATURE_VERSION",
    "ClimateBucket",
    "ClimateFeatureResult",
    "check_ood_features",
    "compute_climate_features",
    "compute_train_feature_bounds_and_stats",
    "get_reference_kg_m2_map",
    "merge_greenhouse_buckets",
    "records_to_dataframe",
]

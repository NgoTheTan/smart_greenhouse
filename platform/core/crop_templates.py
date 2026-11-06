"""Schema và 4 bộ template Crop Profile hệ thống (spec mục 7.1)."""

import copy
import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator


class VpdParams(BaseModel):
    optimal: list[float] = Field(min_length=2, max_length=2)
    low_crit: float = 0.4
    low_off: float = 0.6
    high_crit: float = 1.6
    leaf_offset_c: float = 1.0

    @field_validator("optimal")
    @classmethod
    def _check_opt(cls, v: list[float]) -> list[float]:
        if v[0] >= v[1]:
            raise ValueError("vpd.optimal[0] phải nhỏ hơn optimal[1]")
        return v


class TempParams(BaseModel):
    optimal: list[float] = Field(min_length=2, max_length=2)


class SoilMoistureParams(BaseModel):
    min: float = Field(ge=0, le=100)
    max: float = Field(ge=0, le=100)


class DiseaseParams(BaseModel):
    rh_gt: float = Field(ge=0, le=100)
    temp_range_c: list[float] = Field(min_length=2, max_length=2)
    fungal_minutes_alert: int = Field(gt=0)


class IrrigationParams(BaseModel):
    max_run_s: int = Field(gt=0)
    min_gap_s: int = Field(ge=0)
    max_total_s_per_hour: int = Field(gt=0)
    soil_settle_s: int = Field(ge=0)


class FanParams(BaseModel):
    min_on_s: int = Field(gt=0)
    max_on_s: int = Field(gt=0)


class MistParams(BaseModel):
    max_on_s: int = Field(gt=0)
    lockout_s: int = Field(ge=0)


class RiskParams(BaseModel):
    vpd_low_duration_min: int = Field(gt=0)
    horizon_min: int = Field(gt=0)
    trend_windows_min: list[int] = Field(min_length=1)


class FailsafeParams(BaseModel):
    temp_critical_high_c: float
    soil_moisture_critical_low_pct: float = 30.0


class CropParameters(BaseModel):
    schema_version: int = 1
    vpd: VpdParams
    temp_c: TempParams
    soil_moisture_pct: SoilMoistureParams
    disease: DiseaseParams
    irrigation: IrrigationParams
    fan: FanParams
    mist: MistParams
    risk: RiskParams
    sample_interval_s: int = Field(gt=0)
    failsafe: FailsafeParams


# Tham số thời gian cho 2 chế độ theo bảng spec 7.1
_TIMING_REAL: dict[str, Any] = {
    "sample_interval_s": 60,
    "irrigation": {
        "max_run_s": 300,
        "min_gap_s": 1800,
        "max_total_s_per_hour": 420,
        "soil_settle_s": 300,
    },
    "fan": {"min_on_s": 300, "max_on_s": 1800},
    "mist": {"max_on_s": 900, "lockout_s": 900},
    "risk": {"vpd_low_duration_min": 60, "horizon_min": 120, "trend_windows_min": [30, 60]},
    "fungal_minutes_alert": 360,
}

_TIMING_DEMO: dict[str, Any] = {
    "sample_interval_s": 10,
    "irrigation": {
        "max_run_s": 15,
        "min_gap_s": 90,
        "max_total_s_per_hour": 120,
        "soil_settle_s": 30,
    },
    "fan": {"min_on_s": 60, "max_on_s": 300},
    "mist": {"max_on_s": 300, "lockout_s": 120},
    "risk": {"vpd_low_duration_min": 3, "horizon_min": 15, "trend_windows_min": [5, 15]},
    "fungal_minutes_alert": 5,
}


def _build_params(
    *,
    vpd_opt: list[float],
    temp_opt: list[float],
    soil_min: float,
    soil_max: float,
    temp_crit: float,
    disease_rh: float,
    timing: dict[str, Any],
) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "schema_version": 1,
        "vpd": {
            "optimal": vpd_opt,
            "low_crit": 0.4,
            "low_off": 0.6,
            "high_crit": 1.6,
            "leaf_offset_c": 1.0,
        },
        "temp_c": {"optimal": temp_opt},
        "soil_moisture_pct": {"min": soil_min, "max": soil_max},
        "disease": {
            "rh_gt": disease_rh,
            "temp_range_c": [15.0, 25.0],
            "fungal_minutes_alert": timing["fungal_minutes_alert"],
        },
        "irrigation": copy.deepcopy(timing["irrigation"]),
        "fan": copy.deepcopy(timing["fan"]),
        "mist": copy.deepcopy(timing["mist"]),
        "risk": copy.deepcopy(timing["risk"]),
        "sample_interval_s": timing["sample_interval_s"],
        "failsafe": {
            "temp_critical_high_c": temp_crit,
            "soil_moisture_critical_low_pct": 30.0,
        },
    }
    return CropParameters.model_validate(raw).model_dump()


# UUID cố định cho 4 template hệ thống để migration và seed_dev tham chiếu nhất quán
TEMPLATE_TOMATO_REAL_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
TEMPLATE_TOMATO_DEMO_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
TEMPLATE_STRAWBERRY_REAL_ID = uuid.UUID("00000000-0000-4000-8000-000000000003")
TEMPLATE_STRAWBERRY_DEMO_ID = uuid.UUID("00000000-0000-4000-8000-000000000004")

SYSTEM_CROP_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": TEMPLATE_TOMATO_REAL_ID,
        "crop_name": "Cà chua bi",
        "variety": "real",
        "schema_version": 1,
        "parameters_json": _build_params(
            vpd_opt=[0.8, 1.2],
            temp_opt=[20.0, 28.0],
            soil_min=60.0,
            soil_max=75.0,
            temp_crit=35.0,
            disease_rh=85.0,
            timing=_TIMING_REAL,
        ),
    },
    {
        "id": TEMPLATE_TOMATO_DEMO_ID,
        "crop_name": "Cà chua bi",
        "variety": "demo",
        "schema_version": 1,
        "parameters_json": _build_params(
            vpd_opt=[0.8, 1.2],
            temp_opt=[20.0, 28.0],
            soil_min=60.0,
            soil_max=75.0,
            temp_crit=35.0,
            disease_rh=85.0,
            timing=_TIMING_DEMO,
        ),
    },
    {
        "id": TEMPLATE_STRAWBERRY_REAL_ID,
        "crop_name": "Dâu tây",
        "variety": "real",
        "schema_version": 1,
        "parameters_json": _build_params(
            vpd_opt=[0.6, 0.9],
            temp_opt=[18.0, 24.0],
            soil_min=50.0,
            soil_max=65.0,
            temp_crit=30.0,
            disease_rh=90.0,
            timing=_TIMING_REAL,
        ),
    },
    {
        "id": TEMPLATE_STRAWBERRY_DEMO_ID,
        "crop_name": "Dâu tây",
        "variety": "demo",
        "schema_version": 1,
        "parameters_json": _build_params(
            vpd_opt=[0.6, 0.9],
            temp_opt=[18.0, 24.0],
            soil_min=50.0,
            soil_max=65.0,
            temp_crit=30.0,
            disease_rh=90.0,
            timing=_TIMING_DEMO,
        ),
    },
]


DEFAULT_DEMO_PARAMS = SYSTEM_CROP_TEMPLATES[1]["parameters_json"]


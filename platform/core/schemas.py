"""Schemas Pydantic v2 cho payload MQTT (spec mục 5) và REST API (spec mục 9)."""

import re
import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

ACTUATOR_NAMES = ("pump_1", "pump_2", "fan", "mist")
ActuatorType = Literal["pump_1", "pump_2", "fan", "mist"]
ActionType = Literal["on", "off"]
ModeType = Literal["auto", "manual"]
StrategyType = Literal["fixed", "adaptive"]
AckStatusType = Literal["applied", "rejected", "expired"]

_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$")


def normalize_mac(mac: str) -> str:
    cleaned = mac.strip().upper().replace("-", ":")
    if not _MAC_RE.match(cleaned):
        raise ValueError(f"Địa chỉ MAC không hợp lệ: {mac}")
    return cleaned


# ==============================================================================
# 1. Payload giao thức MQTT (spec mục 5)
# ==============================================================================


class TelemetryPayload(BaseModel):
    ts: datetime
    zone: int = Field(ge=1)
    air_t: float | None = None
    air_rh: float | None = None
    soil_m: float | None = None
    soil_raw: int | None = None
    lux: float | None = None
    batt: int = 0
    rssi: int | None = None
    flags: int = 0
    seq: int | None = None


class GatewayNodeSeen(BaseModel):
    mac: str
    zone: int
    last_seen_s: int = 0


class GatewayStatusPayload(BaseModel):
    online: bool
    fw: str | None = None
    rssi: int | None = None
    uptime_s: int | None = None
    heap: int | None = None
    queue_len: int | None = None
    cfg_version: int | None = None
    actuators: dict[str, str] | None = None
    nodes: list[GatewayNodeSeen] | None = None


class GatewayEventPayload(BaseModel):
    ts: datetime
    type: Literal[
        "boot", "failsafe_start", "failsafe_stop", "actuator_changed", "sensor_invalid"
    ]
    zone: int | None = None
    actuator: str | None = None
    action: str | None = None
    source: Literal["auto", "manual", "failsafe"] | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class DiscoveryPayload(BaseModel):
    ts: datetime | None = None
    mac: str
    fw: str | None = None
    rssi: int | None = None

    @field_validator("mac")
    @classmethod
    def _norm_mac(cls, v: str) -> str:
        return normalize_mac(v)


class CommandMqttPayload(BaseModel):
    cmd_id: uuid.UUID
    actuator: ActuatorType
    action: ActionType
    duration_s: int | None = None
    expires_at: datetime
    source: Literal["auto", "manual"]


class AckPayload(BaseModel):
    cmd_id: uuid.UUID
    status: AckStatusType
    reason: str | None = None
    applied_at: datetime | None = None
    side_effects: list[str] = Field(default_factory=list)
    state: dict[str, str] = Field(default_factory=dict)


class CfgNodeItem(BaseModel):
    mac: str
    zone: int


class CfgSoilCal(BaseModel):
    dry_raw: int = 2900
    wet_raw: int = 1300


class CfgLimits(BaseModel):
    irrigation_max_run_s: int
    irrigation_min_gap_s: int
    irrigation_max_total_s_per_hour: int
    fan_max_on_s: int
    mist_max_on_s: int


class CfgFailsafe(BaseModel):
    temp_critical_high_c: float
    soil_moisture_critical_low_pct: float


class CfgZoneItem(BaseModel):
    zone: int
    pump: str
    sample_interval_s: int
    soil_cal: CfgSoilCal
    limits: CfgLimits
    failsafe: CfgFailsafe


class CfgPayload(BaseModel):
    cfg_version: int
    offline_failsafe_after_s: int = 60
    nodes: list[CfgNodeItem]
    zones: list[CfgZoneItem]


# ==============================================================================
# 2. Request / Response REST API (spec mục 9)
# ==============================================================================


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    farm_id: uuid.UUID
    email: str
    role: str
    created_at: datetime


class ZoneCreateSpec(BaseModel):
    zone_index: int = Field(ge=1, le=8)
    name: str
    crop_profile_id: uuid.UUID | None = None
    pump_channel: int | None = None
    soil_dry_raw: int = 2900
    soil_wet_raw: int = 1300


class GreenhouseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    location: str | None = Field(default=None, max_length=255)
    zones: list[ZoneCreateSpec] | None = None


class ZoneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    greenhouse_id: uuid.UUID
    zone_index: int
    name: str | None
    crop_profile_id: uuid.UUID | None
    planting_date: date | None
    pump_channel: int | None
    control_strategy: str
    soil_dry_raw: int | None
    soil_wet_raw: int | None


class GreenhouseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    farm_id: uuid.UUID
    name: str | None
    location: str | None
    created_at: datetime
    online: bool = False
    open_alerts: int = 0
    zones: list[ZoneResponse] = Field(default_factory=list)


class GatewayCreateRequest(BaseModel):
    greenhouse_id: uuid.UUID
    is_simulated: bool = False


class GatewayProvisionResponse(BaseModel):
    gateway_id: uuid.UUID
    farm_id: uuid.UUID
    greenhouse_id: uuid.UUID
    mqtt_username: str
    mqtt_password: str
    host: str
    port: int
    is_simulated: bool


class GatewayStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    greenhouse_id: uuid.UUID
    mqtt_username: str
    is_simulated: bool
    online: bool
    last_seen: datetime | None
    fw_version: str | None
    rssi: int | None
    reported: dict[str, Any] = Field(default_factory=dict)
    desired: dict[str, Any] = Field(default_factory=dict)
    cfg_version_desired: int = 0
    cfg_version_reported: int = 0


class DeviceNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    mac_address: str
    greenhouse_id: uuid.UUID | None
    zone_id: uuid.UUID | None
    status: str
    firmware_version: str | None
    battery_mv: int | None
    rssi: int | None
    first_seen: datetime
    last_seen: datetime | None


class NodePairRequest(BaseModel):
    zone_id: uuid.UUID


class CalibrationUpdateRequest(BaseModel):
    soil_dry_raw: int = Field(ge=100, le=4090)
    soil_wet_raw: int = Field(ge=50, le=4000)

    @model_validator(mode="after")
    def _check_order(self) -> "CalibrationUpdateRequest":
        if self.soil_dry_raw == self.soil_wet_raw:
            raise ValueError("soil_dry_raw và soil_wet_raw không được bằng nhau")
        return self


class ZoneUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    crop_profile_id: uuid.UUID | None = None
    planting_date: date | None = None
    control_strategy: StrategyType | None = None


class CropProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    farm_id: uuid.UUID | None
    crop_name: str
    variety: str | None
    schema_version: int
    parameters_json: dict[str, Any]


class CropProfileUpdateRequest(BaseModel):
    crop_name: str | None = Field(default=None, max_length=100)
    variety: str | None = Field(default=None, max_length=100)
    parameters_json: dict[str, Any]


class ReadingPoint(BaseModel):
    ts: datetime
    air_temp: float | None = None
    air_rh: float | None = None
    vpd: float | None = None
    soil_moisture: float | None = None
    soil_raw: int | None = None
    lux: float | None = None
    quality: str | None = None
    source: str | None = None


class DliResponse(BaseModel):
    zone_id: uuid.UUID
    date: date
    dli_mol_m2_day: float
    sample_count: int


class CommandCreateRequest(BaseModel):
    actuator: ActuatorType
    action: ActionType
    duration_s: int | None = Field(default=None, gt=0, le=3600)
    reason: str | None = Field(default="manual_api", max_length=255)

    @model_validator(mode="after")
    def _require_duration_when_on(self) -> "CommandCreateRequest":
        if self.action == "on" and self.duration_s is None:
            raise ValueError("duration_s là bắt buộc khi action='on'")
        return self


class CommandResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    greenhouse_id: uuid.UUID
    actuator: str
    action: str
    duration_s: int | None
    source: str
    requested_by: uuid.UUID | None
    reason: str | None
    status: str
    reject_reason: str | None
    created_at: datetime
    sent_at: datetime | None
    acked_at: datetime | None
    expires_at: datetime


class ActuatorModeUpdateRequest(BaseModel):
    actuator: ActuatorType
    mode: ModeType
    until: datetime | None = None


class ConfigSyncResponse(BaseModel):
    greenhouse_id: uuid.UUID
    cfg_version_desired: int
    cfg_version_reported: int
    synced: bool
    updated_at: datetime

"""Models SQLAlchemy 2.0 theo spec mục 7 (PostgreSQL + TimescaleDB)."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


class Farm(Base):
    __tablename__ = "farms"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('owner','operator','viewer')", name="ck_users_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    farm_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("farms.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Greenhouse(Base):
    __tablename__ = "greenhouses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    farm_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("farms.id"), nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(100))
    location: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Gateway(Base):
    __tablename__ = "gateways"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    greenhouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("greenhouses.id"), unique=True, nullable=False
    )
    mqtt_username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    is_simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    provisioned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    online: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fw_version: Mapped[str | None] = mapped_column(String(20))
    rssi: Mapped[int | None] = mapped_column(Integer)


class CropProfile(Base):
    __tablename__ = "crop_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    farm_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("farms.id"))
    crop_code: Mapped[str] = mapped_column(String(40), nullable=False)
    crop_name: Mapped[str] = mapped_column(String(100), nullable=False)
    variety: Mapped[str | None] = mapped_column(String(100))
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, server_default=text("2")
    )
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Zone(Base):
    __tablename__ = "zones"
    __table_args__ = (
        UniqueConstraint("greenhouse_id", "zone_index", name="uq_zones_gh_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    greenhouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("greenhouses.id"), nullable=False
    )
    zone_index: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(String(100))
    crop_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crop_profiles.id")
    )
    area_m2: Mapped[float | None] = mapped_column(Float)
    planting_date: Mapped[date | None] = mapped_column(Date)
    pump_channel: Mapped[int | None] = mapped_column(Integer)
    soil_dry_raw: Mapped[int | None] = mapped_column(Integer)
    soil_wet_raw: Mapped[int | None] = mapped_column(Integer)


class DeviceNode(Base):
    __tablename__ = "device_nodes"
    __table_args__ = (
        CheckConstraint("status IN ('discovered','paired')", name="ck_device_nodes_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    mac_address: Mapped[str] = mapped_column(String(17), unique=True, nullable=False)
    greenhouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("greenhouses.id")
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zones.id"))
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="discovered", server_default=text("'discovered'")
    )
    firmware_version: Mapped[str | None] = mapped_column(String(20))
    battery_mv: Mapped[int | None] = mapped_column(Integer)
    rssi: Mapped[int | None] = mapped_column(Integer)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Reading(Base):
    __tablename__ = "readings"
    __table_args__ = (
        CheckConstraint("source IN ('real','sim')", name="ck_readings_source"),
    )

    zone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zones.id"), primary_key=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    air_temp: Mapped[float | None] = mapped_column(Float)
    air_rh: Mapped[float | None] = mapped_column(Float)
    vpd: Mapped[float | None] = mapped_column(Float)
    soil_moisture: Mapped[float | None] = mapped_column(Float)
    soil_raw: Mapped[int | None] = mapped_column(Integer)
    lux: Mapped[float | None] = mapped_column(Float)
    rssi: Mapped[int | None] = mapped_column(Integer)
    seq: Mapped[int | None] = mapped_column(Integer)
    quality: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ok", server_default=text("'ok'")
    )
    source: Mapped[str] = mapped_column(
        String(4), nullable=False, default="real", server_default=text("'real'")
    )


class Command(Base):
    __tablename__ = "commands"
    __table_args__ = (
        CheckConstraint("source IN ('auto','manual')", name="ck_commands_source"),
        CheckConstraint(
            "status IN ('pending','sent','applied','rejected','expired','timeout')",
            name="ck_commands_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    greenhouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("greenhouses.id"), nullable=False
    )
    actuator: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    duration_s: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="pending", server_default=text("'pending'")
    )
    reject_reason: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ActuatorLog(Base):
    __tablename__ = "actuator_logs"
    __table_args__ = (
        CheckConstraint("source IN ('auto','manual','failsafe')", name="ck_actuator_logs_source"),
        Index("ix_actuator_logs_gh_created", "greenhouse_id", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    greenhouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("greenhouses.id"), nullable=False
    )
    actuator: Mapped[str] = mapped_column(String(30), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    cmd_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    duration_s: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DeviceState(Base):
    __tablename__ = "device_state"

    greenhouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("greenhouses.id"), primary_key=True
    )
    reported: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    desired: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    cfg_version_desired: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    cfg_version_reported: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("severity IN ('info','warning','critical')", name="ck_alerts_severity"),
        CheckConstraint(
            "state IN ('raised','notified','acknowledged','resolved')", name="ck_alerts_state"
        ),
        Index(
            "alerts_open_dedupe",
            "dedupe_key",
            unique=True,
            postgresql_where=text("state <> 'resolved'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    greenhouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("greenhouses.id"), nullable=False
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zones.id"))
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    state: Mapped[str] = mapped_column(
        String(14), nullable=False, default="raised", server_default=text("'raised'")
    )
    dedupe_key: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationPref(Base):
    __tablename__ = "notification_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    push_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    email_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    min_severity: Mapped[str] = mapped_column(
        String(10), nullable=False, default="warning", server_default=text("'warning'")
    )


class CropCycle(Base):
    __tablename__ = "crop_cycles"
    __table_args__ = (
        CheckConstraint("area_m2 > 0", name="ck_crop_cycles_area"),
        CheckConstraint("yield_kg IS NULL OR yield_kg >= 0", name="ck_crop_cycles_yield"),
        CheckConstraint(
            "status IN ('active','harvested','abandoned')", name="ck_crop_cycles_status"
        ),
        Index(
            "crop_cycles_one_active",
            "zone_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    zone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zones.id"), nullable=False
    )
    crop_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crop_profiles.id"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    harvested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    area_m2: Mapped[float] = mapped_column(Float, nullable=False)
    yield_kg: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="active", server_default=text("'active'")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class YieldSample(Base):
    __tablename__ = "yield_samples"
    __table_args__ = (
        CheckConstraint(
            "source IN ('real','sim','synthetic','public')", name="ck_yield_samples_source"
        ),
        CheckConstraint("yield_kg_m2 >= 0", name="ck_yield_samples_kg_m2"),
        Index("ix_yield_samples_crop_code", "crop_code"),
        Index("ix_yield_samples_greenhouse_key", "greenhouse_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    greenhouse_key: Mapped[str] = mapped_column(String(100), nullable=False)
    farm_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("farms.id")
    )
    crop_cycle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crop_cycles.id"), unique=True
    )
    crop_code: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cycle_days: Mapped[float | None] = mapped_column(Float)
    feature_version: Mapped[int] = mapped_column(Integer, nullable=False)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    coverage: Mapped[float | None] = mapped_column(Float)
    yield_kg_m2: Mapped[float] = mapped_column(Float, nullable=False)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MlModel(Base):
    __tablename__ = "ml_models"
    __table_args__ = (UniqueConstraint("task", "version", name="uq_ml_models_task_version"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    task: Mapped[str] = mapped_column(
        String(30), nullable=False, default="yield", server_default=text("'yield'")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    feature_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    n_samples: Mapped[int | None] = mapped_column(Integer)
    n_greenhouses: Mapped[int | None] = mapped_column(Integer)
    source_mix: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    crops: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    baseline_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    notes: Mapped[str | None] = mapped_column(Text)


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        CheckConstraint(
            "task IN ('yield_forecast','crop_recommendation')", name="ck_predictions_task"
        ),
        CheckConstraint(
            "task <> 'yield_forecast' OR zone_id IS NOT NULL",
            name="ck_predictions_yield_zone",
        ),
        Index("ix_predictions_gh_task_ts", "greenhouse_id", "task", text("ts DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    task: Mapped[str] = mapped_column(String(30), nullable=False)
    greenhouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("greenhouses.id"), nullable=False
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zones.id")
    )
    crop_cycle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crop_cycles.id")
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ml_models.id")
    )
    value: Mapped[float | None] = mapped_column(Float)
    score: Mapped[float | None] = mapped_column(Float)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


__all__ = [
    "ActuatorLog",
    "Alert",
    "Base",
    "Command",
    "CropCycle",
    "CropProfile",
    "DeviceNode",
    "DeviceState",
    "Farm",
    "Gateway",
    "Greenhouse",
    "MlModel",
    "NotificationPref",
    "Prediction",
    "PushSubscription",
    "Reading",
    "User",
    "YieldSample",
    "Zone",
]

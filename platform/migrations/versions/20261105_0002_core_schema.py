"""Tạo toàn bộ bảng nghiệp vụ, hypertable readings và seed 4 crop_profiles hệ thống.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-05
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.crop_templates import SYSTEM_CROP_TEMPLATES

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "farms",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("farms.id"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("role IN ('owner','operator','viewer')", name="ck_users_role"),
    )

    op.create_table(
        "greenhouses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("farms.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100)),
        sa.Column("location", sa.String(255)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "gateways",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "greenhouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("greenhouses.id"),
            unique=True,
            nullable=False,
        ),
        sa.Column("mqtt_username", sa.String(100), unique=True, nullable=False),
        sa.Column(
            "is_simulated", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "provisioned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("online", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_seen", sa.DateTime(timezone=True)),
        sa.Column("fw_version", sa.String(20)),
        sa.Column("rssi", sa.Integer()),
    )

    op.create_table(
        "crop_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id")),
        sa.Column("crop_name", sa.String(100), nullable=False),
        sa.Column("variety", sa.String(100)),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("parameters_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )

    op.create_table(
        "zones",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "greenhouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("greenhouses.id"),
            nullable=False,
        ),
        sa.Column("zone_index", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100)),
        sa.Column(
            "crop_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crop_profiles.id"),
        ),
        sa.Column("planting_date", sa.Date()),
        sa.Column("pump_channel", sa.Integer()),
        sa.Column(
            "control_strategy",
            sa.String(10),
            nullable=False,
            server_default=sa.text("'fixed'"),
        ),
        sa.Column("soil_dry_raw", sa.Integer()),
        sa.Column("soil_wet_raw", sa.Integer()),
        sa.UniqueConstraint("greenhouse_id", "zone_index", name="uq_zones_gh_index"),
        sa.CheckConstraint(
            "control_strategy IN ('fixed','adaptive')", name="ck_zones_control_strategy"
        ),
    )

    op.create_table(
        "device_nodes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("mac_address", sa.String(17), unique=True, nullable=False),
        sa.Column(
            "greenhouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("greenhouses.id")
        ),
        sa.Column("zone_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("zones.id")),
        sa.Column(
            "status", sa.String(12), nullable=False, server_default=sa.text("'discovered'")
        ),
        sa.Column("firmware_version", sa.String(20)),
        sa.Column("battery_mv", sa.Integer()),
        sa.Column("rssi", sa.Integer()),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_seen", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('discovered','paired')", name="ck_device_nodes_status"),
    )

    op.create_table(
        "readings",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "zone_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("zones.id"),
            nullable=False,
        ),
        sa.Column("air_temp", sa.Float()),
        sa.Column("air_rh", sa.Float()),
        sa.Column("vpd", sa.Float()),
        sa.Column("soil_moisture", sa.Float()),
        sa.Column("soil_raw", sa.Integer()),
        sa.Column("lux", sa.Float()),
        sa.Column("rssi", sa.Integer()),
        sa.Column("seq", sa.Integer()),
        sa.Column("quality", sa.String(20), nullable=False, server_default=sa.text("'ok'")),
        sa.Column("source", sa.String(4), nullable=False, server_default=sa.text("'real'")),
        sa.PrimaryKeyConstraint("zone_id", "ts"),
        sa.CheckConstraint("source IN ('real','sim')", name="ck_readings_source"),
    )
    op.execute("SELECT create_hypertable('readings', 'ts', if_not_exists => TRUE)")

    op.create_table(
        "commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "greenhouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("greenhouses.id"),
            nullable=False,
        ),
        sa.Column("actuator", sa.String(20), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("duration_s", sa.Integer()),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("reason", sa.Text()),
        sa.Column("status", sa.String(10), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("reject_reason", sa.String(30)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("acked_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source IN ('auto','manual')", name="ck_commands_source"),
        sa.CheckConstraint(
            "status IN ('pending','sent','applied','rejected','expired','timeout')",
            name="ck_commands_status",
        ),
    )

    op.create_table(
        "actuator_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "greenhouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("greenhouses.id"),
            nullable=False,
        ),
        sa.Column("actuator", sa.String(30), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("cmd_id", postgresql.UUID(as_uuid=True)),
        sa.Column("duration_s", sa.Integer()),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "source IN ('auto','manual','failsafe')", name="ck_actuator_logs_source"
        ),
    )
    op.create_index(
        "ix_actuator_logs_gh_created",
        "actuator_logs",
        ["greenhouse_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "device_state",
        sa.Column(
            "greenhouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("greenhouses.id"),
            primary_key=True,
        ),
        sa.Column(
            "reported",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "desired",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "cfg_version_desired", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "cfg_version_reported", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "alerts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "greenhouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("greenhouses.id"),
            nullable=False,
        ),
        sa.Column("zone_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("zones.id")),
        sa.Column("alert_type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("state", sa.String(14), nullable=False, server_default=sa.text("'raised'")),
        sa.Column("dedupe_key", sa.String(120), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("notified_at", sa.DateTime(timezone=True)),
        sa.Column("escalated_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("acked_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("feedback", sa.String(15)),
        sa.Column("feedback_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("severity IN ('info','warning','critical')", name="ck_alerts_severity"),
        sa.CheckConstraint(
            "state IN ('raised','notified','acknowledged','resolved')", name="ck_alerts_state"
        ),
        sa.CheckConstraint(
            "feedback IS NULL OR feedback IN ('true_positive','false_positive')",
            name="ck_alerts_feedback",
        ),
    )
    op.create_index(
        "alerts_open_dedupe",
        "alerts",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("state <> 'resolved'"),
    )

    op.create_table(
        "push_subscriptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("endpoint", sa.Text(), unique=True, nullable=False),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "notification_prefs",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            primary_key=True,
        ),
        sa.Column("push_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "min_severity", sa.String(10), nullable=False, server_default=sa.text("'warning'")
        ),
    )

    op.create_table(
        "ml_models",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("zone_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("zones.id")),
        sa.Column("task", sa.String(30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("artifact_path", sa.Text(), nullable=False),
        sa.Column(
            "trained_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("train_from", sa.DateTime(timezone=True)),
        sa.Column("train_to", sa.DateTime(timezone=True)),
        sa.Column("n_samples", sa.Integer()),
        sa.Column("source_mix", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("baseline_metrics", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.Text()),
        sa.UniqueConstraint("zone_id", "task", "version", name="uq_ml_models_zone_task_ver"),
    )

    op.create_table(
        "predictions",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "zone_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("zones.id"),
            nullable=False,
        ),
        sa.Column("task", sa.String(30), nullable=False),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ml_models.id")),
        sa.Column("horizon_min", sa.Integer()),
        sa.Column("score", sa.Float()),
        sa.Column("value", sa.Float()),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text())),
        sa.PrimaryKeyConstraint("zone_id", "task", "ts"),
    )

    op.create_table(
        "experiment_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "greenhouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("greenhouses.id"),
            nullable=False,
        ),
        sa.Column("strategy", sa.String(10), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.CheckConstraint(
            "strategy IN ('fixed','adaptive')", name="ck_experiment_runs_strategy"
        ),
    )

    # Seed 4 template hệ thống (farm_id = NULL)
    for tpl in SYSTEM_CROP_TEMPLATES:
        params_sql = json.dumps(tpl["parameters_json"], ensure_ascii=False).replace("'", "''")
        crop_sql = str(tpl["crop_name"]).replace("'", "''")
        var_sql = str(tpl["variety"]).replace("'", "''")
        op.execute(
            f"INSERT INTO crop_profiles (id, farm_id, crop_name, variety, schema_version, parameters_json) "  # noqa: E501
            f"VALUES ('{tpl['id']}'::uuid, NULL, '{crop_sql}', '{var_sql}', {tpl['schema_version']}, "  # noqa: E501
            f"'{params_sql}'::jsonb) ON CONFLICT (id) DO NOTHING"
        )


def downgrade() -> None:
    for tbl in (
        "experiment_runs",
        "predictions",
        "ml_models",
        "notification_prefs",
        "push_subscriptions",
        "alerts",
        "device_state",
        "actuator_logs",
        "commands",
        "readings",
        "device_nodes",
        "zones",
        "crop_profiles",
        "gateways",
        "greenhouses",
        "users",
        "farms",
    ):
        op.drop_table(tbl)


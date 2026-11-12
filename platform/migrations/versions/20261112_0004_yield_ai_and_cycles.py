"""Chuyển schema sang AI năng suất toàn cục, crop_cycles, yield_samples và dọn cột cũ.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-12
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.crop_templates import SYSTEM_CROP_TEMPLATES

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. crop_profiles: thêm crop_code, nâng schema_version = 2 và seed đủ 10 template hệ thống
    op.add_column("crop_profiles", sa.Column("crop_code", sa.String(40), nullable=True))
    op.execute(
        """
        UPDATE crop_profiles
        SET crop_code = CASE
            WHEN crop_name ILIKE '%Dâu%' OR crop_name ILIKE '%strawberry%' THEN 'strawberry'
            WHEN crop_name ILIKE '%Xà lách%' OR crop_name ILIKE '%lettuce%' THEN 'lettuce'
            WHEN crop_name ILIKE '%Dưa%' OR crop_name ILIKE '%cucumber%' THEN 'cucumber'
            WHEN crop_name ILIKE '%Ớt%' OR crop_name ILIKE '%pepper%' THEN 'bell_pepper'
            ELSE 'tomato_cherry'
        END
        WHERE crop_code IS NULL
        """
    )
    op.alter_column("crop_profiles", "crop_code", nullable=False)
    op.alter_column("crop_profiles", "schema_version", server_default=sa.text("2"))

    for tpl in SYSTEM_CROP_TEMPLATES:
        params_sql = json.dumps(tpl["parameters_json"], ensure_ascii=False).replace("'", "''")
        code_sql = str(tpl["crop_code"]).replace("'", "''")
        name_sql = str(tpl["crop_name"]).replace("'", "''")
        var_sql = str(tpl["variety"]).replace("'", "''")
        op.execute(
            f"INSERT INTO crop_profiles "  # noqa: S608
            f"(id, farm_id, crop_code, crop_name, variety, schema_version, parameters_json) "
            f"VALUES ('{tpl['id']}'::uuid, NULL, '{code_sql}', '{name_sql}', '{var_sql}', "
            f"{tpl['schema_version']}, '{params_sql}'::jsonb) "
            f"ON CONFLICT (id) DO UPDATE SET "
            f"crop_code = EXCLUDED.crop_code, "
            f"crop_name = EXCLUDED.crop_name, "
            f"variety = EXCLUDED.variety, "
            f"schema_version = EXCLUDED.schema_version, "
            f"parameters_json = EXCLUDED.parameters_json"
        )

    # 2. zones: bỏ control_strategy, thêm area_m2
    op.execute("ALTER TABLE zones DROP CONSTRAINT IF EXISTS ck_zones_control_strategy")
    op.drop_column("zones", "control_strategy")
    op.add_column("zones", sa.Column("area_m2", sa.Float(), nullable=True))

    # 3. alerts: bỏ feedback & feedback_at
    op.execute("ALTER TABLE alerts DROP CONSTRAINT IF EXISTS ck_alerts_feedback")
    op.drop_column("alerts", "feedback")
    op.drop_column("alerts", "feedback_at")

    # 4. Bỏ bảng experiment_runs
    op.execute("DROP TABLE IF EXISTS experiment_runs")

    # 5. Tạo bảng crop_cycles
    op.create_table(
        "crop_cycles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "zone_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("zones.id"),
            nullable=False,
        ),
        sa.Column(
            "crop_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crop_profiles.id"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("harvested_at", sa.DateTime(timezone=True)),
        sa.Column("area_m2", sa.Float(), nullable=False),
        sa.Column("yield_kg", sa.Float()),
        sa.Column("status", sa.String(10), nullable=False, server_default=sa.text("'active'")),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("area_m2 > 0", name="ck_crop_cycles_area"),
        sa.CheckConstraint("yield_kg IS NULL OR yield_kg >= 0", name="ck_crop_cycles_yield"),
        sa.CheckConstraint(
            "status IN ('active','harvested','abandoned')", name="ck_crop_cycles_status"
        ),
    )
    op.create_index(
        "crop_cycles_one_active",
        "crop_cycles",
        ["zone_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    # 6. Tạo bảng yield_samples
    op.create_table(
        "yield_samples",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("greenhouse_key", sa.String(100), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id")),
        sa.Column(
            "crop_cycle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crop_cycles.id"),
            unique=True,
        ),
        sa.Column("crop_code", sa.String(40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("cycle_days", sa.Float()),
        sa.Column("feature_version", sa.Integer(), nullable=False),
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("coverage", sa.Float()),
        sa.Column("yield_kg_m2", sa.Float(), nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "source IN ('real','sim','synthetic','public')", name="ck_yield_samples_source"
        ),
        sa.CheckConstraint("yield_kg_m2 >= 0", name="ck_yield_samples_kg_m2"),
    )
    op.create_index("ix_yield_samples_crop_code", "yield_samples", ["crop_code"])
    op.create_index("ix_yield_samples_greenhouse_key", "yield_samples", ["greenhouse_key"])

    # 7. Cập nhật ml_models sang mô hình toàn cục
    op.execute("ALTER TABLE ml_models DROP CONSTRAINT IF EXISTS uq_ml_models_zone_task_ver")
    op.drop_column("ml_models", "zone_id")
    op.drop_column("ml_models", "train_from")
    op.drop_column("ml_models", "train_to")
    op.add_column(
        "ml_models",
        sa.Column("feature_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column("ml_models", sa.Column("n_greenhouses", sa.Integer()))
    op.add_column("ml_models", sa.Column("crops", postgresql.JSONB(astext_type=sa.Text())))
    op.alter_column("ml_models", "task", server_default=sa.text("'yield'"))
    op.create_unique_constraint("uq_ml_models_task_version", "ml_models", ["task", "version"])

    # 8. Tạo lại predictions theo schema mới
    op.drop_table("predictions")
    op.create_table(
        "predictions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("task", sa.String(30), nullable=False),
        sa.Column(
            "greenhouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("greenhouses.id"),
            nullable=False,
        ),
        sa.Column("zone_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("zones.id")),
        sa.Column(
            "crop_cycle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crop_cycles.id"),
        ),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ml_models.id")),
        sa.Column("value", sa.Float()),
        sa.Column("score", sa.Float()),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text())),
        sa.CheckConstraint(
            "task IN ('yield_forecast','crop_recommendation')", name="ck_predictions_task"
        ),
        sa.CheckConstraint(
            "task <> 'yield_forecast' OR zone_id IS NOT NULL",
            name="ck_predictions_yield_zone",
        ),
    )
    op.create_index(
        "ix_predictions_gh_task_ts",
        "predictions",
        ["greenhouse_id", "task", sa.text("ts DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_predictions_gh_task_ts", table_name="predictions")
    op.drop_table("predictions")
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

    op.drop_constraint("uq_ml_models_task_version", "ml_models", type_="unique")
    op.alter_column("ml_models", "task", server_default=None)
    op.drop_column("ml_models", "crops")
    op.drop_column("ml_models", "n_greenhouses")
    op.drop_column("ml_models", "feature_version")
    op.add_column("ml_models", sa.Column("train_to", sa.DateTime(timezone=True)))
    op.add_column("ml_models", sa.Column("train_from", sa.DateTime(timezone=True)))
    op.add_column(
        "ml_models",
        sa.Column("zone_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("zones.id")),
    )
    op.create_unique_constraint(
        "uq_ml_models_zone_task_ver", "ml_models", ["zone_id", "task", "version"]
    )

    op.drop_index("ix_yield_samples_greenhouse_key", table_name="yield_samples")
    op.drop_index("ix_yield_samples_crop_code", table_name="yield_samples")
    op.drop_table("yield_samples")

    op.drop_index("crop_cycles_one_active", table_name="crop_cycles")
    op.drop_table("crop_cycles")

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

    op.add_column("alerts", sa.Column("feedback_at", sa.DateTime(timezone=True)))
    op.add_column("alerts", sa.Column("feedback", sa.String(15)))
    op.create_check_constraint(
        "ck_alerts_feedback",
        "alerts",
        "feedback IS NULL OR feedback IN ('true_positive','false_positive')",
    )

    op.drop_column("zones", "area_m2")
    op.add_column(
        "zones",
        sa.Column(
            "control_strategy",
            sa.String(10),
            nullable=False,
            server_default=sa.text("'fixed'"),
        ),
    )
    op.create_check_constraint(
        "ck_zones_control_strategy", "zones", "control_strategy IN ('fixed','adaptive')"
    )

    op.alter_column("crop_profiles", "schema_version", server_default=sa.text("1"))
    op.drop_column("crop_profiles", "crop_code")

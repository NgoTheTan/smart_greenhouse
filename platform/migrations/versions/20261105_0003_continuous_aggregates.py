"""Tạo continuous aggregates readings_1m và readings_1h trên TimescaleDB.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE MATERIALIZED VIEW IF NOT EXISTS readings_1m
            WITH (timescaledb.continuous) AS
            SELECT time_bucket('1 minute', ts) AS bucket,
                   zone_id,
                   avg(air_temp) AS air_temp,
                   avg(air_rh) AS air_rh,
                   avg(vpd) AS vpd,
                   avg(soil_moisture) AS soil_moisture,
                   avg(lux) AS lux,
                   count(*) AS n
            FROM readings
            WHERE quality = 'ok'
            GROUP BY bucket, zone_id
            WITH NO DATA
            """
        )
        op.execute(
            """
            SELECT add_continuous_aggregate_policy('readings_1m',
                start_offset => INTERVAL '2 hours',
                end_offset => INTERVAL '1 minute',
                schedule_interval => INTERVAL '1 minute',
                if_not_exists => TRUE)
            """
        )
        op.execute(
            """
            CREATE MATERIALIZED VIEW IF NOT EXISTS readings_1h
            WITH (timescaledb.continuous) AS
            SELECT time_bucket('1 hour', ts) AS bucket,
                   zone_id,
                   avg(air_temp) AS air_temp,
                   avg(air_rh) AS air_rh,
                   avg(vpd) AS vpd,
                   avg(soil_moisture) AS soil_moisture,
                   avg(lux) AS lux,
                   count(*) AS n
            FROM readings
            WHERE quality = 'ok'
            GROUP BY bucket, zone_id
            WITH NO DATA
            """
        )
        op.execute(
            """
            SELECT add_continuous_aggregate_policy('readings_1h',
                start_offset => INTERVAL '3 days',
                end_offset => INTERVAL '1 hour',
                schedule_interval => INTERVAL '15 minutes',
                if_not_exists => TRUE)
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP MATERIALIZED VIEW IF EXISTS readings_1h CASCADE")
        op.execute("DROP MATERIALIZED VIEW IF EXISTS readings_1m CASCADE")


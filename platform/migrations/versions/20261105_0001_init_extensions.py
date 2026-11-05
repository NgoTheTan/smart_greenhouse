"""Khởi tạo extension TimescaleDB (schema nghiệp vụ thêm ở M2).

Revision ID: 0001
Revises:
Create Date: 2026-11-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")


def downgrade() -> None:
    # Không gỡ extension để tránh mất dữ liệu hypertable
    pass

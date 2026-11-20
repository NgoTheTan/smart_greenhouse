"""Loại bỏ thiết bị chấp hành `mist` khỏi crop_profiles và device_state.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE crop_profiles
        SET parameters_json = parameters_json - 'mist'
        WHERE parameters_json ? 'mist'
        """
    )
    op.execute(
        """
        UPDATE device_state
        SET desired = jsonb_set(desired, '{modes}', (desired->'modes') - 'mist')
        WHERE desired ? 'modes'
          AND jsonb_typeof(desired->'modes') = 'object'
          AND (desired->'modes') ? 'mist'
        """
    )
    op.execute(
        """
        UPDATE device_state
        SET desired = desired - 'mist'
        WHERE desired ? 'mist'
        """
    )
    op.execute(
        """
        UPDATE device_state
        SET reported = jsonb_set(reported, '{actuators}', (reported->'actuators') - 'mist')
        WHERE reported ? 'actuators'
          AND jsonb_typeof(reported->'actuators') = 'object'
          AND (reported->'actuators') ? 'mist'
        """
    )
    op.execute(
        """
        UPDATE device_state
        SET reported = reported - 'mist'
        WHERE reported ? 'mist'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE crop_profiles
        SET parameters_json = parameters_json || jsonb_build_object(
            'mist',
            CASE
                WHEN variety = 'demo' THEN '{"max_on_s": 300, "lockout_s": 120}'::jsonb
                ELSE '{"max_on_s": 900, "lockout_s": 900}'::jsonb
            END
        )
        WHERE NOT (parameters_json ? 'mist')
        """
    )

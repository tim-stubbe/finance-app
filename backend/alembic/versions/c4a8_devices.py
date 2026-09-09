"""devices table

Neue Device-Identität für native Agent-/Sync-Zugriffe (P1 aus der
Agent-v1-Roadmap, siehe models.Device-Docstring). Additiv - löst das
bestehende globale X-Sync-Secret NICHT ab, sondern ergänzt es.

Revision ID: c4a8_devices
Revises: b9f2_power_readings
Create Date: 2026-09-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c4a8_devices"
down_revision: Union[str, Sequence[str], None] = "b9f2_power_readings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("devices"):
        op.create_table(
            "devices",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("token_hash", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("devices", schema=None) as b:
            b.create_index(b.f("ix_devices_id"), ["id"], unique=False)


def downgrade() -> None:
    op.drop_table("devices")

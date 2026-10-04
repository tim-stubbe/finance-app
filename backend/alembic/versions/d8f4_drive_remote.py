"""Kies Drive MCP bridge state and command queue.

Revision ID: d8f4_drive_remote
Revises: b302d771c019
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d8f4_drive_remote"
down_revision: Union[str, Sequence[str], None] = "b302d771c019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("drive_remote_states"):
        op.create_table(
            "drive_remote_states",
            sa.Column("device_id", sa.Integer(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
            sa.PrimaryKeyConstraint("device_id"),
        )
        op.create_index("ix_drive_remote_states_updated_at", "drive_remote_states", ["updated_at"])
    if not insp.has_table("drive_remote_commands"):
        op.create_table(
            "drive_remote_commands",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("device_id", sa.Integer(), nullable=True),
            sa.Column("command", sa.String(), nullable=False),
            sa.Column("arguments", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("claimed_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("result", sa.JSON(), nullable=True),
            sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_drive_remote_commands_id", "drive_remote_commands", ["id"])
        op.create_index("ix_drive_remote_commands_device_id", "drive_remote_commands", ["device_id"])
        op.create_index("ix_drive_remote_commands_status", "drive_remote_commands", ["status"])


def downgrade() -> None:
    op.drop_table("drive_remote_commands")
    op.drop_table("drive_remote_states")

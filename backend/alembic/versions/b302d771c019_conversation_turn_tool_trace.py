"""conversation_turn tool_trace

Neue Spalte `tool_trace` (JSON) auf `conversation_turn`: haelt fest, welche
Agent-Core-Tools fuer einen Assistant-Turn aufgerufen wurden, siehe
models.ConversationTurn-Docstring / assistant_memory.append_turn.

Revision ID: b302d771c019
Revises: c4a8_devices
Create Date: 2026-09-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b302d771c019"
down_revision: Union[str, Sequence[str], None] = "c4a8_devices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("conversation_turn")}
    if "tool_trace" not in cols:
        with op.batch_alter_table("conversation_turn", schema=None) as b:
            b.add_column(sa.Column("tool_trace", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("conversation_turn", schema=None) as b:
        b.drop_column("tool_trace")

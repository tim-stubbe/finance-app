"""assistant_memory + conversation_turn: dauerhaftes Assistenten-Gedächtnis

Neue Tabellen (Modelle `AssistantMemory`, `ConversationTurn`). Auf frischer
DB legt sie die Baseline/`create_all` an; hier für Bestandsinstallationen.
Guards via `has_table`, damit die Migration idempotent bleibt.

Revision ID: b7e1_assistant_memory
Revises: a3d1_proactive_proposals
Create Date: 2026-09-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7e1_assistant_memory"
down_revision: Union[str, Sequence[str], None] = "a3d1_proactive_proposals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())

    if not insp.has_table("assistant_memory"):
        op.create_table(
            "assistant_memory",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("text", sa.String(), nullable=False),
            sa.Column("category", sa.String(), nullable=False, server_default="fakt"),
            sa.Column("source", sa.String(), nullable=False, server_default="manuell"),
            sa.Column("importance", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("status", sa.String(), nullable=False, server_default="aktiv"),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("key", name="uq_assistant_memory_key"),
        )
        with op.batch_alter_table("assistant_memory", schema=None) as b:
            b.create_index(b.f("ix_assistant_memory_id"), ["id"], unique=False)
            b.create_index(b.f("ix_assistant_memory_created_at"), ["created_at"], unique=False)
            b.create_index(b.f("ix_assistant_memory_last_used_at"), ["last_used_at"], unique=False)
            b.create_index(b.f("ix_assistant_memory_expires_at"), ["expires_at"], unique=False)

    if not insp.has_table("conversation_turn"):
        op.create_table(
            "conversation_turn",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("chat_id", sa.String(), nullable=True),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("summarized", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("conversation_turn", schema=None) as b:
            b.create_index(b.f("ix_conversation_turn_id"), ["id"], unique=False)
            b.create_index(b.f("ix_conversation_turn_created_at"), ["created_at"], unique=False)
            b.create_index(b.f("ix_conversation_turn_chat_id"), ["chat_id"], unique=False)


def downgrade() -> None:
    op.drop_table("conversation_turn")
    op.drop_table("assistant_memory")

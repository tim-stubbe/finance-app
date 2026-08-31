"""proactive_proposals: strukturierte Vorschläge des proaktiven Assistenten

Neue Tabelle (Modell `ProactiveProposal`). Auf frischer DB legt sie die
Baseline/`create_all` an; hier für Bestandsinstallationen.

Revision ID: a3d1_proactive_proposals
Revises: 9b2c_recipes_nutrition
Create Date: 2026-08-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a3d1_proactive_proposals"
down_revision: Union[str, Sequence[str], None] = "9b2c_recipes_nutrition"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("proactive_proposals"):
        return
    op.create_table(
        "proactive_proposals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("urgency", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("options_json", sa.Text(), nullable=True),
        sa.Column("dedup_key", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("chosen_key", sa.String(), nullable=True),
        sa.Column("result_text", sa.Text(), nullable=True),
        sa.Column("answered_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("proactive_proposals", schema=None) as b:
        b.create_index(b.f("ix_proactive_proposals_id"), ["id"], unique=False)
        b.create_index(b.f("ix_proactive_proposals_created_at"), ["created_at"], unique=False)
        b.create_index(b.f("ix_proactive_proposals_dedup_key"), ["dedup_key"], unique=False)
        b.create_index(b.f("ix_proactive_proposals_status"), ["status"], unique=False)


def downgrade() -> None:
    op.drop_table("proactive_proposals")

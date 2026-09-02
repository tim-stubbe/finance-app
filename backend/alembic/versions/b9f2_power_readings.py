"""power_readings + Settings.homeassistant_power_entity

Server-Stromverbrauch: HA-Watt-Sensor pollen (Modell PowerReading) und die
entity_id auf Settings. Guards via inspect, damit idempotent.

Revision ID: b9f2_power_readings
Revises: b7e1_assistant_memory
Create Date: 2026-09-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b9f2_power_readings"
down_revision: Union[str, Sequence[str], None] = "b7e1_assistant_memory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())

    cols = {c["name"] for c in insp.get_columns("settings")}
    if "homeassistant_power_entity" not in cols:
        op.add_column("settings", sa.Column("homeassistant_power_entity", sa.String(), nullable=True))

    if not insp.has_table("power_readings"):
        op.create_table(
            "power_readings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("ts", sa.DateTime(), nullable=True),
            sa.Column("watts", sa.Float(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("power_readings", schema=None) as b:
            b.create_index(b.f("ix_power_readings_id"), ["id"], unique=False)
            b.create_index(b.f("ix_power_readings_ts"), ["ts"], unique=False)


def downgrade() -> None:
    op.drop_table("power_readings")
    with op.batch_alter_table("settings", schema=None) as b:
        b.drop_column("homeassistant_power_entity")

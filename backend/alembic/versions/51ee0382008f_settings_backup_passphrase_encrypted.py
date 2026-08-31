"""settings backup_passphrase_encrypted

Revision ID: 51ee0382008f
Revises: 0001_baseline
Create Date: 2026-08-31 08:20:25.770755
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '51ee0382008f'
down_revision: Union[str, Sequence[str], None] = '0001_baseline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    # Guard fuer die Uebergangsphase: solange main.py nach den Migrationen noch
    # create_all/ensure_columns als Sicherheitsnetz faehrt, koennte die Spalte
    # bei einer frischen DB je nach Reihenfolge schon existieren.
    if not _has_column("settings", "backup_passphrase_encrypted"):
        with op.batch_alter_table("settings", schema=None) as batch_op:
            batch_op.add_column(sa.Column("backup_passphrase_encrypted", sa.String(), nullable=True))


def downgrade() -> None:
    if _has_column("settings", "backup_passphrase_encrypted"):
        with op.batch_alter_table("settings", schema=None) as batch_op:
            batch_op.drop_column("backup_passphrase_encrypted")

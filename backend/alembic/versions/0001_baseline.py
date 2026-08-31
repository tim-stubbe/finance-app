"""baseline - Schemastand zum Zeitpunkt der Alembic-Einfuehrung

Diese Revision definiert KEIN handgeschriebenes CREATE TABLE. Die Baseline ist
schlicht "alles, was die SQLAlchemy-Modelle beschreiben" (`create_all`). Damit
ist sie automatisch deckungsgleich mit dem, was `models.Base.metadata.create_all`
+ die alten `ensure_columns`-Aufrufe in `main.py` bisher schon aufgebaut haben.

Bestehende Installationen (finance.db existiert, aber ohne `alembic_version`)
werden von `app/db_migrate.run_migrations` auf DIESE Revision *gestempelt*, statt
sie auszufuehren - die Tabellen sind dort ja schon da. Nur eine wirklich leere
DB laesst `upgrade()` hier tatsaechlich laufen.

Ab hier gilt: Schema-Aenderungen NUR noch als neue Alembic-Revision
(`cd backend && alembic revision --autogenerate -m "..."`), keine neuen
`ensure_columns`-Zeilen mehr.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-31
"""
from typing import Sequence, Union

from alembic import op

from app import models

revision: str = "0001_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    models.Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    models.Base.metadata.drop_all(bind=op.get_bind())

"""recipes: Naehrwert-Spalten (kcal/protein_g/carbs_g/fat_g) nachziehen

Diese Spalten kamen mit dem "Essen: Ernaehrungs-Profil"-Feature ans Recipe-
Modell, bekamen aber weder eine `ensure_columns`-Zeile noch (vor Alembic) eine
Migration - Bestandsinstallationen hatten die `recipes`-Tabelle also ohne sie,
was `GET /api/meals/*` mit `no such column: recipes.kcal` (500) killte.

Die eingefrorene Baseline (0001) legt `recipes` bereits MIT den Spalten an
(sie wurde aus dem aktuellen Modellstand erzeugt) - eine frische DB braucht
hier nichts, daher die "existiert schon?"-Pruefung. Bestandsinstallationen
bekommen die vier ALTERs.

Revision ID: 9b2c_recipes_nutrition
Revises: 51ee0382008f
Create Date: 2026-08-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9b2c_recipes_nutrition"
down_revision: Union[str, Sequence[str], None] = "51ee0382008f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = ("kcal", "protein_g", "carbs_g", "fat_g")


def _existing(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    have = _existing("recipes")
    todo = [c for c in _COLUMNS if c not in have]
    if not todo:
        return
    with op.batch_alter_table("recipes", schema=None) as batch_op:
        for col in todo:
            batch_op.add_column(sa.Column(col, sa.Integer(), nullable=True))


def downgrade() -> None:
    have = _existing("recipes")
    with op.batch_alter_table("recipes", schema=None) as batch_op:
        for col in _COLUMNS:
            if col in have:
                batch_op.drop_column(col)

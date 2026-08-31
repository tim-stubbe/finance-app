"""Alembic-Grundgeruest (siehe app/db_migrate.py, backend/alembic/).

conftest importiert `app.main` -> `run_migrations()` ist beim Testlauf schon
gelaufen. Hier wird geprueft, dass die DB danach auf head steht und dass die
Modelle nicht von der Migrations-Historie abgedriftet sind (der wiederkehrende
Nutzen: eine neue Modell-Spalte ohne passende Revision faellt hier auf).
"""
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from sqlalchemy import inspect, text

from app.database import engine, Base
from app.db_migrate import _alembic_config, verify_and_heal_schema


def test_db_is_at_alembic_head():
    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    assert current == head


def test_no_structural_schema_drift():
    with engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn, opts={"compare_type": True, "render_as_batch": True}
        )
        diffs = compare_metadata(ctx, Base.metadata)

    # compare_metadata liefert entweder ein Tupel ("add_column", ...) oder bei
    # Feindiffs (Typ/Default) eine Liste solcher Tupel. Nur strukturelle
    # Abweichungen sind hier ein Fehler - SQLite meldet bei Typen gern
    # Pseudo-Unterschiede.
    structural = {"add_table", "remove_table", "add_column", "remove_column"}
    flat = []
    for d in diffs:
        flat.extend(d if isinstance(d, list) else [d])
    offenders = [d for d in flat if d and d[0] in structural]
    assert not offenders, f"Schema weicht von den Migrationen ab: {offenders}"


def test_verify_and_heal_schema_readds_missing_nullable_column():
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE recipes DROP COLUMN kcal"))
    assert "kcal" not in {c["name"] for c in inspect(engine).get_columns("recipes")}

    verify_and_heal_schema()

    assert "kcal" in {c["name"] for c in inspect(engine).get_columns("recipes")}

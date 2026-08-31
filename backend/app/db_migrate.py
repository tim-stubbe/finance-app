"""Alembic-Autostart beim App-Import.

`main.py` baut das Schema weiterhin zuerst per `create_all` + `ensure_columns`
auf (Sicherheitsnetz fuer den Uebergang) und ruft danach `run_migrations()`:

* frische DB / DB ohne `alembic_version`, aber mit Tabellen -> auf die Baseline
  STEMPELN (nicht ausfuehren, die Tabellen sind schon da);
* danach in jedem Fall `upgrade head` -> spielt alle noch offenen Revisionen
  ein.

Kuenftige Schema-Aenderungen kommen als neue Alembic-Revision dazu
(`cd backend && alembic revision --autogenerate -m "..."`), nicht mehr als
weitere `ensure_columns`-Zeile.
"""
import logging
import os

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.schema import CreateColumn

from . import models
from .database import engine

log = logging.getLogger("kies.schema")

_ALEMBIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic")
BASELINE_REVISION = "0001_baseline"


def _alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", _ALEMBIC_DIR)
    cfg.set_main_option("sqlalchemy.url", str(engine.url))
    return cfg


def run_migrations() -> None:
    cfg = _alembic_config()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
        has_schema = inspect(conn).has_table("settings")

    if current is None and has_schema:
        # Bestehende Installation ohne Migrations-Historie: Tabellen existieren
        # bereits (create_all/ensure_columns), also nur den Startpunkt setzen.
        command.stamp(cfg, BASELINE_REVISION)

    command.upgrade(cfg, "head")


def verify_and_heal_schema() -> None:
    """Sicherheitsnetz gegen vergessene Migrationen: eine Modell-Spalte ohne
    passende Migration schlaegt sonst erst beim ersten Query als 500 auf
    (genau so ist `recipes.kcal` monatelang unentdeckt geblieben). Hier wird
    beim Start jede fehlende, NULLABLE Spalte still per ALTER ergaenzt und
    laut geloggt - der eigentliche Fix bleibt eine echte Revision, aber die
    Produktion faellt in der Zwischenzeit nicht um.

    NOT-NULL-/Tabellen-Abweichungen werden nur gemeldet (Tabellen deckt
    ohnehin `create_all` ab)."""
    healed, warned = [], []

    with engine.begin() as conn:
        insp = inspect(conn)  # frische Reflection auf DIESER Verbindung
        existing_tables = set(insp.get_table_names())
        for table in models.Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                warned.append(f"Tabelle {table.name} fehlt")
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                if not col.nullable and col.default is None and col.server_default is None:
                    warned.append(f"{table.name}.{col.name} (NOT NULL) fehlt - Migration noetig")
                    continue
                ddl = str(CreateColumn(col).compile(dialect=conn.dialect))
                try:
                    conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {ddl}"))
                except OperationalError:  # z.B. Spalte doch schon da (Reflection-Cache)
                    continue
                healed.append(f"{table.name}.{col.name}")

    if healed:
        log.warning("Schema-Drift automatisch geflickt (ALTER ADD): %s - "
                    "bitte eine Alembic-Revision dafuer nachreichen.", ", ".join(healed))
    for w in warned:
        log.warning("Schema-Drift: %s", w)

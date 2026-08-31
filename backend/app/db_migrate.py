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
import os

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

from .database import engine

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

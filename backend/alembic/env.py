"""Alembic-Umgebung.

Die DB-URL kommt bewusst aus `app.database` (also aus `DATA_DIR`), NICHT aus
`alembic.ini` - so treffen CLI (`alembic ...`) und der Autostart der App
(`app/db_migrate.py`) immer dieselbe `finance.db`.

SQLite kann `ALTER TABLE` nur sehr eingeschraenkt: `render_as_batch=True` laesst
Alembic Aenderungen ueber die "batch"-Methode (Tabelle neu bauen + kopieren)
erzeugen, sonst scheitern Spalten-Aenderungen/-Drops.
"""
from logging.config import fileConfig

from alembic import context

from app.database import engine, Base
from app import models  # noqa: F401  - registriert alle Modelle an Base.metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=str(engine.url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

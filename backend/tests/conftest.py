"""Pytest-Grundgerüst - erste automatisierte Tests für Kies (siehe README/
ROADMAP: bisher gab es nur manuelles Live-Testen im laufenden Container vor
jedem Push, kein automatisierter Test existierte).

WICHTIG: `DATA_DIR` muss auf ein frisches Temp-Verzeichnis zeigen, BEVOR
`app.database`/`app.main` importiert werden - beide legen Engine/Tabellen
schon beim Modul-Import an (kein FastAPI-Startup-Event, siehe database.py/
main.py), nicht erst beim ersten Request. Deshalb hier zuerst der env-var,
dann erst der Import - in der falschen Reihenfolge würde die Test-Suite
gegen die echte /data/finance.db laufen.

Bekannte Einschränkung: `app.main` startet beim Import auch den echten
APScheduler (main.py:scheduler.start(), ebenfalls Modul-Level statt
Startup-Event) - in der kurzen Testlaufzeit gegen eine leere Test-DB feuert
praktisch keiner der Cron-Jobs, aber sauber wäre es nicht. Eine Umstellung
auf FastAPI-Lifespan-Events wäre der richtige Fix, ist aber ein größerer,
risikoreicherer Umbau an main.py selbst - bewusst nicht Teil dieser ersten
Test-Suite, siehe ROADMAP.
"""
import os
import tempfile

import pytest

_tmp_data_dir = tempfile.mkdtemp(prefix="kies-test-")
os.environ["DATA_DIR"] = _tmp_data_dir

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.database import SessionLocal, engine, Base  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    """Leert vor JEDEM Test alle Tabellen (statt einer komplett neuen DB pro
    Test - schneller, und create_all()/ensure_columns() liefen ohnehin schon
    beim Modul-Import einmal). Reihenfolge rückwärts wegen Foreign Keys."""
    yield
    db = SessionLocal()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
    finally:
        db.close()


@pytest.fixture
def client():
    # base_url MUSS https sein: SessionMiddleware/CSRF-Cookie laufen mit
    # https_only=True (die App ist ausschließlich per HTTPS erreichbar, siehe
    # main.py) - mit dem httpx-Default http://testserver würde der Session-
    # Cookie beim ersten Roundtrip gesetzt, aber vom Client wegen des
    # Secure-Flags nie wieder zurückgeschickt (live beobachtet: /status zeigte
    # nach erfolgreichem /setup fälschlich authenticated=False).
    return TestClient(app, base_url="https://testserver")

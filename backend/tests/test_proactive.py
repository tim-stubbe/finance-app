"""Proaktiver KI-Assistent (proactive.py): opt-in, Ollama-Pflicht,
8-Minuten-Untergrenze und Dedup gegen die letzte Meldung."""
import uuid
from datetime import date, datetime, timedelta

from app import auth, models, proactive, ollama_client
from app.database import SessionLocal


def _add_overdue_todo(db):
    db.add(models.Todo(uid=uuid.uuid4().hex, title="Steuererklärung", done=False,
                       due_date=date.today() - timedelta(days=10)))
    db.commit()


def _settings(with_content=True, **over):
    db = SessionLocal()
    s = auth.get_or_create_settings(db)
    s.notifications_enabled = True
    s.ollama_url = "http://o"
    s.ollama_model = "m"
    s.proactive_assistant_enabled = True
    s.proactive_assistant_last_sent_at = None
    s.proactive_assistant_last_hash = None
    for k, v in over.items():
        setattr(s, k, v)
    db.commit()
    if with_content:
        _add_overdue_todo(db)  # sonst greift der "leerer Snapshot"-Kurzschluss
    return db, s


def test_disabled_returns_none(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "chat", lambda *a, **k: "Trink mehr Wasser.")
    db, s = _settings(proactive_assistant_enabled=False)
    try:
        assert proactive.generate(db, s) is None
    finally:
        db.close()


def test_needs_ollama(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "chat", lambda *a, **k: "Etwas Nützliches.")
    db, s = _settings(ollama_url=None)
    try:
        assert proactive.generate(db, s) is None
    finally:
        db.close()


def test_nichts_is_swallowed(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "chat", lambda *a, **k: "NICHTS")
    db, s = _settings()
    try:
        assert proactive.generate(db, s) is None
    finally:
        db.close()


def test_real_suggestion_then_cooldown_and_dedup(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "chat",
                        lambda *a, **k: "Dein Budget für Essen ist zu 90 % ausgeschöpft, noch 8 Tage im Monat.")
    db, s = _settings()
    try:
        res = proactive.generate(db, s)
        assert res is not None
        text, digest = res
        assert "Budget" in text and len(digest) == 16

        # 8-Minuten-Untergrenze: gerade gesendet -> noch nichts Neues
        s.proactive_assistant_last_sent_at = datetime.utcnow()
        s.proactive_assistant_last_hash = digest
        db.commit()
        assert proactive.generate(db, s) is None

        # Untergrenze vorbei, Snapshot unverändert -> KI wird gar nicht befragt
        s.proactive_assistant_last_sent_at = datetime.utcnow() - timedelta(minutes=20)
        db.commit()
        assert proactive.generate(db, s) is None

        # Snapshot ändert sich, aber die KI liefert denselben Text -> Reply-Dedup
        _add_overdue_todo(db)
        assert proactive.generate(db, s) is None
    finally:
        db.close()

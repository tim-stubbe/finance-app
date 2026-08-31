"""Proaktiver KI-Assistent (proactive.py): opt-in, Ollama-Pflicht, Snooze,
Dedup über dedup_key. Seit dem Umbau liefert die KI strukturiertes JSON und
proactive.run() gibt die neu angelegten Vorschläge zurück."""
import json
import uuid
from datetime import date, datetime, timedelta

from app import auth, models, proactive, ollama_client
from app.database import SessionLocal

_ONE = json.dumps({"proposals": [{
    "kind": "wahl", "urgency": "mittel", "title": "Steuererklärung ist überfällig",
    "body": "Spart Ärger mit dem Finanzamt.", "dedup": "steuer-ueberfaellig",
    "options": [
        {"label": "Als To-do für morgen", "action": {"type": "todo_add",
         "params": {"title": "Steuererklärung", "due_date": "2026-09-01"}}},
        {"label": "Später erinnern", "action": {"type": "remind_later", "params": {"days": 3}}},
    ]}]})


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


def test_disabled_returns_nothing(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "chat", lambda *a, **k: _ONE)
    db, s = _settings(proactive_assistant_enabled=False)
    try:
        assert proactive.run(db, s) == []
    finally:
        db.close()


def test_needs_ollama(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "chat", lambda *a, **k: _ONE)
    db, s = _settings(ollama_url=None)
    try:
        assert proactive.run(db, s) == []
    finally:
        db.close()


def test_empty_json_yields_nothing(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "chat", lambda *a, **k: '{"proposals": []}')
    db, s = _settings()
    try:
        assert proactive.run(db, s) == []
    finally:
        db.close()


def test_snapshot_includes_health_trends(client):
    db = SessionLocal()
    s = auth.get_or_create_settings(db)
    try:
        for i in range(4):
            db.add(models.HealthMetric(metric_type=models.HealthMetricType.schlaf,
                                       date=date.today() - timedelta(days=i), value=5.2))
        db.commit()
        snap = proactive.build_snapshot(db, s, 1)
        assert "Schlaf: zuletzt" in snap
        assert "3 Nächte in Folge unter 6 h" in snap
    finally:
        db.close()


def test_snooze_blocks(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "chat", lambda *a, **k: _ONE)
    db, s = _settings(proactive_assistant_snoozed_until=datetime.utcnow() + timedelta(hours=3))
    try:
        assert proactive.run(db, s) == []
        # abgelaufene Pause -> wieder aktiv
        s.proactive_assistant_snoozed_until = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
        assert len(proactive.run(db, s)) == 1
    finally:
        db.close()


def test_telegram_proaktiv_command(client, monkeypatch):
    from app import telegram_bot
    sent = []
    monkeypatch.setattr(telegram_bot, "_send", lambda tok, cid, msg: sent.append(msg))
    db, s = _settings()
    try:
        assert telegram_bot._handle_proactive_command(db, s, "t", "c", "/proaktiv aus")
        assert s.proactive_assistant_enabled is False
        assert telegram_bot._handle_proactive_command(db, s, "t", "c", "/proaktiv an")
        assert s.proactive_assistant_enabled is True
        assert telegram_bot._handle_proactive_command(db, s, "t", "c", "/proaktiv pause 5")
        assert s.proactive_assistant_snoozed_until > datetime.utcnow() + timedelta(hours=4)
        assert not telegram_bot._handle_proactive_command(db, s, "t", "c", "/etwas anderes")
    finally:
        db.close()


def test_telegram_proaktiv_feedback_command(client, monkeypatch):
    from app import telegram_bot
    sent = []
    monkeypatch.setattr(telegram_bot, "_send", lambda tok, cid, msg: sent.append(msg))
    db, s = _settings()
    try:
        # Ohne letzte Meldung: nur Hinweis, kein Eintrag.
        s.proactive_assistant_last_text = None
        assert telegram_bot._handle_proactive_feedback_command(db, s, "t", "c", "/nützlich")
        assert db.query(models.ProactiveFeedback).count() == 0

        s.proactive_assistant_last_text = "Dein Essens-Budget ist fast aufgebraucht."
        db.commit()
        assert telegram_bot._handle_proactive_feedback_command(db, s, "t", "c", "/unnötig")
        assert telegram_bot._handle_proactive_feedback_command(db, s, "t", "c", "/nützlich")
        rows = db.query(models.ProactiveFeedback).order_by(models.ProactiveFeedback.id).all()
        assert [r.useful for r in rows] == [False, True]
        assert all(r.text == "Dein Essens-Budget ist fast aufgebraucht." for r in rows)

        assert not telegram_bot._handle_proactive_feedback_command(db, s, "t", "c", "/anderes")

        hint = proactive._feedback_hint(db)
        assert "UNNÖTIG" in hint and "NÜTZLICH" in hint
    finally:
        db.close()


def test_dedup_key_prevents_repeat(client, monkeypatch):
    """Kein Cooldown - aber derselbe Vorschlag (gleicher dedup_key) kommt nicht
    zweimal. Ein inhaltlich anderer Vorschlag schon."""
    monkeypatch.setattr(ollama_client, "chat", lambda *a, **k: _ONE)
    db, s = _settings()
    try:
        first = proactive.run(db, s)
        assert len(first) == 1 and first[0].dedup_key == "steuer-ueberfaellig"

        assert proactive.run(db, s) == []  # gleicher dedup_key -> nichts Neues

        other = json.dumps({"proposals": [{
            "kind": "info", "title": "Ganz andere Sache", "dedup": "andere-sache"}]})
        monkeypatch.setattr(ollama_client, "chat", lambda *a, **k: other)
        assert len(proactive.run(db, s)) == 1
    finally:
        db.close()

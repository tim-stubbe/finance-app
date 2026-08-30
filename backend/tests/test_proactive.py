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
    monkeypatch.setattr(ollama_client, "chat", lambda *a, **k: "Etwas Nützliches passiert gerade.")
    db, s = _settings(proactive_assistant_snoozed_until=datetime.utcnow() + timedelta(hours=3))
    try:
        assert proactive.generate(db, s) is None
        # abgelaufene Pause -> wieder aktiv
        s.proactive_assistant_snoozed_until = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
        assert proactive.generate(db, s) is not None
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


def test_no_throttle_repeats_allowed(client, monkeypatch):
    """Nach "nimm alle Limits raus": keine Cooldown-/Dedup-Sperre mehr - was
    zaehlt ist nur, ob die KI etwas sagt (statt "NICHTS")."""
    monkeypatch.setattr(ollama_client, "chat",
                        lambda *a, **k: "Dein Budget für Essen ist zu 90 % ausgeschöpft, noch 8 Tage im Monat.")
    db, s = _settings()
    try:
        first = proactive.generate(db, s)
        assert first is not None and "Budget" in first[0]

        # gerade eben gesendet + identischer Hash gespeichert -> trotzdem wieder
        s.proactive_assistant_last_sent_at = datetime.utcnow()
        s.proactive_assistant_last_hash = first[1]
        db.commit()
        again = proactive.generate(db, s)
        assert again is not None and again[0] == first[0]
    finally:
        db.close()

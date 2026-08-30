"""notifications.notify() protokolliert jede Meldung in models.NotificationLog
(auch die per Ruhezeiten unterdrückten) und GET /api/notifications/log gibt
den Verlauf zurück."""
from datetime import datetime

from app import auth, bank_sync, models, notifications
from app.database import SessionLocal


def _telegram_configured(db):
    s = auth.get_or_create_settings(db)
    s.notifications_enabled = True
    s.telegram_bot_token_encrypted = bank_sync.encrypt_secret(s.secret_key, "tok")
    s.telegram_chat_id = "123"
    s.quiet_hours_enabled = False
    s.quiet_until = None
    db.commit()
    return s


def test_notify_writes_log(client, monkeypatch):
    monkeypatch.setattr(notifications, "send_telegram", lambda *a, **k: None)
    db = SessionLocal()
    try:
        s = _telegram_configured(db)
        notifications.notify(s, "Testmeldung eins")
        rows = db.query(models.NotificationLog).all()
        assert any(r.text == "Testmeldung eins" and r.sent for r in rows)
    finally:
        db.close()


def test_quiet_hours_logged_as_not_sent(client, monkeypatch):
    calls = []
    monkeypatch.setattr(notifications, "send_telegram", lambda *a, **k: calls.append(1))
    now_h = datetime.now().hour
    db = SessionLocal()
    try:
        s = _telegram_configured(db)
        s.quiet_hours_enabled = True
        s.quiet_hours_start_hour = now_h
        s.quiet_hours_end_hour = (now_h + 2) % 24
        db.commit()
        notifications.notify(s, "Nachtmeldung")
        assert not calls
        rows = db.query(models.NotificationLog).filter(models.NotificationLog.text == "Nachtmeldung").all()
        assert rows and all(r.sent is False for r in rows)
    finally:
        db.close()


def test_log_endpoint(client, monkeypatch):
    client.post("/api/auth/setup", json={"password": "Sicheres-Testpasswort-123"})
    monkeypatch.setattr(notifications, "send_telegram", lambda *a, **k: None)
    db = SessionLocal()
    try:
        notifications.notify(_telegram_configured(db), "Endpunkt-Test")
    finally:
        db.close()
    r = client.get("/api/notifications/log?limit=10")
    assert r.status_code == 200
    assert any(row["text"] == "Endpunkt-Test" for row in r.json())

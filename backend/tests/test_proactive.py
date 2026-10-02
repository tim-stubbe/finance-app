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


def test_snapshot_includes_realistic_liquidity(client, monkeypatch):
    db = SessionLocal()
    s = auth.get_or_create_settings(db)
    try:
        monkeypatch.setattr(proactive.crud, "cashflow_forecast", lambda *args, **kwargs: type("F", (), {
            "start_balance": 200.0,
            "planning_balance": 1000.0,
            "expected_receivables": 900.0,
            "expected_payables": 100.0,
            "lowest_balance": 150.0,
        })())
        snap = proactive.build_snapshot(db, s, 1)
        assert "realistisch verfügbar 1.000 €" in snap
        assert "bestätigte Rückzahlungen/Forderungen +900 €" in snap
        assert "offene Schulden -100 €" in snap
    finally:
        db.close()


def test_active_trip_hides_school_routine_but_keeps_real_appointments(client):
    db = SessionLocal()
    s = auth.get_or_create_settings(db)
    try:
        space = db.query(models.Space).first()
        db.add(models.Trip(space_id=space.id, name="Berlin", start_date=date.today(),
                           end_date=date.today() + timedelta(days=6)))
        start = datetime.utcnow() + timedelta(days=1)
        db.add_all([
            models.CalendarEvent(uid="webuntis-42@kies", title="Unterricht", start=start,
                                 end=start + timedelta(minutes=45), location="Schule", all_day=False),
            models.CalendarEvent(uid="private-arzt", title="Arzt", start=start,
                                 end=start + timedelta(minutes=30), location="Berlin", all_day=False),
        ])
        db.commit()

        snap = proactive.build_snapshot(db, s, space.id)
        assert "AKTIVER REISEMODUS: Berlin" in snap
        assert "Unterricht" not in snap
        assert "Arzt" in snap and "@ Berlin" in snap
    finally:
        db.close()


def test_quiet_hours_block_proactive_run(client, monkeypatch):
    import app.proactive as p
    monkeypatch.setattr(ollama_client, "chat", lambda *a, **k: _ONE)
    db, s = _settings(quiet_hours_enabled=True, quiet_hours_start_hour=2,
                      quiet_hours_end_hour=7)
    try:
        # 3 Uhr nachts -> Ruhezeit -> nichts
        monkeypatch.setattr(p, "datetime", type("D", (), {
            "utcnow": staticmethod(lambda: datetime(2026, 9, 1, 3, 0)),
            "now": staticmethod(lambda: datetime(2026, 9, 1, 3, 0))}))
        assert p.run(db, s) == []
        # 10 Uhr -> aktiv
        monkeypatch.setattr(p, "datetime", type("D", (), {
            "utcnow": staticmethod(lambda: datetime(2026, 9, 1, 10, 0)),
            "now": staticmethod(lambda: datetime(2026, 9, 1, 10, 0))}))
        assert len(p.run(db, s)) == 1
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


def test_remind_later_snoozes_only_that_topic(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "chat", lambda *a, **k: _ONE)
    db, s = _settings()
    try:
        proposal = proactive.run(db, s)[0]
        result = proactive.answer(db, s, proposal.id, "b")
        db.refresh(proposal)
        assert "3 Tag" in result
        assert proposal.status == "snoozed"
        assert proposal.expires_at > datetime.utcnow() + timedelta(days=2)
        assert s.proactive_assistant_snoozed_until is None
        assert proposal.dedup_key in proactive._recent_dedup_keys(db)
    finally:
        db.close()


def test_minimum_gap_blocks_differently_worded_followup(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "chat", lambda *a, **k: _ONE)
    db, s = _settings(proactive_assistant_min_gap_hours=4)
    try:
        assert len(proactive.run(db, s)) == 1
        # Selbst ein anderes Thema darf nicht direkt den naechsten Push ausloesen.
        monkeypatch.setattr(ollama_client, "chat", lambda *a, **k: json.dumps({"proposals": [{
            "kind": "info", "title": "Ganz anderes Thema", "dedup": "anderes-thema"
        }]}))
        assert proactive.run(db, s) == []
    finally:
        db.close()


def test_snoozed_topic_stays_quiet_when_llm_renames_it(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "chat", lambda *a, **k: json.dumps({"proposals": [{
        "kind": "wahl", "title": "Drohne verkaufen", "dedup": "drohne-alt",
        "options": [
            {"label": "Später", "action": {"type": "remind_later", "params": {"days": 7}}},
            {"label": "Nein", "action": {"type": "dismiss"}},
        ],
    }]}))
    db, s = _settings()
    try:
        first = proactive.run(db, s)[0]
        proactive.answer(db, s, first.id, "a")
        # Abstand bewusst ablaufen lassen: Hier soll die Themen-Sperre greifen.
        s.proactive_assistant_last_sent_at = datetime.utcnow() - timedelta(days=1)
        db.commit()
        monkeypatch.setattr(ollama_client, "chat", lambda *a, **k: json.dumps({"proposals": [{
            "kind": "info", "title": "Drohnen-Verkauf prüfen", "dedup": "neuer-key"
        }]}))
        assert proactive.run(db, s) == []
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
    db, s = _settings(proactive_assistant_min_gap_hours=0)
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

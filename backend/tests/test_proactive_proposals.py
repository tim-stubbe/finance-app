"""Strukturierte proaktive Vorschläge (proactive.py + proactive_actions.py)."""
import json

from app import proactive, proactive_actions, models
from app.database import SessionLocal


def _settings(db):
    from app import auth
    s = auth.get_or_create_settings(db)
    s.proactive_assistant_enabled = True
    s.notifications_enabled = True
    s.ollama_url = "http://x"
    s.ollama_model = "m"
    db.commit()
    return s


def test_sanitize_unknown_action_becomes_open():
    raw = {
        "kind": "wahl", "urgency": "hoch", "title": "3 Fahrten offen",
        "body": "Spart dir das Einzeln-Klicken.",
        "options": [
            {"label": "Alle geschäftlich", "action": {"type": "trips_classify_all",
                                                      "params": {"purpose": "geschaeftlich"}}},
            {"label": "Hack the mainframe", "action": {"type": "rm_rf", "params": {}}},
        ],
    }
    s = proactive._sanitize(raw)
    assert s["kind"] == "wahl"
    assert s["options"][0]["action"]["type"] == "trips_classify_all"
    assert s["options"][1]["action"]["type"] == "open"          # degradiert
    # letzte Option ist automatisch eine Ausweichoption
    assert s["options"][-1]["action"]["type"] in ("dismiss", "remind_later")


def test_extract_json_tolerates_fences_and_prose():
    txt = 'Klar!\n```json\n{"proposals": [{"kind":"info","title":"Hi"}]}\n```\ndanke'
    assert proactive._extract_json(txt)["proposals"][0]["title"] == "Hi"


def test_think_persists_and_answer_executes(monkeypatch):
    db = SessionLocal()
    try:
        s = _settings(db)
        payload = json.dumps({"proposals": [{
            "kind": "wahl", "urgency": "mittel", "title": "Test-Todo anlegen?",
            "body": "warum", "dedup": "fix-key",
            "options": [
                {"label": "To-do anlegen", "action": {"type": "todo_add",
                                                      "params": {"title": "Aus Vorschlag"}}},
                {"label": "Nein", "action": {"type": "dismiss"}},
            ]}]})
        monkeypatch.setattr("app.ollama_client.chat", lambda *a, **k: payload)

        created = proactive.run(db, s)
        assert len(created) == 1
        pid = created[0].id

        # zweiter Lauf: gleicher dedup_key -> nichts Neues
        assert proactive.run(db, s) == []

        result = proactive.answer(db, s, pid, "a")
        assert "angelegt" in result.lower()
        assert db.query(models.Todo).filter(models.Todo.title == "Aus Vorschlag").count() == 1
        row = db.query(models.ProactiveProposal).get(pid)
        assert row.status == "beantwortet" and row.chosen_key == "a"

        # erneute Antwort auf denselben Vorschlag -> abgewiesen
        assert "erledigt" in proactive.answer(db, s, pid, "a").lower()
    finally:
        db.close()


def test_registry_actions_all_callable():
    for name, fn in proactive_actions.REGISTRY.items():
        assert callable(fn), name


def test_push_proposal_creates_row_and_dedups():
    db = SessionLocal()
    try:
        s = _settings(db)
        p = proactive.push_proposal(
            db, s, title="Preiserhöhung: Spotify",
            body="10 → 12 €.", urgency="mittel", dedup_key="anom-x",
            options=[{"label": "Notieren", "action": {"type": "note_add", "params": {"text": "hoch"}}},
                     {"label": "Ignorieren", "action": {"type": "dismiss"}}])
        assert p is not None and p.status == "offen"
        opts = json.loads(p.options_json)
        assert opts[0]["action"]["type"] == "note_add"
        # gleicher dedup_key innerhalb 7 Tagen -> None
        assert proactive.push_proposal(db, s, title="Nochmal", dedup_key="anom-x",
                                       options=[{"label": "x", "action": {"type": "dismiss"}}]) is None
    finally:
        db.close()


def test_push_proposal_answer_runs_action():
    db = SessionLocal()
    try:
        s = _settings(db)
        p = proactive.push_proposal(
            db, s, title="Ausreißer: Lebensmittel", urgency="mittel", dedup_key="anom-y",
            options=[{"label": "To-do", "action": {"type": "todo_add", "params": {"title": "Prüfen"}}},
                     {"label": "Ignorieren", "action": {"type": "dismiss"}}])
        proactive.answer(db, s, p.id, "a")
        assert db.query(models.Todo).filter(models.Todo.title == "Prüfen").count() == 1
    finally:
        db.close()


def test_new_actions_calendar_and_wishlist():
    from app import auth
    db = SessionLocal()
    try:
        s = auth.get_or_create_settings(db)
        r1 = proactive_actions.execute(db, s, {"type": "wishlist_add",
                                               "params": {"name": "Kopfhörer", "target_price": 99}})
        assert "Kopfhörer" in r1
        assert db.query(models.WishlistItem).filter_by(name="Kopfhörer").count() == 1
        r2 = proactive_actions.execute(db, s, {"type": "calendar_add",
                                               "params": {"title": "Zahnarzt", "date": "2027-01-15", "time": "09:30"}})
        assert "Zahnarzt" in r2
        assert db.query(models.CalendarEvent).filter_by(title="Zahnarzt").count() == 1
    finally:
        db.close()


def test_meal_plan_fill_no_recipes_is_noop():
    from app import auth
    db = SessionLocal()
    try:
        s = auth.get_or_create_settings(db)
        out = proactive_actions.execute(db, s, {"type": "meal_plan_fill", "params": {}})
        assert "Rezept" in out  # "Noch keine Rezepte angelegt ..."
    finally:
        db.close()


def test_too_similar_catches_near_duplicate_titles():
    assert proactive._too_similar(
        "Drohne-Karte & Zigaretten-Verkauf",
        ["Dringende Entscheidung: Drohne-Karte und Zigaretten-Verkauf"])
    assert not proactive._too_similar(
        "Wochenplan füllen", ["Fahrten einordnen", "Steuer vorbereiten"])


def test_dismiss_records_negative_feedback(monkeypatch):
    db = SessionLocal()
    try:
        s = _settings(db)
        payload = json.dumps({"proposals": [{
            "kind": "wahl", "urgency": "mittel", "title": "Nervnachricht", "dedup": "x",
            "options": [{"label": "Nein danke", "action": {"type": "dismiss"}}]}]})
        monkeypatch.setattr("app.ollama_client.chat", lambda *a, **k: payload)
        pid = proactive.run(db, s)[0].id
        proactive.answer(db, s, pid, "a")
        fb = db.query(models.ProactiveFeedback).order_by(models.ProactiveFeedback.id.desc()).first()
        assert fb and fb.useful is False and "Nervnachricht" in fb.text
    finally:
        db.close()

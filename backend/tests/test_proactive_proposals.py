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

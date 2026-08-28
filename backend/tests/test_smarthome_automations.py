"""KI-Automationen (Phase 4): die KI schlaegt Ablaeufe vor und schreibt die
Home-Assistant-Automation (YAML). Ollama und Home Assistant sind gemockt -
getestet wird die Logik drumherum: Vorschlaege anlegen, YAML validieren
(unbekannte entity_ids, nicht freigegebene Services), Anlegen in HA, und dass
ein gesperrter Service das Anlegen blockiert.
"""

import json

import pytest

from app import ha_client, ollama_client, auth, bank_sync
from app.database import SessionLocal


@pytest.fixture
def configured(auth_client, monkeypatch):
    db = SessionLocal()
    s = auth.get_or_create_settings(db)
    s.homeassistant_url = "http://ha.test:8123"
    s.homeassistant_token_encrypted = bank_sync.encrypt_secret(s.secret_key, "tok")
    s.ollama_url = "http://ollama.test:11434"
    s.ollama_model = "test-model"
    db.commit()
    db.close()
    states = [
        {"entity_id": "light.wohnzimmer", "state": "on", "attributes": {"friendly_name": "Wohnzimmer Licht"}},
        {"entity_id": "cover.bad", "state": "open", "attributes": {"friendly_name": "Bad Rollladen"}},
    ]
    monkeypatch.setattr(ha_client, "get_states", lambda u, t: states)
    monkeypatch.setattr(ha_client, "area_map", lambda u, t: {})
    monkeypatch.setattr(ha_client, "list_automations", lambda u, t: [])
    return auth_client


def _mock_chat(monkeypatch, response):
    monkeypatch.setattr(ollama_client, "chat", lambda *a, **k: response)


def test_suggest_creates_drafts(configured, monkeypatch):
    _mock_chat(monkeypatch, json.dumps({"ideas": [
        {"title": "Abends Licht an", "description": "Bei Sonnenuntergang Wohnzimmerlicht einschalten",
         "trigger": "Sonnenuntergang", "entities": ["light.wohnzimmer"]},
    ]}))
    r = configured.post("/api/smarthome/automations/suggest", json={"count": 5})
    assert r.status_code == 200
    assert r.json()[0]["title"] == "Abends Licht an"
    lst = configured.get("/api/smarthome/automations").json()
    assert lst[0]["status"] == "vorschlag"


def test_draft_yaml_clean(configured, monkeypatch):
    _mock_chat(monkeypatch, json.dumps({"ideas": [
        {"title": "T", "description": "d", "trigger": "x", "entities": ["light.wohnzimmer"]}]}))
    did = configured.post("/api/smarthome/automations/suggest", json={"count": 1}).json()[0]["id"]

    _mock_chat(monkeypatch,
               "alias: Test\ntrigger:\n  - platform: sun\n    event: sunset\naction:\n"
               "  - service: light.turn_on\n    target:\n      entity_id: light.wohnzimmer\n")
    r = configured.post(f"/api/smarthome/automations/{did}/draft")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "entwurf"
    assert body["warnings"] == []
    assert "light.turn_on" in body["yaml"]


def test_draft_yaml_flags_unknown_entity_and_blocked_service(configured, monkeypatch):
    _mock_chat(monkeypatch, json.dumps({"ideas": [
        {"title": "T2", "description": "d", "trigger": "x", "entities": []}]}))
    did = configured.post("/api/smarthome/automations/suggest", json={"count": 1}).json()[0]["id"]

    _mock_chat(monkeypatch,
               "alias: Boese\ntrigger:\n  - platform: state\n    entity_id: binary_sensor.tuer\n"
               "action:\n  - service: lock.unlock\n    target:\n      entity_id: lock.haustuer\n")
    body = configured.post(f"/api/smarthome/automations/{did}/draft").json()
    joined = " ".join(body["warnings"])
    assert "Unbekannte entity_ids" in joined
    assert "Nicht freigegebene Services" in joined


def test_apply_pushes_to_ha(configured, monkeypatch):
    _mock_chat(monkeypatch, json.dumps({"ideas": [
        {"title": "T3", "description": "d", "trigger": "x", "entities": ["light.wohnzimmer"]}]}))
    did = configured.post("/api/smarthome/automations/suggest", json={"count": 1}).json()[0]["id"]
    _mock_chat(monkeypatch,
               "alias: T3\ntrigger:\n  - platform: sun\n    event: sunset\naction:\n"
               "  - service: light.turn_on\n    target:\n      entity_id: light.wohnzimmer\n")
    configured.post(f"/api/smarthome/automations/{did}/draft")

    pushed = {}
    monkeypatch.setattr(ha_client, "create_automation",
                        lambda u, t, aid, body: pushed.update(aid=aid, body=body) or {})
    monkeypatch.setattr(ha_client, "reload_automations", lambda u, t: None)

    r = configured.post(f"/api/smarthome/automations/{did}/apply")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "angelegt"
    assert body["ha_entity_id"].startswith("automation.kies_")
    assert pushed["body"]["alias"] == "T3"


def test_apply_blocked_by_disallowed_service(configured, monkeypatch):
    _mock_chat(monkeypatch, json.dumps({"ideas": [
        {"title": "T4", "description": "d", "trigger": "x", "entities": []}]}))
    did = configured.post("/api/smarthome/automations/suggest", json={"count": 1}).json()[0]["id"]
    _mock_chat(monkeypatch,
               "alias: T4\ntrigger:\n  - platform: state\n    entity_id: sun.sun\n"
               "action:\n  - service: lock.unlock\n    target:\n      entity_id: lock.haustuer\n")
    configured.post(f"/api/smarthome/automations/{did}/draft")

    monkeypatch.setattr(ha_client, "create_automation", lambda *a, **k: pytest.fail("darf nicht aufgerufen werden"))
    r = configured.post(f"/api/smarthome/automations/{did}/apply")
    assert r.status_code == 400
    assert "Nicht freigegebene Services" in r.json()["detail"]


def test_freeform_draft(configured, monkeypatch):
    _mock_chat(monkeypatch,
               "alias: Freitext\ntrigger:\n  - platform: sun\n    event: sunset\naction:\n"
               "  - service: cover.close_cover\n    target:\n      entity_id: cover.bad\n")
    r = configured.post("/api/smarthome/automations/draft-freeform",
                        json={"text": "Rollladen im Bad bei Sonnenuntergang schließen"})
    assert r.status_code == 200
    assert r.json()["status"] == "entwurf"
    assert "cover.close_cover" in r.json()["yaml"]


def test_scheduled_weekly_suggestion_nudge(configured, monkeypatch):
    """Der Wochen-Job erzeugt Vorschläge und meldet EINEN Sammel-Hinweis
    über die bestehende AssistantSuggestion-Queue."""
    from app import main, notifications
    db = SessionLocal()
    s = auth.get_or_create_settings(db)
    s.notifications_enabled = True
    db.commit()
    db.close()
    _mock_chat(monkeypatch, json.dumps({"ideas": [
        {"title": "Nachts alles aus", "description": "d", "trigger": "23 Uhr", "entities": ["light.wohnzimmer"]}]}))
    notes = []
    monkeypatch.setattr(notifications, "notify", lambda settings, text, **k: notes.append(text))

    main._scheduled_smarthome_automation_suggestions()
    assert notes and "Automations-Idee" in notes[0]

    # Zweiter Lauf in derselben ISO-Woche -> kein neuer Hinweis (dedupliziert)
    notes.clear()
    main._scheduled_smarthome_automation_suggestions()
    assert notes == []


def test_suggest_without_ollama_is_400(auth_client, monkeypatch):
    monkeypatch.setattr(ha_client, "get_states", lambda u, t: [])
    monkeypatch.setattr(ha_client, "area_map", lambda u, t: {})
    r = auth_client.post("/api/smarthome/automations/suggest", json={"count": 3})
    assert r.status_code == 400
    assert "Ollama" in r.json()["detail"]

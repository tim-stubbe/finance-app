"""Universelle Hub-Kommandozeile (hub_command.route / POST /api/hub/command).

Ollama ist gemockt - getestet wird das Routing in die richtige Domaene und
dass geldbezogene Aktionen nur vorgeschlagen (nicht gebucht) werden.
"""

import json

import pytest

from app import ollama_client, ha_client, auth, bank_sync
from app.database import SessionLocal


@pytest.fixture
def hub(auth_client, monkeypatch):
    db = SessionLocal()
    s = auth.get_or_create_settings(db)
    s.ollama_url = "http://ollama.test:11434"
    s.ollama_model = "m"
    s.homeassistant_url = "http://ha.test:8123"
    s.homeassistant_token_encrypted = bank_sync.encrypt_secret(s.secret_key, "tok")
    db.commit()
    db.close()
    monkeypatch.setattr(ha_client, "get_states", lambda u, t: [])
    monkeypatch.setattr(ha_client, "area_map", lambda u, t: {})
    return auth_client


def _chat_returns(monkeypatch, *responses):
    """Nacheinander abrufbare Ollama-Antworten (letzte wird wiederholt)."""
    calls = list(responses)

    def fake(url, model, messages, timeout=600):
        return calls.pop(0) if len(calls) > 1 else calls[0]

    monkeypatch.setattr(ollama_client, "chat", fake)


def _cmd(client, text):
    return client.post("/api/hub/command", json={"text": text}).json()


def test_routes_todo(hub, monkeypatch):
    _chat_returns(monkeypatch, json.dumps({"domain": "todo", "title": "Müll rausbringen", "due": None, "reply": "Notiert."}))
    r = _cmd(hub, "erinnere mich, den Müll rauszubringen")
    assert r["domain"] == "todo" and r["ok"] is True
    assert any(t["title"] == "Müll rausbringen" for t in hub.get("/api/todos").json())


def test_routes_wishlist(hub, monkeypatch):
    _chat_returns(monkeypatch, json.dumps({"domain": "wunschliste", "name": "Bohrmaschine", "price": 89.9, "reply": "Draufgesetzt."}))
    r = _cmd(hub, "setz eine Bohrmaschine auf die Wunschliste")
    assert r["domain"] == "wunschliste"
    assert any(w["name"] == "Bohrmaschine" for w in hub.get("/api/wishlist").json())


def test_routes_navigation(hub, monkeypatch):
    _chat_returns(monkeypatch, json.dumps({"domain": "navigation", "tab": "investments", "reply": "Öffne Investments."}))
    r = _cmd(hub, "zeig mir die investments")
    assert r["domain"] == "navigation" and r["tab"] == "investments"


def test_expense_is_only_suggested(hub, monkeypatch):
    _chat_returns(monkeypatch, json.dumps({"domain": "ausgabe", "amount": 12.5, "merchant": "Rewe", "note": "", "reply": "Vorschlag."}))
    r = _cmd(hub, "12,50 bei Rewe bezahlt")
    assert r["domain"] == "ausgabe"
    assert r["route"] == "expense"          # nur Navigation zum Buchungs-Formular
    assert r["params"]["amount"] == 12.5    # geparst, aber NICHT gebucht


def test_routes_smarthome(hub, monkeypatch):
    _chat_returns(monkeypatch, json.dumps({"domain": "smarthome", "text": "Wohnzimmerlicht aus", "reply": ""}))
    calls = []
    monkeypatch.setattr(ha_client, "get_states", lambda u, t: [
        {"entity_id": "light.wohnzimmer", "state": "on", "attributes": {"friendly_name": "Wohnzimmer Licht"}}])
    monkeypatch.setattr(ha_client, "call_service", lambda u, t, d, sv, dt: calls.append((d, sv)) or [])
    # Alias -> Schnellpfad, damit process_command keinen (gemockten) Ollama-Intent braucht
    hub.post("/api/smarthome/aliases", json={"phrase": "Wohnzimmerlicht", "entity_id": "light.wohnzimmer"})
    r = _cmd(hub, "mach das licht im wohnzimmer aus")
    assert r["domain"] == "smarthome"
    assert ("light", "turn_off") in calls


def test_unparseable_falls_back_to_chat(hub, monkeypatch):
    _chat_returns(monkeypatch, "kein json, nur text")
    r = _cmd(hub, "hallo")
    assert r["domain"] == "chat" and r["ok"] is True
    assert "text" in r["reply"].lower() or r["reply"]


def test_question_uses_second_call(hub, monkeypatch):
    _chat_returns(monkeypatch,
                  json.dumps({"domain": "frage", "reply": ""}),
                  "Du hast diesen Monat 0 € ausgegeben.")
    r = _cmd(hub, "wie viel habe ich diesen monat ausgegeben")
    assert r["domain"] == "frage"
    assert "ausgegeben" in r["reply"]

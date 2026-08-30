"""Einheitliche Jarvis-Intent-Schicht (app/jarvis.py) + /api/jarvis/command.

Deckt die Schnellpfade OHNE Ollama ab (Haus / Alltag / Finanzen-lesend) und
das Kurzzeitgedächtnis. Der Ollama-Fallback wird hier nicht geübt (kein
Modell in der Test-Umgebung) - das ist Sache von test_smarthome / test_hub.
"""
import pytest

from app import auth, bank_sync, ha_client, jarvis
from app.database import SessionLocal


@pytest.fixture(autouse=True)
def _clear_memory():
    jarvis.forget()
    yield
    jarvis.forget()


@pytest.fixture
def configured_ha(auth_client, monkeypatch):
    db = SessionLocal()
    s = auth.get_or_create_settings(db)
    s.homeassistant_url = "http://ha.test:8123"
    s.homeassistant_token_encrypted = bank_sync.encrypt_secret(s.secret_key, "tok")
    db.commit()
    db.close()
    calls = []
    fake_states = [
        {"entity_id": "light.bad", "state": "on", "attributes": {"friendly_name": "Bad Licht"}},
    ]
    monkeypatch.setattr(ha_client, "get_states", lambda url, token: fake_states)
    monkeypatch.setattr(ha_client, "area_map", lambda url, token: {})
    monkeypatch.setattr(ha_client, "call_service",
                        lambda url, token, d, s, data: calls.append((d, s, data)) or [])
    return calls


def test_command_shape_is_uniform(auth_client):
    r = auth_client.post("/api/jarvis/command", json={"text": "was hängt?"})
    assert r.status_code == 200
    body = r.json()
    assert set(("ok", "reply", "actions", "domain")).issubset(body)
    assert body["domain"] == "alltag"


def test_todo_fastpath_creates_without_ollama(auth_client):
    r = auth_client.post("/api/jarvis/command", json={"text": "Todo: Mülltonne rausstellen"})
    body = r.json()
    assert body["ok"] and body["domain"] == "alltag"
    assert "Mülltonne" in body["reply"]
    assert any(a.get("type") == "todo_created" for a in body["actions"])
    assert any(t["title"] == "Mülltonne rausstellen"
               for t in auth_client.get("/api/todos").json())


def test_saldo_fastpath_is_read_only(auth_client):
    auth_client.post("/api/accounts", json={"name": "Giro", "type": "girokonto", "initial_balance": 100})
    r = auth_client.post("/api/jarvis/command", json={"text": "wie ist mein Kontostand?"})
    body = r.json()
    assert body["domain"] == "finanzen"
    assert "Giro" in body["reply"]


def test_house_fastpath_and_memory_followup(auth_client, configured_ha):
    auth_client.post("/api/smarthome/aliases", json={"phrase": "Badlicht", "entity_id": "light.bad"})
    # 1) klarer Haus-Befehl -> direkt geschaltet, Entity landet im Gedächtnis
    r1 = auth_client.post("/api/jarvis/command", json={"text": "Badlicht an"}).json()
    assert r1["domain"] == "smarthome" and r1["ok"]
    assert ("light", "turn_on", {"entity_id": "light.bad"}) in configured_ha
    mem = auth_client.get("/api/jarvis/memory").json()
    assert mem.get("entity_id") == "light.bad"
    # 2) Folgebefehl ohne Gerätewort -> greift auf das Gedächtnis zurück
    configured_ha.clear()
    r2 = auth_client.post("/api/jarvis/command", json={"text": "mach das wieder aus"}).json()
    assert r2["domain"] == "smarthome"
    assert ("light", "turn_off", {"entity_id": "light.bad"}) in configured_ha


def test_memory_clear_endpoint(auth_client, configured_ha):
    auth_client.post("/api/smarthome/aliases", json={"phrase": "Badlicht", "entity_id": "light.bad"})
    auth_client.post("/api/jarvis/command", json={"text": "Badlicht an"})
    assert auth_client.delete("/api/jarvis/memory").json()["ok"] is True
    assert auth_client.get("/api/jarvis/memory").json() == {}


def test_house_summary_endpoint_unconfigured(auth_client):
    r = auth_client.get("/api/jarvis/house-summary")
    assert r.status_code == 200
    assert r.json()["ha_configured"] is False

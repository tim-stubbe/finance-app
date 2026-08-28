"""Smart-Home-Assistent (Home Assistant <-> lokale Ollama, siehe
app/smarthome.py). Deckt die Teile ab, die ohne echten HA-/Ollama-Server
testbar sind: Policy/Allowlist, Schnellpfad-Intent-Erkennung, tolerantes
JSON-Parsen, Alias-Matching, und die Pipeline-Endpunkte mit gemocktem
ha_client (kein Netz).
"""

import pytest

from app import smarthome, ha_client, auth, bank_sync
from app.database import SessionLocal


# ---------------- Reine Einheiten ----------------

def test_parse_fast_intent_on_off():
    assert smarthome.parse_fast_intent("Licht Wohnzimmer aus")["action"] == "turn_off"
    assert smarthome.parse_fast_intent("mach das Licht an")["action"] == "turn_on"
    assert smarthome.parse_fast_intent("wie warm ist es im Bad") is None


def test_parse_fast_intent_brightness_and_temp():
    assert smarthome.parse_fast_intent("dimm das Licht auf 30%") == {"action": "set_brightness", "value": 30}
    assert smarthome.parse_fast_intent("stell die Heizung auf 21 Grad") == {"action": "set_temperature", "value": 21.0}


def test_service_allowed_and_blocked():
    assert smarthome.service_allowed("light", "turn_on")
    assert not smarthome.service_allowed("light", "explode")
    # Nie erlaubt, auch nicht ueber die Zusatz-Allowlist:
    assert not smarthome.service_allowed("lock", "unlock", ["lock.unlock"])
    # Zusatz-Freigabe greift fuer nicht-gesperrte Services:
    assert smarthome.service_allowed("vacuum", "start", ["vacuum.start"])


def test_parse_json_lenient_handles_fences_and_prose():
    assert smarthome.parse_json_lenient('```json\n{"intent": "chat"}\n```')["intent"] == "chat"
    assert smarthome.parse_json_lenient('Klar! {"intent": "query", "reply": "ok"} fertig')["reply"] == "ok"
    with pytest.raises(ValueError):
        smarthome.parse_json_lenient("überhaupt kein json")


def test_match_aliases_prefers_longer_phrase():
    aliases = [
        {"phrase": "licht", "entity_id": "light.alle"},
        {"phrase": "wohnzimmer licht", "entity_id": "light.wohnzimmer"},
    ]
    assert smarthome.match_aliases("mach das wohnzimmer licht aus", aliases)[0] == "light.wohnzimmer"


def test_match_aliases_same_phrase_two_devices_is_ambiguous():
    aliases = [
        {"phrase": "Lampe", "entity_id": "light.a"},
        {"phrase": "Lampe", "entity_id": "light.b"},
    ]
    assert set(smarthome.match_aliases("Lampe aus", aliases)) == {"light.a", "light.b"}


# ---------------- Endpunkte (nicht eingerichtet) ----------------

def test_health_endpoint_reports_unconfigured(auth_client):
    r = auth_client.get("/api/smarthome/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ha_configured"] is False
    assert body["ha_connected"] is False


def test_command_without_setup_is_soft_error(auth_client):
    r = auth_client.post("/api/smarthome/command", json={"text": "Licht an"})
    assert r.status_code == 200  # kein 500-Stacktrace an den Nutzer
    body = r.json()
    assert body["ok"] is False
    assert "eingerichtet" in body["reply"].lower()


def test_alias_crud_roundtrip(auth_client):
    r = auth_client.post("/api/smarthome/aliases", json={"phrase": "Testlicht", "entity_id": "light.test"})
    assert r.status_code == 200
    alias_id = r.json()["id"]
    assert any(a["phrase"] == "Testlicht" for a in auth_client.get("/api/smarthome/aliases").json())
    assert auth_client.delete(f"/api/smarthome/aliases/{alias_id}").status_code == 200
    assert auth_client.get("/api/smarthome/aliases").json() == []


def test_alias_rejects_invalid_entity_id(auth_client):
    r = auth_client.post("/api/smarthome/aliases", json={"phrase": "x", "entity_id": "keinpunkt"})
    assert r.status_code == 400


# ---------------- Pipeline mit gemocktem Home Assistant ----------------

@pytest.fixture
def configured_ha(auth_client, monkeypatch):
    """Settings mit HA-URL/-Token bestuecken und ha_client komplett mocken -
    kein Netzwerk. Gibt die Liste der ausgefuehrten Service-Calls zurueck."""
    db = SessionLocal()
    s = auth.get_or_create_settings(db)
    s.homeassistant_url = "http://ha.test:8123"
    s.homeassistant_token_encrypted = bank_sync.encrypt_secret(s.secret_key, "tok")
    db.commit()
    db.close()

    calls = []
    fake_states = [
        {"entity_id": "light.wohnzimmer", "state": "on",
         "attributes": {"friendly_name": "Wohnzimmer Licht"}},
        {"entity_id": "light.kueche", "state": "off",
         "attributes": {"friendly_name": "Küche Licht"}},
    ]
    monkeypatch.setattr(ha_client, "get_states", lambda url, token: fake_states)
    monkeypatch.setattr(ha_client, "area_map", lambda url, token: {})
    monkeypatch.setattr(ha_client, "call_service",
                        lambda url, token, domain, service, data: calls.append((domain, service, data)) or [])
    return calls


def test_fastpath_alias_switches_directly(auth_client, configured_ha):
    auth_client.post("/api/smarthome/aliases", json={"phrase": "Wohnzimmerlicht", "entity_id": "light.wohnzimmer"})
    r = auth_client.post("/api/smarthome/command", json={"text": "Wohnzimmerlicht aus"})
    body = r.json()
    assert body["ok"] is True
    assert body["intent"] == "control"
    assert configured_ha == [("light", "turn_off", {"entity_id": "light.wohnzimmer"})]


def test_fastpath_ambiguous_asks_back(auth_client, configured_ha):
    # Derselbe Sprich-Name zeigt auf zwei Geraete -> Rueckfrage statt raten,
    # es darf kein Service ausgefuehrt werden.
    auth_client.post("/api/smarthome/aliases", json={"phrase": "Lampe", "entity_id": "light.wohnzimmer"})
    auth_client.post("/api/smarthome/aliases", json={"phrase": "Lampe", "entity_id": "light.kueche"})
    r = auth_client.post("/api/smarthome/command", json={"text": "Lampe aus"})
    body = r.json()
    assert body["intent"] == "clarify"
    assert body["needs_confirmation"] is True
    assert len(body["candidates"]) == 2
    assert configured_ha == []


def test_ha_down_returns_clean_message(auth_client, configured_ha, monkeypatch):
    def boom(url, token):
        raise ha_client.HAError("Home Assistant ist nicht erreichbar unter http://ha.test:8123. Laeuft HA?")
    monkeypatch.setattr(ha_client, "get_states", boom)
    r = auth_client.post("/api/smarthome/command", json={"text": "Wohnzimmerlicht aus"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "nicht erreichbar" in body["reply"]

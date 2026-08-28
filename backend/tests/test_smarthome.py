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


def test_health_quick_skips_network_probes(auth_client, monkeypatch):
    # quick=1 darf ha_client/ollama gar nicht erst anfassen (Hub-Panel-Aufruf)
    import app.smarthome as sh
    monkeypatch.setattr(sh, "health", lambda s: (_ for _ in ()).throw(AssertionError("nicht aufrufen")))
    r = auth_client.get("/api/smarthome/health?quick=1")
    assert r.status_code == 200
    assert r.json() == {"ha_configured": False, "ollama_configured": False, "live": False}


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


# ---------------- Grundriss (Phase 3) ----------------

def test_floorplan_defaults_empty(auth_client):
    r = auth_client.get("/api/smarthome/floorplan")
    assert r.status_code == 200
    body = r.json()
    assert body["rooms"] == [] and body["devices"] == [] and body["states"] == {}


def test_floorplan_save_and_reload(auth_client):
    plan = {
        "rooms": [{"id": "r1", "name": "Wohnzimmer", "x": 0, "y": 0, "w": 5, "h": 4}],
        "devices": [{"entity_id": "light.wohnzimmer", "x": 2.5, "y": 2, "room_id": "r1"}],
    }
    assert auth_client.put("/api/smarthome/floorplan", json=plan).status_code == 200
    back = auth_client.get("/api/smarthome/floorplan").json()
    assert back["rooms"][0]["name"] == "Wohnzimmer"
    assert back["devices"][0]["entity_id"] == "light.wohnzimmer"


def test_floorplan_autolayout_from_areas(auth_client, configured_ha, monkeypatch):
    from app import ha_client as hac
    monkeypatch.setattr(hac, "area_map", lambda u, t: {"light.wohnzimmer": "Wohnzimmer",
                                                       "light.kueche": "Küche"})
    r = auth_client.post("/api/smarthome/floorplan/autolayout")
    assert r.status_code == 200
    plan = r.json()
    names = {room["name"] for room in plan["rooms"]}
    assert {"Wohnzimmer", "Küche"} <= names
    # jedes Geraet hat einen Raum zugeordnet bekommen
    assert all(d.get("room_id") for d in plan["devices"])
    # bleibt gespeichert
    assert auth_client.get("/api/smarthome/floorplan").json()["rooms"]


def test_floorplan_merges_live_states(auth_client, configured_ha):
    auth_client.put("/api/smarthome/floorplan", json={
        "rooms": [], "devices": [{"entity_id": "light.wohnzimmer", "x": 1, "y": 1}],
    })
    body = auth_client.get("/api/smarthome/floorplan").json()
    assert body["states"]["light.wohnzimmer"]["state"] == "on"


# ---------------- Live-Zustaende (WebSocket-Cache) ----------------

def test_ws_cache_liveness_and_snapshot():
    from app import smarthome_ws
    c = smarthome_ws._Cache()
    assert c.is_live() is False
    c.connected = True
    c.replace_all([{"entity_id": "light.x", "state": "on"}])
    assert c.is_live() is True
    assert {s["entity_id"] for s in c.snapshot()} == {"light.x"}
    c.update_one("light.x", {"entity_id": "light.x", "state": "off"})
    assert c.snapshot()[0]["state"] == "off"
    c.update_one("light.x", None)  # removed
    assert c.snapshot() == []


def test_get_states_prefers_ws_cache(monkeypatch):
    from app import smarthome, smarthome_ws, ha_client as hac
    monkeypatch.setattr(smarthome_ws, "cached_states",
                        lambda: [{"entity_id": "light.cached", "state": "on", "attributes": {}}])
    monkeypatch.setattr(hac, "get_states", lambda u, t: (_ for _ in ()).throw(AssertionError("REST nicht noetig")))

    class _S:
        homeassistant_url = "http://ha"
        secret_key = "k"
        homeassistant_token_encrypted = None
    got = smarthome._get_states(_S())
    assert got[0]["entity_id"] == "light.cached"


def test_events_stream_generator_yields_comment_first():
    # Direkt gegen den Generator (nicht ueber den TestClient-Stream, der sonst
    # auf das 20s-Timeout des naechsten q.get() warten wuerde).
    from app import smarthome_ws
    gen = smarthome_ws.events_stream()
    try:
        first = next(gen)
        assert first.startswith(b":")
    finally:
        gen.close()


# ---------------- Szenen (Phase 2 der Liste) ----------------

def test_create_and_list_scene(auth_client, configured_ha, monkeypatch):
    from app import ha_client as hac
    # Geraet mit Zusatz-Attribut
    states = [{"entity_id": "light.wohnzimmer", "state": "on",
               "attributes": {"friendly_name": "Wohnzimmer Licht", "brightness": 180}},
              {"entity_id": "scene.kies_abend", "state": "unknown",
               "attributes": {"friendly_name": "Abend", "entity_id": ["light.wohnzimmer"]}}]
    monkeypatch.setattr(hac, "get_states", lambda u, t: states)
    created = {}
    monkeypatch.setattr(hac, "create_scene",
                        lambda u, t, sid, body: created.update(sid=sid, body=body) or {})
    monkeypatch.setattr(hac, "reload_scenes", lambda u, t: None)

    r = auth_client.post("/api/smarthome/scenes",
                         json={"name": "Abend", "entity_ids": ["light.wohnzimmer"]})
    assert r.status_code == 200
    assert r.json()["entity_id"] == "scene.kies_abend"
    assert created["sid"] == "kies_abend"
    ent = created["body"]["entities"]["light.wohnzimmer"]
    assert ent["state"] == "on" and ent["brightness"] == 180

    scenes = auth_client.get("/api/smarthome/scenes").json()
    assert any(s["entity_id"] == "scene.kies_abend" for s in scenes)


def test_activate_scene(auth_client, configured_ha):
    r = auth_client.post("/api/smarthome/scenes/activate", json={"entity_id": "scene.kies_abend"})
    assert r.status_code == 200
    assert ("scene", "turn_on", {"entity_id": "scene.kies_abend"}) in configured_ha


def test_activate_scene_rejects_non_scene(auth_client, configured_ha):
    assert auth_client.post("/api/smarthome/scenes/activate",
                            json={"entity_id": "light.x"}).status_code == 400


# ---------------- Automations-Dashboard (Phase 3 der Liste) ----------------

def test_list_live_automations(auth_client, configured_ha, monkeypatch):
    from app import ha_client as hac
    monkeypatch.setattr(hac, "get_states", lambda u, t: [
        {"entity_id": "automation.abends", "state": "on",
         "attributes": {"friendly_name": "Abends", "last_triggered": "2026-08-28T20:00:00+00:00", "current": 0}},
        {"entity_id": "automation.pause", "state": "off",
         "attributes": {"friendly_name": "Pausiert"}},
    ])
    rows = auth_client.get("/api/smarthome/automations/live").json()
    by = {r["entity_id"]: r for r in rows}
    assert by["automation.abends"]["enabled"] is True
    assert by["automation.pause"]["enabled"] is False


def test_toggle_and_run_live_automation(auth_client, configured_ha):
    assert auth_client.post("/api/smarthome/automations/live/automation.x/toggle?enabled=false").status_code == 200
    assert ("automation", "turn_off", {"entity_id": "automation.x"}) in configured_ha
    assert auth_client.post("/api/smarthome/automations/live/automation.x/run").status_code == 200
    assert ("automation", "trigger", {"entity_id": "automation.x"}) in configured_ha


def test_toggle_rejects_non_automation(auth_client, configured_ha):
    assert auth_client.post("/api/smarthome/automations/live/light.x/toggle").status_code == 400


# ---------------- Energie (Phase 4 der Liste) ----------------

def test_energy_summary(auth_client, configured_ha, monkeypatch):
    from app import ha_client as hac
    monkeypatch.setattr(hac, "get_states", lambda u, t: [
        {"entity_id": "sensor.gesamt", "state": "250",
         "attributes": {"friendly_name": "Gesamt", "device_class": "power", "unit_of_measurement": "W"}},
        {"entity_id": "sensor.spuelmaschine", "state": "1.5",
         "attributes": {"friendly_name": "Spülmaschine", "unit_of_measurement": "kW"}},
        {"entity_id": "sensor.zaehler", "state": "1234.5",
         "attributes": {"friendly_name": "Zähler", "device_class": "energy", "unit_of_measurement": "kWh"}},
    ])
    # Preis setzen
    auth_client.put("/api/smarthome/settings", json={"electricity_price": 0.40})
    e = auth_client.get("/api/smarthome/energy").json()
    assert e["total_power_w"] == 1750.0          # 250 + 1500
    assert e["price_per_kwh"] == 0.40
    assert e["est_daily_cost"] == round(1.75 * 24 * 0.40, 2)
    assert any(s["entity_id"] == "sensor.zaehler" and s["kwh"] == 1234.5 for s in e["energy_sensors"])


# ---------------- Morgen-Briefing-Notizen (Phase 6) ----------------

def test_morning_notes(monkeypatch):
    from app import smarthome, ha_client as hac
    from datetime import datetime, timezone, timedelta

    class _S:
        homeassistant_url = "http://ha"
        homeassistant_token_encrypted = "x"
        secret_key = "k"
        homeassistant_allowed_domains = None
        homeassistant_allowed_areas = None
    monkeypatch.setattr(smarthome, "_token", lambda s: "tok")
    old = (datetime.now(timezone.utc) - timedelta(hours=9)).isoformat()
    monkeypatch.setattr(hac, "get_states", lambda u, t: [
        {"entity_id": "cover.bad", "state": "open", "attributes": {"friendly_name": "Bad Rollladen"}},
        {"entity_id": "climate.wz", "state": "heat", "attributes": {"friendly_name": "Wohnzimmer", "temperature": 22}},
        {"entity_id": "light.flur", "state": "on", "attributes": {"friendly_name": "Flur"}, "last_changed": old},
        {"entity_id": "binary_sensor.tuer", "state": "on",
         "attributes": {"friendly_name": "Haustür", "device_class": "door"}},
    ])
    notes = smarthome.morning_notes(_S())
    joined = " ".join(notes)
    assert "Bad Rollladen" in joined
    assert "Wohnzimmer (22°)" in joined
    assert "Flur" in joined
    assert "Haustür" in joined


# ---------------- Telegram /haus ----------------

def test_telegram_haus_command(auth_client, configured_ha, monkeypatch):
    from app import telegram_bot
    from app.database import SessionLocal
    from app import auth as _auth

    auth_client.post("/api/smarthome/aliases",
                     json={"phrase": "Wohnzimmerlicht", "entity_id": "light.wohnzimmer"})
    sent = []
    monkeypatch.setattr(telegram_bot, "_send", lambda tok, cid, txt: sent.append(txt))

    db = SessionLocal()
    s = _auth.get_or_create_settings(db)
    handled = telegram_bot._handle_home_command(db, s, "tok", "cid", "/haus Wohnzimmerlicht aus")
    db.close()

    assert handled is True
    assert sent and "Wohnzimmer Licht" in sent[0]
    assert configured_ha == [("light", "turn_off", {"entity_id": "light.wohnzimmer"})]


def test_telegram_haus_ignores_other_text(monkeypatch):
    from app import telegram_bot
    from app.database import SessionLocal
    from app import auth as _auth
    db = SessionLocal()
    s = _auth.get_or_create_settings(db)
    assert telegram_bot._handle_home_command(db, s, "t", "c", "/saldo Giro 100") is False
    db.close()


def test_ha_down_returns_clean_message(auth_client, configured_ha, monkeypatch):
    def boom(url, token):
        raise ha_client.HAError("Home Assistant ist nicht erreichbar unter http://ha.test:8123. Laeuft HA?")
    monkeypatch.setattr(ha_client, "get_states", boom)
    r = auth_client.post("/api/smarthome/command", json={"text": "Wohnzimmerlicht aus"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "nicht erreichbar" in body["reply"]


# ---------------- Lebensbereiche-Jahres-Heatmap (Phase 8) ----------------

def test_life_heatmap(auth_client):
    area = auth_client.post("/api/life-areas", json={"name": "Sport"}).json()
    auth_client.post("/api/life-checkins", json={"area_id": area["id"], "note": "gelaufen"})
    auth_client.post("/api/life-checkins", json={"area_id": area["id"], "note": "nochmal"})
    hm = auth_client.get("/api/life-areas/heatmap?days=30").json()
    assert len(hm) == 30
    assert hm[-1]["count"] == 2          # beide Check-ins heute
    assert all(h["count"] == 0 for h in hm[:-1])

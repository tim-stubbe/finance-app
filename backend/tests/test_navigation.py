import pytest
from datetime import datetime
from fastapi import HTTPException
from types import SimpleNamespace

from app.routers import navigation
from app import models
from app.database import SessionLocal


class Response:
    def raise_for_status(self): pass
    def json(self):
        return {"ok": True, "stations": [{
            "id": "one", "name": "Test", "brand": "Kies Fuel",
            "street": "Testweg 1", "place": "Mainz", "lat": 49.99,
            "lng": 8.25, "price": 1.629, "isOpen": True,
        }]}


def test_fuel_station_key_stays_server_side(monkeypatch):
    monkeypatch.setenv("TANKERKOENIG_API_KEY", "server-secret")
    captured = {}
    def fake_get(url, params, timeout):
        captured.update(params)
        return Response()
    monkeypatch.setattr(navigation.requests, "get", fake_get)
    result = navigation.fuel_stations(49.98, 8.24, 10, "diesel", None, None)
    assert result["stations"][0]["price"] == 1.629
    assert result["stations"][0]["distance_km"] > 0
    assert captured["apikey"] == "server-secret"
    assert "apikey" not in result


def test_fuel_station_missing_server_key(monkeypatch):
    monkeypatch.delenv("TANKERKOENIG_API_KEY", raising=False)
    monkeypatch.setattr(navigation.auth, "get_or_create_settings", lambda db: SimpleNamespace(
        tankerkoenig_api_key_encrypted=None, secret_key="unused"
    ))
    with pytest.raises(HTTPException) as exc:
        navigation.fuel_stations(49.98, 8.24, 10, "diesel", None, None)
    assert exc.value.status_code == 503


def test_fuel_station_uses_encrypted_settings_key(monkeypatch):
    monkeypatch.delenv("TANKERKOENIG_API_KEY", raising=False)
    monkeypatch.setattr(navigation.auth, "get_or_create_settings", lambda db: SimpleNamespace(
        tankerkoenig_api_key_encrypted="encrypted", secret_key="secret"
    ))
    monkeypatch.setattr(navigation.bank_sync, "decrypt_secret", lambda key, value: "db-key")
    seen = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True, "stations": []}

    def fake_get(url, params, timeout):
        seen.update(params)
        return Response()

    monkeypatch.setattr(navigation.requests, "get", fake_get)
    result = navigation.fuel_stations(49.98, 8.24, 10, "diesel", None, None)
    assert result["stations"] == []
    assert result["fuel"] == "diesel"
    assert seen["apikey"] == "db-key"


def test_toll_amount_requires_explicit_total_label():
    assert navigation._explicit_toll_amount("Mautkosten: 18,40 EUR für diese Route") == 18.4
    assert navigation._explicit_toll_amount("Vignette ab 11,50 EUR") is None


def test_drive_mcp_lists_tools(client, monkeypatch):
    monkeypatch.setenv("KIES_DRIVE_MCP_TOKEN", "remote-secret")
    response = client.post("/api/navigation/mcp", headers={"Authorization": "Bearer remote-secret"}, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
    })
    assert response.status_code == 200
    names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert {"get_location", "get_active_route", "set_destination", "restore_route"} <= names


def test_drive_mcp_reads_state_and_queues_actions(monkeypatch):
    monkeypatch.setenv("KIES_DRIVE_MCP_TOKEN", "remote-secret")
    db = SessionLocal()
    try:
        device = models.Device(name="Drive Test", token_hash="unused")
        db.add(device); db.flush()
        db.add(models.DriveRemoteState(device_id=device.id, updated_at=datetime.utcnow(), payload={
            "location": {"latitude": 49.0, "longitude": 8.0},
            "recorded_at": "2026-10-04T12:00:00Z", "navigation_active": True,
        }))
        db.commit()
        result = navigation._call_drive_tool(db, "get_location", {})
        assert "49.0" in result["content"][0]["text"]

        result = navigation._call_drive_tool(db, "set_route_options", {"avoid_highways": True})
        assert "accepted" in result["content"][0]["text"]
        command = db.query(models.DriveRemoteCommand).one()
        assert command.device_id == device.id
        assert command.arguments == {"avoid_highways": True}
    finally:
        db.close()


def test_drive_mcp_rejects_wrong_token(client, monkeypatch):
    monkeypatch.setenv("KIES_DRIVE_MCP_TOKEN", "remote-secret")
    response = client.post("/api/navigation/mcp", headers={"Authorization": "Bearer wrong"}, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/list",
    })
    assert response.status_code == 401

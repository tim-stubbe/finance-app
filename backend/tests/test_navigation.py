import pytest
from fastapi import HTTPException

from app.routers import navigation


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
    with pytest.raises(HTTPException) as exc:
        navigation.fuel_stations(49.98, 8.24, 10, "diesel", None, None)
    assert exc.value.status_code == 503

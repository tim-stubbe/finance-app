"""Tests für die native Geräte-Verwaltung (routers/devices.py) - deckt den
Pairing-Flow (Erstellen inkl. Klartext-Token nur einmalig, Auflisten,
Widerrufen) sowie die Auth-Grenzen ab (Web-Session-Auth für die
Verwaltungs-Endpunkte, siehe devices.py-Kopf)."""
from app import crud


def test_create_device_returns_token_once(auth_client):
    resp = auth_client.post("/api/devices", json={"name": "iPhone"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "iPhone"
    assert body["revoked"] is False
    assert "token" in body and len(body["token"]) > 20

    # Nachfolgendes Auflisten enthält keinen Klartext-Token mehr.
    listed = auth_client.get("/api/devices").json()
    assert len(listed) == 1
    assert "token" not in listed[0]
    assert listed[0]["id"] == body["id"]


def test_create_device_requires_name(auth_client):
    resp = auth_client.post("/api/devices", json={"name": "   "})
    assert resp.status_code == 400


def test_revoke_device(auth_client):
    created = auth_client.post("/api/devices", json={"name": "iPad"}).json()
    resp = auth_client.delete(f"/api/devices/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["revoked"] is True

    listed = auth_client.get("/api/devices").json()
    assert listed[0]["revoked"] is True


def test_revoke_unknown_device_404(auth_client):
    resp = auth_client.delete("/api/devices/999999")
    assert resp.status_code == 404


def test_devices_endpoint_requires_web_session(client):
    # Kein Login -> geschützter Endpunkt lehnt ab (siehe main.py: devices_router
    # hängt an dependencies=[Depends(auth.require_auth)]).
    resp = client.get("/api/devices")
    assert resp.status_code in (401, 403)


def test_authenticate_device_rejects_revoked_token(auth_client):
    from app.database import SessionLocal

    created = auth_client.post("/api/devices", json={"name": "Mac"}).json()
    token = created["token"]

    db = SessionLocal()
    try:
        # Vor dem Widerruf funktioniert das Token.
        assert crud.authenticate_device(db, token) is not None
    finally:
        db.close()

    auth_client.delete(f"/api/devices/{created['id']}")

    db = SessionLocal()
    try:
        assert crud.authenticate_device(db, token) is None
    finally:
        db.close()

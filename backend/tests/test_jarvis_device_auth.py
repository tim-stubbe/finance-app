"""Tests für die Device-Token-Auth am `/api/jarvis/chat`-Endpunkt (siehe
auth.require_session_or_device, routers/jarvis.py:jarvis_chat_router).

Deckt beide Auth-Wege (Web-Session, Device-Token) sowie die dazugehörigen
Sicherheitsgrenzen ab: ungültiges/widerrufenes Token, fehlende Auth, kein
Klartext-Token in der DB, sofortige Wirkung eines Widerrufs, und dass die
Agent-Tool-Privacy-Boundary für Device-Requests identisch bleibt wie für
Web-Requests.
"""
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app import models
from app.main import app

from app.auth import DEVICE_TOKEN_HEADER


def _pair_device(auth_client, name="iPhone"):
    resp = auth_client.post("/api/devices", json={"name": name})
    assert resp.status_code == 200
    return resp.json()


def _device_client():
    """Eigener, NICHT eingeloggter Client für Device-Token-Requests.

    `client` und `auth_client` (siehe conftest.py) sind dieselbe TestClient-
    Instanz - `auth_client` loggt `client` nur zusätzlich ein. Für Tests, die
    ausschließlich das Device-Token prüfen wollen (ohne dass eine parallel
    gültige Web-Session das Ergebnis verfälscht), braucht es also einen
    komplett separaten Client ohne Session-Cookie."""
    return TestClient(app, base_url="https://testserver")


def test_chat_with_valid_device_token_allowed(auth_client):
    device = _pair_device(auth_client)

    resp = _device_client().post(
        "/api/jarvis/chat",
        json={"message": "Wie hoch ist mein Kontostand?"},
        headers={DEVICE_TOKEN_HEADER: device["token"]},
    )
    assert resp.status_code == 200


def test_chat_with_invalid_device_token_rejected():
    resp = _device_client().post(
        "/api/jarvis/chat",
        json={"message": "Hallo"},
        headers={DEVICE_TOKEN_HEADER: "irgendein-ungueltiges-token"},
    )
    assert resp.status_code == 401


def test_chat_with_revoked_device_token_rejected(auth_client):
    device = _pair_device(auth_client)
    auth_client.delete(f"/api/devices/{device['id']}")

    resp = _device_client().post(
        "/api/jarvis/chat",
        json={"message": "Hallo"},
        headers={DEVICE_TOKEN_HEADER: device["token"]},
    )
    assert resp.status_code == 401


def test_chat_without_token_and_without_session_rejected():
    resp = _device_client().post("/api/jarvis/chat", json={"message": "Hallo"})
    assert resp.status_code == 401


def test_chat_still_works_with_web_session(auth_client):
    resp = auth_client.post("/api/jarvis/chat", json={"message": "Hallo"})
    assert resp.status_code == 200


def test_device_plaintext_token_never_stored_in_db(auth_client):
    device = _pair_device(auth_client)
    db = SessionLocal()
    try:
        row = db.query(models.Device).get(device["id"])
        assert row.token_hash != device["token"]
        assert device["token"] not in row.token_hash
    finally:
        db.close()


def test_device_last_seen_at_updated_on_chat(auth_client):
    device = _pair_device(auth_client)
    db = SessionLocal()
    try:
        row = db.query(models.Device).get(device["id"])
        assert row.last_seen_at is None
    finally:
        db.close()

    resp = _device_client().post(
        "/api/jarvis/chat",
        json={"message": "Hallo"},
        headers={DEVICE_TOKEN_HEADER: device["token"]},
    )
    assert resp.status_code == 200

    db = SessionLocal()
    try:
        row = db.query(models.Device).get(device["id"])
        assert row.last_seen_at is not None
    finally:
        db.close()


def test_device_revocation_takes_effect_immediately(auth_client):
    device = _pair_device(auth_client)
    device_client = _device_client()

    ok = device_client.post(
        "/api/jarvis/chat",
        json={"message": "Hallo"},
        headers={DEVICE_TOKEN_HEADER: device["token"]},
    )
    assert ok.status_code == 200

    auth_client.delete(f"/api/devices/{device['id']}")

    blocked = device_client.post(
        "/api/jarvis/chat",
        json={"message": "Hallo"},
        headers={DEVICE_TOKEN_HEADER: device["token"]},
    )
    assert blocked.status_code == 401


def test_device_scope_grants_agent_read(auth_client):
    """v1 kennt nur den einen Scope "agent:read" (siehe
    models.AuthenticatedPrincipal.allowed_scopes-Default) - dieser Test
    dokumentiert die Erwartung, damit ein späteres Hinzufügen weiterer Scopes
    (sync:write, notifications, ...) bewusst geschieht statt versehentlich
    alles freizuschalten."""
    from app import models as app_models

    principal = app_models.AuthenticatedPrincipal(auth_method="device")
    assert principal.has_scope("agent:read")
    assert not principal.has_scope("sync:write")


def test_other_jarvis_endpoints_stay_session_only_for_devices(auth_client):
    """Die Auth-Grenze gilt gezielt nur für /jarvis/chat - andere
    Jarvis-Endpunkte hängen weiterhin an der pauschalen Web-Session-Dependency
    (main.py: dependencies=_require_auth für jarvis_router) und lehnen ein
    Device-Token (das kein Session-Cookie ist) wie jeden anderen unangemeldeten
    Zugriff ab."""
    device = _pair_device(auth_client)

    resp = _device_client().get(
        "/api/jarvis/capabilities",
        headers={DEVICE_TOKEN_HEADER: device["token"]},
    )
    assert resp.status_code in (401, 403)

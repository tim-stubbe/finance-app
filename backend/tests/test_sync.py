"""Tests für den nativen Offline-Sync (/api/sync/pull, /api/sync/push) -
Secret-Header-Auth statt Session-Cookie (siehe sync.py-Docstring), Last-
Write-Wins-Konfliktauflösung über updated_at. Category als Test-Entität
gewählt: einfachste im SYNC_REGISTRY (space_scoped=False, keine depends_on-
Abhängigkeit), deckt trotzdem den vollen create/update/pull/conflict-Pfad ab."""
from app import auth, bank_sync
from app.database import SessionLocal

# Rein ASCII halten - HTTP-Header-Werte sind nicht beliebig UTF-8-faehig,
# ein Umlaut hier fuehrte live zu UnicodeEncodeError beim Senden des Headers.
SECRET = "test-sync-secret-fuer-pytest"


def _enable_native_sync():
    db = SessionLocal()
    try:
        s = auth.get_or_create_settings(db)
        s.native_sync_secret_encrypted = bank_sync.encrypt_secret(s.secret_key, SECRET)
        db.commit()
    finally:
        db.close()


def test_pull_without_secret_rejected(client):
    r = client.get("/api/sync/pull")
    assert r.status_code == 403


def test_pull_before_setup_rejected(client):
    """Nativer Sync ist bewusst separat vom Web-Login eingerichtet (eigenes
    Secret) - ohne dieses Secret-Setup muss auch ein korrekt aussehender
    Header nichts nützen."""
    r = client.get("/api/sync/pull", headers={"X-Sync-Secret": "irgendwas"})
    assert r.status_code == 403


def test_pull_wrong_secret_rejected(client):
    _enable_native_sync()
    r = client.get("/api/sync/pull", headers={"X-Sync-Secret": "falsches-secret"})
    assert r.status_code == 403


def test_pull_with_correct_secret_succeeds(client):
    _enable_native_sync()
    r = client.get("/api/sync/pull", headers={"X-Sync-Secret": SECRET})
    assert r.status_code == 200
    body = r.json()
    assert "entities" in body
    assert "Category" in body["entities"]
    assert body["entities"]["Category"] == []


def test_push_create_then_pull_roundtrip(client):
    _enable_native_sync()
    headers = {"X-Sync-Secret": SECRET}
    push_body = {
        "ops": [{
            "op": "create", "entity_type": "Category", "client_id": "tmp-1",
            "data": {"name": "Test-Kategorie", "type": "ausgabe"},
        }],
    }
    r = client.post("/api/sync/push", json=push_body, headers=headers)
    assert r.status_code == 200
    result = r.json()
    assert result["conflicts"] == []
    assert "tmp-1" in result["id_map"]

    r = client.get("/api/sync/pull", headers=headers)
    cats = r.json()["entities"]["Category"]
    assert len(cats) == 1
    assert cats[0]["name"] == "Test-Kategorie"


def test_push_update_stale_base_updated_at_reports_conflict(client):
    """Kernverhalten der Last-Write-Wins-Logik: ein Update mit einem
    base_updated_at, das älter als der aktuelle Server-Stand ist, darf NICHT
    einfach durchgewunken werden, sondern muss als Konflikt zurückkommen."""
    _enable_native_sync()
    headers = {"X-Sync-Secret": SECRET}
    create_body = {
        "ops": [{
            "op": "create", "entity_type": "Category", "client_id": "tmp-1",
            "data": {"name": "Ursprung", "type": "ausgabe"},
        }],
    }
    r = client.post("/api/sync/push", json=create_body, headers=headers)
    server_id = r.json()["id_map"]["tmp-1"]

    # Server-seitig ein zweites Mal aendern, damit updated_at garantiert
    # neuer ist als jeder vom "Client" mitgeschickte base_updated_at.
    update_body = {
        "ops": [{
            "op": "update", "entity_type": "Category", "server_id": server_id,
            "data": {"name": "Server-Version"},
        }],
    }
    r = client.post("/api/sync/push", json=update_body, headers=headers)
    assert r.json()["conflicts"] == []

    # "Client" versucht jetzt mit einem laengst veralteten Zeitstempel zu
    # ueberschreiben.
    stale_update = {
        "ops": [{
            "op": "update", "entity_type": "Category", "server_id": server_id,
            "base_updated_at": "2000-01-01T00:00:00",
            "data": {"name": "Veralteter-Client-Stand"},
        }],
    }
    r = client.post("/api/sync/push", json=stale_update, headers=headers)
    body = r.json()
    assert len(body["conflicts"]) == 1
    assert body["conflicts"][0]["reason"] == "server_newer"

    # Der Server-Stand darf durch den Konflikt nicht ueberschrieben worden sein.
    r = client.get("/api/sync/pull", headers=headers)
    cats = r.json()["entities"]["Category"]
    assert cats[0]["name"] == "Server-Version"


def test_push_unknown_entity_type_reports_conflict(client):
    _enable_native_sync()
    headers = {"X-Sync-Secret": SECRET}
    body = {"ops": [{"op": "create", "entity_type": "GibtEsNicht", "data": {}}]}
    r = client.post("/api/sync/push", json=body, headers=headers)
    assert r.status_code == 200
    assert len(r.json()["conflicts"]) == 1


# --- Universelle Kommandozeile fuer native Clients (Siri-Shortcut) ---
def test_native_command_needs_secret(client):
    _enable_native_sync()
    assert client.post("/api/sync/command", json={"text": "hallo"}).status_code == 403


def test_native_command_routes_via_hub(client, monkeypatch):
    from app import ollama_client, auth as _auth
    _enable_native_sync()
    db = SessionLocal()
    s = _auth.get_or_create_settings(db)
    s.ollama_url = "http://o"; s.ollama_model = "m"
    db.commit(); db.close()
    monkeypatch.setattr(ollama_client, "chat",
                        lambda *a, **k: '{"domain": "todo", "title": "Test-Aufgabe", "due": null, "reply": "Notiert."}')
    r = client.post("/api/sync/command", json={"text": "erinnere mich an Test-Aufgabe"},
                    headers={"X-Sync-Secret": SECRET})
    assert r.status_code == 200
    assert r.json()["domain"] == "todo"

"""Tests für den sicherheitskritischsten Pfad der App: Login, Lockout,
Passwort-Ändern, TOTP-Deaktivieren. Deckt konkret die Fälle ab, die das
`/security-review` (Ultra-Review) und das nächtliche Selbst-Review gefunden
und gefixt haben (siehe ROADMAP/Commit-History) - u.a. das fehlende Lockout
beim Passwort-Ändern und beim TOTP-Deaktivieren, damit ein künftiger Umbau
diese Fixes nicht versehentlich wieder rückgängig macht, ohne dass ein Test
das bemerkt."""
import pyotp

from app import auth
from app.database import SessionLocal
from app import bank_sync


def _setup_account(client, password="Sicheres-Testpasswort-123"):
    r = client.post("/api/auth/setup", json={"password": password})
    assert r.status_code == 200
    assert r.json()["authenticated"] is True
    return password


def test_setup_requires_min_length(client):
    r = client.post("/api/auth/setup", json={"password": "kurz"})
    assert r.status_code == 400


def test_setup_then_status_shows_authenticated(client):
    _setup_account(client)
    r = client.get("/api/auth/status")
    assert r.status_code == 200
    body = r.json()
    assert body["setup_required"] is False
    assert body["authenticated"] is True


def test_setup_twice_rejected(client):
    _setup_account(client)
    r = client.post("/api/auth/setup", json={"password": "Noch-ein-Passwort-456"})
    assert r.status_code == 409


def test_login_wrong_password_fails(client):
    _setup_account(client)
    client.cookies.clear()  # Login von einer "neuen", unauthentifizierten Session aus testen
    r = client.post("/api/auth/login", json={"password": "falsches-passwort"})
    assert r.status_code == 401


def test_login_correct_password_succeeds(client):
    password = _setup_account(client)
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"password": password})
    assert r.status_code == 200
    assert r.json()["authenticated"] is True


def test_login_lockout_after_repeated_failures(client):
    """Kern-Regressionstest für den Login-Lockout (auth.FAILED_LOGIN_THRESHOLD).
    Ohne dieses Verhalten könnte das Passwort per Brute-Force erraten werden."""
    _setup_account(client)
    client.cookies.clear()
    for _ in range(auth.FAILED_LOGIN_THRESHOLD):
        r = client.post("/api/auth/login", json={"password": "falsch"})
        assert r.status_code == 401
    # Der naechste Versuch - selbst mit dem RICHTIGEN Passwort - muss jetzt
    # am Lockout scheitern (429), nicht am Passwort (401).
    r = client.post("/api/auth/login", json={"password": "egal-was"})
    assert r.status_code == 429


def test_change_password_wrong_current_counts_toward_lockout(client):
    """Regressionstest für den Ultra-Review-Fund vom 2026-08 (Commit
    70ffccf): PUT /api/auth/password hatte urspruenglich KEIN Lockout."""
    password = _setup_account(client)
    csrf = client.cookies.get("csrf_token")
    headers = {"X-CSRF-Token": csrf}
    for _ in range(auth.FAILED_LOGIN_THRESHOLD):
        r = client.put(
            "/api/auth/password",
            json={"current_password": "falsch", "new_password": "Ein-Neues-Passwort-789"},
            headers=headers,
        )
        assert r.status_code == 401
    r = client.put(
        "/api/auth/password",
        json={"current_password": password, "new_password": "Ein-Neues-Passwort-789"},
        headers=headers,
    )
    assert r.status_code == 429


def test_change_password_success_resets_lockout_counter(client):
    password = _setup_account(client)
    csrf = client.cookies.get("csrf_token")
    headers = {"X-CSRF-Token": csrf}
    new_password = "Ein-Neues-Passwort-789"
    r = client.put(
        "/api/auth/password",
        json={"current_password": password, "new_password": new_password},
        headers=headers,
    )
    assert r.status_code == 200
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"password": new_password})
    assert r.status_code == 200


def _enable_totp_directly(secret: str = "JBSWY3DPEHPK3PXP"):
    """Setzt TOTP direkt am (einzigen) User (statt über den vollen QR-Setup-
    Flow) - fuer diese Tests zaehlt nur die Lockout-Logik in totp_disable."""
    from app import models
    db = SessionLocal()
    try:
        s = auth.get_or_create_settings(db)
        u = db.query(models.User).first()
        u.totp_enabled = True
        u.totp_secret_encrypted = bank_sync.encrypt_secret(s.secret_key, secret)
        db.commit()
    finally:
        db.close()
    return secret


def test_totp_disable_wrong_code_counts_toward_lockout(client):
    """Regressionstest für den zweiten Ultra-Review-Fund (Confidence 7/10,
    in der Nacht 27./28.08. nachgezogen, siehe crud_routines.py-Nachbar-
    Commit): TOTP-Deaktivieren hatte als einziger Passwort/Code-Endpunkt
    kein Lockout."""
    _setup_account(client)
    secret = _enable_totp_directly()
    headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}
    for _ in range(auth.FAILED_LOGIN_THRESHOLD):
        r = client.request(
            "DELETE", "/api/auth/totp", json={"code": "000000"}, headers=headers,
        )
        assert r.status_code == 401
    # Diesmal mit einem tatsaechlich GUELTIGEN Code - muss trotzdem am
    # Lockout scheitern.
    valid_code = pyotp.TOTP(secret).now()
    r = client.request("DELETE", "/api/auth/totp", json={"code": valid_code}, headers=headers)
    assert r.status_code == 429


def test_totp_disable_valid_code_succeeds(client):
    _setup_account(client)
    secret = _enable_totp_directly()
    headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}
    valid_code = pyotp.TOTP(secret).now()
    r = client.request("DELETE", "/api/auth/totp", json={"code": valid_code}, headers=headers)
    assert r.status_code == 200
    from app import models
    db = SessionLocal()
    try:
        assert db.query(models.User).first().totp_enabled is False
    finally:
        db.close()


def test_protected_endpoint_requires_csrf_header(client):
    """Ohne X-CSRF-Token-Header muss ein mutierender Request auf einem
    geschützten Endpunkt scheitern (Double-Submit-Cookie, siehe
    auth.require_auth) - selbst mit gültiger Session."""
    password = _setup_account(client)
    r = client.put(
        "/api/auth/password",
        json={"current_password": password, "new_password": "Ein-Neues-Passwort-789"},
        # kein X-CSRF-Token-Header
    )
    assert r.status_code == 403


def test_unauthenticated_request_to_protected_endpoint_rejected(client):
    _setup_account(client)
    client.cookies.clear()
    r = client.put(
        "/api/auth/password",
        json={"current_password": "egal", "new_password": "egal-neu-123456"},
        headers={"X-CSRF-Token": "irgendwas"},
    )
    assert r.status_code == 401


def test_setup_stores_display_name(client):
    r = client.post("/api/auth/setup", json={"password": "Sicheres-Passwort-999", "display_name": "Tim"})
    assert r.status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
    prof = client.get("/api/auth/profile").json()
    assert prof["display_name"] == "Tim"


# ---------------- Multi-User (Phase 1) ----------------
PW = "Sehr-langes-Passwort-12"


def _setup(client, name="Tim"):
    r = client.post("/api/auth/setup", json={"password": PW, "display_name": name})
    assert r.status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")


def test_second_user_and_login_by_name(client):
    _setup(client, "Tim")
    r = client.post("/api/auth/users", json={"name": "Mila", "password": PW})
    assert r.status_code == 200
    names = {u["name"] for u in client.get("/api/auth/users").json()}
    assert names == {"Tim", "Mila"}

    # Mit zwei Konten braucht der Login jetzt den Namen
    client.post("/api/auth/logout")
    assert client.get("/api/auth/status").json()["users_count"] == 2
    r = client.post("/api/auth/login", json={"password": PW})           # ohne Name
    assert r.status_code == 400
    r = client.post("/api/auth/login", json={"name": "mila", "password": PW})  # case-insensitiv
    assert r.status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
    assert client.get("/api/auth/profile").json()["display_name"] == "Mila"


def test_cannot_delete_self_or_last_user(client):
    _setup(client, "Tim")
    me = [u for u in client.get("/api/auth/users").json() if u["is_self"]][0]
    assert client.delete(f"/api/auth/users/{me['id']}").status_code == 400  # self
    client.post("/api/auth/users", json={"name": "Mila", "password": PW})
    mila = [u for u in client.get("/api/auth/users").json() if u["name"] == "Mila"][0]
    assert client.delete(f"/api/auth/users/{mila['id']}").status_code == 200
    # jetzt ist Tim der letzte -> von Milas Session aus koennte man ihn loeschen,
    # aber es ist ohnehin nur noch einer uebrig
    assert client.get("/api/auth/users").json().__len__() == 1


def test_duplicate_user_name_rejected(client):
    _setup(client, "Tim")
    assert client.post("/api/auth/users", json={"name": "tim", "password": PW}).status_code == 409

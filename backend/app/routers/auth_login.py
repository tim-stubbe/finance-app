"""Web-Login: Passwort, TOTP (2FA), Passkeys (WebAuthn), Session-Idle-Timeout,
Benutzerverwaltung.

Multi-User (Phase 1, siehe ROADMAP): die Authentifizierung haengt an
`models.User` statt am `Settings`-Singleton. Kein Rollensystem - jeder
angemeldete Nutzer darf weitere Konten anlegen/entfernen (Haushalt).
Datentrennung der Inhalte selbst kommt in spaeteren Phasen; bis dahin
sehen alle Nutzer dieselben Daten.

/api/sync/* (sync.py) und /api/webhook/* (settings_misc.py) bleiben
ausserhalb dieses Logins - eigene Header-Secrets.

WebAuthn: RP-ID/Origin pro Request aus der Adresse abgeleitet
(_rp_id_and_origin); eine reine IP-Adresse funktioniert fuer Passkeys nicht
(Browser-Einschraenkung), dafuer gibt es eine klare Fehlermeldung.
"""

import base64
import io
import json
import secrets
from datetime import datetime

import pyotp
import qrcode
import webauthn
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .. import models, schemas, auth, bank_sync
from ..database import get_db

auth_public_router = APIRouter(prefix="/api/auth")
auth_protected_router = APIRouter(prefix="/api/auth")

MIN_PASSWORD_LENGTH = 10


def _instance_secret_key(db: Session) -> str:
    """TOTP-Secrets werden weiterhin mit dem instanzweiten Fernet-Key
    (Settings.secret_key) ver-/entschluesselt - nicht nutzerspezifisch, nur
    der verschluesselte Wert liegt jetzt am User."""
    return auth.get_or_create_settings(db).secret_key


def _rp_id_and_origin(request: Request) -> tuple[str, str]:
    hostname = request.url.hostname or "localhost"
    if hostname.count(".") == 3 and all(part.isdigit() for part in hostname.split(".")):
        raise HTTPException(
            400,
            "Passkeys funktionieren nicht über eine reine IP-Adresse - bitte Kies über "
            "einen Domainnamen aufrufen (z.B. den Tailscale-MagicDNS-Hostnamen).",
        )
    origin = f"{request.url.scheme}://{hostname}"
    if request.url.port and request.url.port not in (80, 443):
        origin += f":{request.url.port}"
    return hostname, origin


def _qr_data_uri(data: str) -> str:
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _establish_session(request: Request, response: Response, user: models.User) -> None:
    """Nach jedem erfolgreichen Login: Session komplett neu (Session-Fixation-
    Schutz) + frisches CSRF-Token als eigenes, per JS lesbares Cookie."""
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["last_activity"] = datetime.utcnow().isoformat()
    response.set_cookie(
        "csrf_token", auth.new_csrf_token(),
        httponly=False, samesite="lax", max_age=60 * 60 * 24 * 30,
    )


def _active_users(db: Session):
    return db.query(models.User).filter(models.User.is_active.is_(True))


# ---------- Öffentlich (kein Login nötig) ----------

@auth_public_router.get("/status", response_model=schemas.AuthStatusOut)
def auth_status(request: Request, db: Session = Depends(get_db)):
    users_count = _active_users(db).count()
    passkey_count = db.query(models.PasskeyCredential).count()
    me = auth.get_user(db, request.session.get("user_id"))
    return schemas.AuthStatusOut(
        setup_required=users_count == 0,
        authenticated=me is not None,
        totp_required=bool(request.session.get("pending_login")),
        totp_enabled=bool(me.totp_enabled) if me else False,
        passkeys_enabled=passkey_count > 0,
        session_idle_timeout_minutes=(me.session_idle_timeout_minutes if me else 5),
        users_count=users_count,
        display_name=(me.name if me else None),
    )


@auth_public_router.post("/setup", response_model=schemas.LoginOut)
def setup(data: schemas.SetupIn, request: Request, response: Response, db: Session = Depends(get_db)):
    if _active_users(db).count() > 0:
        raise HTTPException(409, "Die Ersteinrichtung ist bereits abgeschlossen.")
    if len(data.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen lang sein.")
    name = (data.display_name or "").strip()[:80] or "Ich"
    user = models.User(
        name=name,
        password_hash=auth.hash_password(data.password),
        password_set_at=datetime.utcnow(),
    )
    db.add(user)
    s = auth.get_or_create_settings(db)
    s.setup_completed_at = datetime.utcnow()
    s.display_name = name  # Rueckwaerts-Kompatibilitaet (Telegram/2FA-Label)
    db.commit()
    db.refresh(user)
    _establish_session(request, response, user)
    return schemas.LoginOut(authenticated=True, totp_required=False)


def _resolve_login_user(db: Session, name) -> models.User:
    if (name or "").strip():
        u = auth.find_user_by_name(db, name)
    else:
        rows = _active_users(db).all()
        u = rows[0] if len(rows) == 1 else None
        if u is None and len(rows) > 1:
            raise HTTPException(400, "Bitte den Namen angeben.")
    if not u or not u.is_active:
        raise HTTPException(401, "Anmeldung fehlgeschlagen.")
    return u


@auth_public_router.post("/login", response_model=schemas.LoginOut)
def login(data: schemas.LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    if _active_users(db).count() == 0:
        raise HTTPException(400, "Ersteinrichtung ist noch nicht abgeschlossen.")
    user = _resolve_login_user(db, data.name)
    auth.check_not_locked_out(user)
    if not auth.verify_password(data.password, user.password_hash):
        auth.register_failed_login(db, user)
        raise HTTPException(401, "Anmeldung fehlgeschlagen.")

    if user.totp_enabled:
        request.session.clear()
        request.session["pending_login"] = True
        request.session["pending_user_id"] = user.id
        request.session["pending_login_at"] = datetime.utcnow().isoformat()
        return schemas.LoginOut(authenticated=False, totp_required=True)

    auth.reset_failed_login(db, user)
    _establish_session(request, response, user)
    return schemas.LoginOut(authenticated=True, totp_required=False)


def _pending_user(request: Request, db: Session) -> models.User:
    if not request.session.get("pending_login"):
        raise HTTPException(401, "Kein ausstehender Login.")
    auth.check_pending_login_fresh(request)
    u = auth.get_user(db, request.session.get("pending_user_id"))
    if not u or not u.is_active:
        request.session.clear()
        raise HTTPException(401, "Anmeldung abgelaufen - bitte erneut anmelden.")
    return u


@auth_public_router.post("/totp/verify", response_model=schemas.LoginOut)
def totp_verify(data: schemas.TotpVerifyIn, request: Request, response: Response, db: Session = Depends(get_db)):
    user = _pending_user(request, db)
    auth.check_not_locked_out(user)
    if not user.totp_enabled or not user.totp_secret_encrypted:
        raise HTTPException(400, "TOTP ist nicht aktiviert.")
    secret = bank_sync.decrypt_secret(_instance_secret_key(db), user.totp_secret_encrypted)
    if not pyotp.TOTP(secret).verify(data.code.strip(), valid_window=1):
        auth.register_failed_login(db, user)
        raise HTTPException(401, "Code ungültig.")
    auth.reset_failed_login(db, user)
    _establish_session(request, response, user)
    return schemas.LoginOut(authenticated=True, totp_required=False)


@auth_public_router.post("/recovery-login", response_model=schemas.LoginOut)
def recovery_login(data: schemas.RecoveryLoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """Alternative zu totp/verify, falls das TOTP-Geraet weg ist - einmaliger
    Wiederherstellungscode, schaltet TOTP fuer diesen Nutzer danach direkt ab."""
    user = _pending_user(request, db)
    auth.check_not_locked_out(user)
    if not user.totp_recovery_code_hash or not auth.verify_recovery_code(
        data.recovery_code.strip(), user.totp_recovery_code_hash
    ):
        auth.register_failed_login(db, user)
        raise HTTPException(401, "Code ungültig.")
    auth.reset_failed_login(db, user)
    user.totp_recovery_code_hash = None
    user.totp_enabled = False
    user.totp_secret_encrypted = None
    user.totp_confirmed_at = None
    db.commit()
    _establish_session(request, response, user)
    return schemas.LoginOut(authenticated=True, totp_required=False)


@auth_public_router.post("/logout")
def logout(request: Request, response: Response):
    request.session.clear()
    response.delete_cookie("csrf_token")
    return {"ok": True}


@auth_public_router.post("/webauthn/login/options", response_model=schemas.WebAuthnOptionsOut)
def webauthn_login_options(request: Request, db: Session = Depends(get_db)):
    rp_id, _ = _rp_id_and_origin(request)
    if db.query(models.PasskeyCredential).count() == 0:
        raise HTTPException(400, "Keine Passkeys registriert.")
    # KEIN allow_credentials -> "usernameless"/auffindbarer Flow: der Browser
    # zeigt ALLE Passkey-Quellen zur Auswahl (Geraet, Bitwarden, Telefon),
    # statt bei einer konkreten Credential-ID mit internal-Transport direkt
    # Touch ID/Windows Hello aufzurufen. Der Passkey traegt seinen Nutzer,
    # verify sucht ihn ueber die zurueckgegebene ID.
    options = webauthn.generate_authentication_options(
        rp_id=rp_id,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    request.session["webauthn_challenge"] = bytes_to_base64url(options.challenge)
    return schemas.WebAuthnOptionsOut(publicKey=json.loads(webauthn.options_to_json(options)))


@auth_public_router.post("/webauthn/login/verify", response_model=schemas.LoginOut)
def webauthn_login_verify(
    data: schemas.WebAuthnCredentialIn, request: Request, response: Response, db: Session = Depends(get_db),
):
    challenge_b64 = request.session.get("webauthn_challenge")
    if not challenge_b64:
        raise HTTPException(400, "Keine ausstehende Passkey-Anmeldung.")
    rp_id, origin = _rp_id_and_origin(request)
    cred = (
        db.query(models.PasskeyCredential)
        .filter(models.PasskeyCredential.credential_id == data.credential.get("id"))
        .first()
    )
    if not cred:
        raise HTTPException(401, "Unbekannter Passkey.")
    try:
        result = webauthn.verify_authentication_response(
            credential=data.credential,
            expected_challenge=base64url_to_bytes(challenge_b64),
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=base64url_to_bytes(cred.public_key),
            credential_current_sign_count=cred.sign_count,
            require_user_verification=True,
        )
    except Exception:
        raise HTTPException(401, "Passkey-Anmeldung fehlgeschlagen.")

    user = auth.get_user(db, cred.user_id)
    if not user:  # Altbestand ohne user_id -> einzigem Nutzer zuordnen
        rows = _active_users(db).all()
        user = rows[0] if len(rows) == 1 else None
    if not user or not user.is_active:
        raise HTTPException(401, "Passkey ist keinem aktiven Konto zugeordnet.")

    request.session.pop("webauthn_challenge", None)
    cred.sign_count = result.new_sign_count
    cred.last_used_at = datetime.utcnow()
    if cred.user_id is None:
        cred.user_id = user.id
    auth.reset_failed_login(db, user)
    db.commit()
    _establish_session(request, response, user)
    # Passkey-Login ist bereits stark (require_user_verification) - kein
    # zusaetzliches TOTP.
    return schemas.LoginOut(authenticated=True, totp_required=False)


# ---------- Geschützt (Login nötig - siehe main.py dependencies=) ----------

@auth_protected_router.put("/password")
def change_password(
    data: schemas.PasswordChangeIn,
    db: Session = Depends(get_db),
    me: models.User = Depends(auth.current_user),
):
    auth.check_not_locked_out(me)
    if not auth.verify_password(data.current_password, me.password_hash):
        auth.register_failed_login(db, me)
        raise HTTPException(401, "Aktuelles Passwort ist falsch.")
    if len(data.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"Neues Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen lang sein.")
    auth.reset_failed_login(db, me)
    me.password_hash = auth.hash_password(data.new_password)
    me.password_set_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@auth_protected_router.post("/totp/setup", response_model=schemas.TotpSetupOut)
def totp_setup(db: Session = Depends(get_db), me: models.User = Depends(auth.current_user)):
    if me.totp_enabled:
        raise HTTPException(409, "TOTP ist bereits aktiv - erst deaktivieren, um es neu einzurichten.")
    secret = pyotp.random_base32()
    me.totp_secret_encrypted = bank_sync.encrypt_secret(_instance_secret_key(db), secret)
    me.totp_confirmed_at = None
    db.commit()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=me.name or "Kies", issuer_name="Kies")
    return schemas.TotpSetupOut(secret=secret, otpauth_uri=uri, qr_code_data_uri=_qr_data_uri(uri))


@auth_protected_router.post("/totp/confirm", response_model=schemas.TotpConfirmOut)
def totp_confirm(data: schemas.TotpConfirmIn, db: Session = Depends(get_db), me: models.User = Depends(auth.current_user)):
    if not me.totp_secret_encrypted:
        raise HTTPException(400, "Kein TOTP-Setup gestartet - erst /totp/setup aufrufen.")
    secret = bank_sync.decrypt_secret(_instance_secret_key(db), me.totp_secret_encrypted)
    if not pyotp.TOTP(secret).verify(data.code.strip(), valid_window=1):
        raise HTTPException(401, "Code ungültig - bitte den aktuellen 6-stelligen Code aus der App eingeben.")
    recovery_code = secrets.token_hex(16)
    me.totp_enabled = True
    me.totp_confirmed_at = datetime.utcnow()
    me.totp_recovery_code_hash = auth.hash_recovery_code(recovery_code)
    db.commit()
    return schemas.TotpConfirmOut(recovery_code=recovery_code)


@auth_protected_router.delete("/totp")
def totp_disable(data: schemas.TotpDisableIn, db: Session = Depends(get_db), me: models.User = Depends(auth.current_user)):
    if not me.totp_enabled:
        raise HTTPException(400, "TOTP ist nicht aktiv.")
    auth.check_not_locked_out(me)
    confirmed = False
    if data.password and auth.verify_password(data.password, me.password_hash):
        confirmed = True
    elif data.code and me.totp_secret_encrypted:
        secret = bank_sync.decrypt_secret(_instance_secret_key(db), me.totp_secret_encrypted)
        confirmed = pyotp.TOTP(secret).verify(data.code.strip(), valid_window=1)
    if not confirmed:
        auth.register_failed_login(db, me)
        raise HTTPException(401, "Bitte Passwort oder aktuellen TOTP-Code zur Bestätigung angeben.")
    auth.reset_failed_login(db, me)
    me.totp_enabled = False
    me.totp_secret_encrypted = None
    me.totp_confirmed_at = None
    me.totp_recovery_code_hash = None
    db.commit()
    return {"ok": True}


@auth_protected_router.post("/webauthn/register/options", response_model=schemas.WebAuthnOptionsOut)
def webauthn_register_options(request: Request, db: Session = Depends(get_db), me: models.User = Depends(auth.current_user)):
    rp_id, _ = _rp_id_and_origin(request)
    mine = db.query(models.PasskeyCredential).filter(models.PasskeyCredential.user_id == me.id).all()
    options = webauthn.generate_registration_options(
        rp_id=rp_id, rp_name="Kies",
        user_id=str(me.id).encode(), user_name=me.name,
        user_display_name=me.name or "Kies",
        authenticator_selection=AuthenticatorSelectionCriteria(
            # REQUIRED erzwingt einen *auffindbaren* (resident) Passkey - nur
            # dann bieten Passwort-Manager (Bitwarden/1Password) sich beim
            # Anlegen ueberhaupt an. authenticator_attachment bewusst NICHT
            # gesetzt -> Geraet UND Roaming-Authenticator erlaubt.
            resident_key=ResidentKeyRequirement.REQUIRED,
            require_resident_key=True,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id)) for c in mine
        ],
    )
    request.session["webauthn_challenge"] = bytes_to_base64url(options.challenge)
    return schemas.WebAuthnOptionsOut(publicKey=json.loads(webauthn.options_to_json(options)))


@auth_protected_router.post("/webauthn/register/verify", response_model=schemas.PasskeyCredentialOut)
def webauthn_register_verify(
    data: schemas.WebAuthnCredentialIn, request: Request,
    db: Session = Depends(get_db), me: models.User = Depends(auth.current_user),
):
    challenge_b64 = request.session.get("webauthn_challenge")
    if not challenge_b64:
        raise HTTPException(400, "Keine ausstehende Passkey-Registrierung.")
    rp_id, origin = _rp_id_and_origin(request)
    try:
        result = webauthn.verify_registration_response(
            credential=data.credential,
            expected_challenge=base64url_to_bytes(challenge_b64),
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_verification=True,
        )
    except Exception as e:
        raise HTTPException(400, f"Passkey-Registrierung fehlgeschlagen: {e}")
    request.session.pop("webauthn_challenge", None)
    transports = (data.credential.get("response") or {}).get("transports") or []
    cred = models.PasskeyCredential(
        user_id=me.id,
        credential_id=bytes_to_base64url(result.credential_id),
        public_key=bytes_to_base64url(result.credential_public_key),
        sign_count=result.sign_count,
        transports=",".join(transports) if transports else None,
        name=data.name or "Passkey",
        created_at=datetime.utcnow(),
    )
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return cred


@auth_protected_router.get("/webauthn/credentials", response_model=list[schemas.PasskeyCredentialOut])
def list_passkeys(db: Session = Depends(get_db), me: models.User = Depends(auth.current_user)):
    return (
        db.query(models.PasskeyCredential)
        .filter(models.PasskeyCredential.user_id == me.id)
        .order_by(models.PasskeyCredential.created_at)
        .all()
    )


@auth_protected_router.delete("/webauthn/credentials/{credential_id}")
def delete_passkey(credential_id: int, db: Session = Depends(get_db), me: models.User = Depends(auth.current_user)):
    cred = (
        db.query(models.PasskeyCredential)
        .filter(models.PasskeyCredential.id == credential_id, models.PasskeyCredential.user_id == me.id)
        .first()
    )
    if not cred:
        raise HTTPException(404, "Nicht gefunden.")
    db.delete(cred)
    db.commit()
    return {"ok": True}


@auth_protected_router.get("/session-timeout", response_model=schemas.SessionTimeoutOut)
def get_session_timeout(me: models.User = Depends(auth.current_user)):
    return schemas.SessionTimeoutOut(session_idle_timeout_minutes=me.session_idle_timeout_minutes)


@auth_protected_router.put("/session-timeout", response_model=schemas.SessionTimeoutOut)
def update_session_timeout(
    data: schemas.SessionTimeoutUpdate, db: Session = Depends(get_db), me: models.User = Depends(auth.current_user),
):
    if not (auth.IDLE_TIMEOUT_MIN_MINUTES <= data.session_idle_timeout_minutes <= auth.IDLE_TIMEOUT_MAX_MINUTES):
        raise HTTPException(
            400, f"Timeout muss zwischen {auth.IDLE_TIMEOUT_MIN_MINUTES} und {auth.IDLE_TIMEOUT_MAX_MINUTES} Minuten liegen.",
        )
    me.session_idle_timeout_minutes = data.session_idle_timeout_minutes
    db.commit()
    return schemas.SessionTimeoutOut(session_idle_timeout_minutes=me.session_idle_timeout_minutes)


# ---------- Benutzerverwaltung (Haushalt - kein Rollensystem) ----------

def _user_out(db: Session, u: models.User, me_id: int) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "is_self": u.id == me_id,
        "totp_enabled": bool(u.totp_enabled),
        "passkey_count": db.query(models.PasskeyCredential).filter(models.PasskeyCredential.user_id == u.id).count(),
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


@auth_protected_router.get("/users")
def list_users(db: Session = Depends(get_db), me: models.User = Depends(auth.current_user)):
    return [_user_out(db, u, me.id) for u in _active_users(db).order_by(models.User.name).all()]


@auth_protected_router.post("/users")
def create_user(data: schemas.UserCreateIn, db: Session = Depends(get_db), me: models.User = Depends(auth.current_user)):
    name = data.name.strip()[:80]
    if not name:
        raise HTTPException(400, "Bitte einen Namen angeben.")
    if len(data.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen lang sein.")
    if auth.find_user_by_name(db, name):
        raise HTTPException(409, "Diesen Namen gibt es schon.")
    u = models.User(name=name, password_hash=auth.hash_password(data.password), password_set_at=datetime.utcnow())
    db.add(u)
    db.commit()
    db.refresh(u)
    return _user_out(db, u, me.id)


@auth_protected_router.patch("/users/{user_id}")
def rename_user(user_id: int, data: schemas.UserRenameIn, db: Session = Depends(get_db), me: models.User = Depends(auth.current_user)):
    u = auth.get_user(db, user_id)
    if not u or not u.is_active:
        raise HTTPException(404, "Nicht gefunden.")
    name = data.name.strip()[:80]
    if not name:
        raise HTTPException(400, "Bitte einen Namen angeben.")
    other = auth.find_user_by_name(db, name)
    if other and other.id != u.id:
        raise HTTPException(409, "Diesen Namen gibt es schon.")
    u.name = name
    if u.id == 1:
        auth.get_or_create_settings(db).display_name = name
    db.commit()
    return _user_out(db, u, me.id)


@auth_protected_router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), me: models.User = Depends(auth.current_user)):
    if user_id == me.id:
        raise HTTPException(400, "Das eigene Konto kann nicht hier entfernt werden.")
    u = auth.get_user(db, user_id)
    if not u or not u.is_active:
        raise HTTPException(404, "Nicht gefunden.")
    if _active_users(db).count() <= 1:
        raise HTTPException(400, "Das letzte Konto kann nicht entfernt werden.")
    db.query(models.PasskeyCredential).filter(models.PasskeyCredential.user_id == u.id).delete()
    db.delete(u)
    db.commit()
    return {"ok": True}

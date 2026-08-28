"""Web-Login: Passwort, TOTP (2FA), Passkeys (WebAuthn), Session-Idle-Timeout.

Ersetzt die bisherige "keine Anmeldung" (siehe README.md/SECURITY.md
"Zugriffsschutz", jetzt angepasst) - bleibt Single-User (kein User-Model,
kein Rollensystem, keine Registrierung für Dritte), aber jeder Zugriff auf
Finanzdaten braucht jetzt eine gültige Session. /api/sync/* (sync.py) und
/api/webhook/* (settings_misc.py) bleiben bewusst außen vor - eigene
Header-Secrets, kein Browser-Login dahinter (native Clients bzw. n8n).

Zwei Router statt einem, weil dieselbe main.py-`dependencies=[Depends(
auth.require_auth)]`-Absicherung (siehe main.py) nur pro ganzem Router
greift, hier aber öffentliche (Status/Setup/Login/TOTP-Verify/Logout/
Passkey-Login) und geschützte Endpunkte (TOTP-Setup/Passkey-Verwaltung/
Session-Timeout-Einstellung) im selben fachlichen Bereich gemischt sind -
genau dasselbe Muster wie der Split von settings_misc_router weiter unten
in dieser Datei für den n8n-Webhook.

WebAuthn: RP-ID/Origin werden PRO REQUEST aus der aufgerufenen Adresse
abgeleitet (_rp_id_and_origin), nicht fest hinterlegt - Kies läuft je nach
Umgebung über einen LAN-Hostnamen oder ein Tailscale-MagicDNS-Ziel. Eine
reine IP-Adresse (z.B. 100.72.226.91 direkt statt über einen Tailscale-
Namen) funktioniert für Passkeys grundsätzlich NICHT - das ist eine
Browser-seitige WebAuthn-Einschränkung (RP-ID muss eine valide Domain
sein), kein Kies-Bug. _rp_id_and_origin gibt in dem Fall eine klare
deutsche Fehlermeldung statt eines kryptischen WebAuthn-Fehlers zurück."""

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

# Fester, stabiler "Nutzer" fürs WebAuthn-Handshake-Protokoll (verlangt eine
# user_id/user_name) - Single-User, kein echtes Konto-System dahinter, ein
# fixer Wert reicht und muss über alle Registrierungen hinweg gleich bleiben.
_WEBAUTHN_USER_ID = b"kies-single-user"
_WEBAUTHN_USER_NAME = "kies"

MIN_PASSWORD_LENGTH = 10


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


def _establish_session(request: Request, response: Response) -> None:
    """Läuft nach jedem erfolgreichen Login (Passwort(+TOTP) oder Passkey) -
    Session komplett neu aufsetzen (verhindert Session Fixation: eine vor
    dem Login evtl. schon bestehende Session-ID wird nicht einfach
    "hochgestuft") und ein frisches CSRF-Token als eigenes, per JS lesbares
    Cookie setzen (Double-Submit, siehe auth.require_auth)."""
    request.session.clear()
    request.session["authenticated"] = True
    request.session["last_activity"] = datetime.utcnow().isoformat()
    response.set_cookie(
        "csrf_token", auth.new_csrf_token(),
        httponly=False, samesite="lax", max_age=60 * 60 * 24 * 30,
    )


# ---------- Öffentlich (kein Login nötig) ----------

@auth_public_router.get("/status", response_model=schemas.AuthStatusOut)
def auth_status(request: Request, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    passkey_count = db.query(models.PasskeyCredential).count()
    return schemas.AuthStatusOut(
        setup_required=not s.password_hash,
        authenticated=bool(request.session.get("authenticated")),
        totp_required=bool(request.session.get("pending_login")),
        totp_enabled=s.totp_enabled,
        passkeys_enabled=passkey_count > 0,
        session_idle_timeout_minutes=s.session_idle_timeout_minutes,
    )


@auth_public_router.post("/setup", response_model=schemas.LoginOut)
def setup(data: schemas.SetupIn, request: Request, response: Response, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    if s.password_hash:
        raise HTTPException(409, "Die Ersteinrichtung ist bereits abgeschlossen.")
    if len(data.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen lang sein.")
    s.password_hash = auth.hash_password(data.password)
    s.password_set_at = datetime.utcnow()
    s.setup_completed_at = datetime.utcnow()
    if (data.display_name or "").strip():
        s.display_name = data.display_name.strip()[:80]
    db.commit()
    _establish_session(request, response)
    return schemas.LoginOut(authenticated=True, totp_required=False)


@auth_public_router.post("/login", response_model=schemas.LoginOut)
def login(data: schemas.LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    if not s.password_hash:
        raise HTTPException(400, "Ersteinrichtung ist noch nicht abgeschlossen.")
    auth.check_not_locked_out(s)
    # Generische Fehlermeldung (kein "falsches Passwort" vs. "Setup fehlt") -
    # es gibt ohnehin nur ein Konto, mehr Detail hilft nur einem Angreifer.
    if not auth.verify_password(data.password, s.password_hash):
        auth.register_failed_login(db, s)
        raise HTTPException(401, "Anmeldung fehlgeschlagen.")

    if s.totp_enabled:
        request.session.clear()
        request.session["pending_login"] = True
        # Zeitstempel für das Zeitfenster in auth.check_pending_login_fresh -
        # ohne den bliebe pending_login unbegrenzt gültig, siehe dort.
        request.session["pending_login_at"] = datetime.utcnow().isoformat()
        return schemas.LoginOut(authenticated=False, totp_required=True)

    auth.reset_failed_login(db, s)
    _establish_session(request, response)
    return schemas.LoginOut(authenticated=True, totp_required=False)


@auth_public_router.post("/totp/verify", response_model=schemas.LoginOut)
def totp_verify(data: schemas.TotpVerifyIn, request: Request, response: Response, db: Session = Depends(get_db)):
    if not request.session.get("pending_login"):
        raise HTTPException(401, "Kein ausstehender Login.")
    auth.check_pending_login_fresh(request)
    s = auth.get_or_create_settings(db)
    auth.check_not_locked_out(s)
    if not s.totp_enabled or not s.totp_secret_encrypted:
        raise HTTPException(400, "TOTP ist nicht aktiviert.")
    secret = bank_sync.decrypt_secret(s.secret_key, s.totp_secret_encrypted)
    if not pyotp.TOTP(secret).verify(data.code.strip(), valid_window=1):
        auth.register_failed_login(db, s)
        raise HTTPException(401, "Code ungültig.")
    auth.reset_failed_login(db, s)
    _establish_session(request, response)
    return schemas.LoginOut(authenticated=True, totp_required=False)


@auth_public_router.post("/recovery-login", response_model=schemas.LoginOut)
def recovery_login(data: schemas.RecoveryLoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """Alternative zu totp/verify, falls das TOTP-Geraet nicht mehr da ist -
    verlangt den einmaligen Wiederherstellungscode (siehe totp_confirm) und
    schaltet TOTP danach direkt ab, siehe Docstring-Begruendung unten."""
    if not request.session.get("pending_login"):
        raise HTTPException(401, "Kein ausstehender Login.")
    auth.check_pending_login_fresh(request)
    s = auth.get_or_create_settings(db)
    auth.check_not_locked_out(s)
    if not s.totp_recovery_code_hash or not auth.verify_recovery_code(data.recovery_code.strip(), s.totp_recovery_code_hash):
        auth.register_failed_login(db, s)
        raise HTTPException(401, "Code ungültig.")
    auth.reset_failed_login(db, s)
    # Einmal-Code ist verbraucht UND schaltet TOTP direkt ab - das verlorene
    # Gerät ist damit nicht mehr im Spiel, TOTP ließe sich sonst ohne Zugriff
    # auf einen gültigen Code nie wieder aktivieren/deaktivieren.
    s.totp_recovery_code_hash = None
    s.totp_enabled = False
    s.totp_secret_encrypted = None
    s.totp_confirmed_at = None
    db.commit()
    _establish_session(request, response)
    return schemas.LoginOut(authenticated=True, totp_required=False)


@auth_public_router.post("/logout")
def logout(request: Request, response: Response):
    request.session.clear()
    response.delete_cookie("csrf_token")
    return {"ok": True}


@auth_public_router.post("/webauthn/login/options", response_model=schemas.WebAuthnOptionsOut)
def webauthn_login_options(request: Request, db: Session = Depends(get_db)):
    rp_id, _ = _rp_id_and_origin(request)
    creds = db.query(models.PasskeyCredential).all()
    if not creds:
        raise HTTPException(400, "Keine Passkeys registriert.")
    # KEIN allow_credentials: das macht die Anmeldung "usernameless" /
    # auffindbar - der Browser zeigt dann ALLE verfuegbaren Passkey-Quellen
    # zur Auswahl (Geraet, Bitwarden, Telefon), statt bei einer konkreten
    # Credential-ID mit internal-Transport direkt Touch ID/Windows Hello
    # aufzurufen (so machen es auch Google/Amazon). verify_authentication_
    # response sucht den Passkey ohnehin ueber die zurueckgegebene ID.
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
    credential_id_raw = data.credential.get("id")
    cred = db.query(models.PasskeyCredential).filter(models.PasskeyCredential.credential_id == credential_id_raw).first()
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
    request.session.pop("webauthn_challenge", None)
    cred.sign_count = result.new_sign_count
    cred.last_used_at = datetime.utcnow()
    # Ein Passkey-Login ist bereits starke, geräte-/nutzerverifizierte
    # Authentifizierung (require_user_verification=True oben) - verlangt
    # bewusst KEIN zusätzliches TOTP mehr, anders als beim Passwort-Login.
    s = auth.get_or_create_settings(db)
    auth.reset_failed_login(db, s)
    db.commit()
    _establish_session(request, response)
    return schemas.LoginOut(authenticated=True, totp_required=False)


# ---------- Geschützt (Login nötig - siehe main.py dependencies=) ----------

@auth_protected_router.put("/password")
def change_password(data: schemas.PasswordChangeIn, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    # Gleiches Lockout wie bei login/totp_verify/recovery_login (Sicherheits-
    # pruefung: hier fehlte es bisher) - eine gestohlene, bereits angemeldete
    # Session ohne Kenntnis des Passworts koennte sonst current_password
    # unbegrenzt durchprobieren und danach dauerhaft uebernehmen.
    auth.check_not_locked_out(s)
    if not s.password_hash or not auth.verify_password(data.current_password, s.password_hash):
        auth.register_failed_login(db, s)
        raise HTTPException(401, "Aktuelles Passwort ist falsch.")
    if len(data.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"Neues Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen lang sein.")
    auth.reset_failed_login(db, s)
    s.password_hash = auth.hash_password(data.new_password)
    s.password_set_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@auth_protected_router.post("/totp/setup", response_model=schemas.TotpSetupOut)
def totp_setup(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    if s.totp_enabled:
        raise HTTPException(409, "TOTP ist bereits aktiv - erst deaktivieren, um es neu einzurichten.")
    secret = pyotp.random_base32()
    s.totp_secret_encrypted = bank_sync.encrypt_secret(s.secret_key, secret)
    s.totp_confirmed_at = None
    db.commit()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=s.display_name or "Kies", issuer_name="Kies")
    return schemas.TotpSetupOut(secret=secret, otpauth_uri=uri, qr_code_data_uri=_qr_data_uri(uri))


@auth_protected_router.post("/totp/confirm", response_model=schemas.TotpConfirmOut)
def totp_confirm(data: schemas.TotpConfirmIn, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    if not s.totp_secret_encrypted:
        raise HTTPException(400, "Kein TOTP-Setup gestartet - erst /totp/setup aufrufen.")
    secret = bank_sync.decrypt_secret(s.secret_key, s.totp_secret_encrypted)
    if not pyotp.TOTP(secret).verify(data.code.strip(), valid_window=1):
        raise HTTPException(401, "Code ungültig - bitte den aktuellen 6-stelligen Code aus der App eingeben.")
    recovery_code = secrets.token_hex(16)
    s.totp_enabled = True
    s.totp_confirmed_at = datetime.utcnow()
    s.totp_recovery_code_hash = auth.hash_recovery_code(recovery_code)
    db.commit()
    return schemas.TotpConfirmOut(recovery_code=recovery_code)


@auth_protected_router.delete("/totp")
def totp_disable(data: schemas.TotpDisableIn, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    if not s.totp_enabled:
        raise HTTPException(400, "TOTP ist nicht aktiv.")
    # Gleiches Lockout wie bei login/totp_verify/recovery_login/change_password
    # (Sicherheits-Review: fehlte hier bisher als einzigem Endpunkt, der
    # Passwort ODER TOTP-Code prüft) - eine gestohlene, bereits angemeldete
    # Session ohne Kenntnis von Passwort/Code könnte sonst unbegrenzt raten,
    # um 2FA zu entfernen.
    auth.check_not_locked_out(s)
    confirmed = False
    if data.password and s.password_hash and auth.verify_password(data.password, s.password_hash):
        confirmed = True
    elif data.code and s.totp_secret_encrypted:
        secret = bank_sync.decrypt_secret(s.secret_key, s.totp_secret_encrypted)
        confirmed = pyotp.TOTP(secret).verify(data.code.strip(), valid_window=1)
    if not confirmed:
        auth.register_failed_login(db, s)
        raise HTTPException(401, "Bitte Passwort oder aktuellen TOTP-Code zur Bestätigung angeben.")
    auth.reset_failed_login(db, s)
    s.totp_enabled = False
    s.totp_secret_encrypted = None
    s.totp_confirmed_at = None
    s.totp_recovery_code_hash = None
    db.commit()
    return {"ok": True}


@auth_protected_router.post("/webauthn/register/options", response_model=schemas.WebAuthnOptionsOut)
def webauthn_register_options(request: Request, db: Session = Depends(get_db)):
    rp_id, _ = _rp_id_and_origin(request)
    s = auth.get_or_create_settings(db)
    existing = db.query(models.PasskeyCredential).all()
    options = webauthn.generate_registration_options(
        rp_id=rp_id, rp_name="Kies", user_id=_WEBAUTHN_USER_ID, user_name=_WEBAUTHN_USER_NAME,
        user_display_name=s.display_name or "Kies",
        authenticator_selection=AuthenticatorSelectionCriteria(
            # REQUIRED (statt PREFERRED): erzwingt einen *auffindbaren*
            # (resident) Passkey. Nur dann bieten Passwort-Manager wie
            # Bitwarden/1Password sich beim Anlegen ueberhaupt an - ein
            # nicht-auffindbarer Passkey kann nur auf dem Geraet selbst
            # liegen, weshalb Chrome direkt Touch ID/Windows Hello nimmt.
            resident_key=ResidentKeyRequirement.REQUIRED,
            require_resident_key=True,
            # authenticator_attachment bewusst NICHT gesetzt -> Plattform-
            # (Geraet) UND Roaming-Authenticator (Bitwarden, Phone, Yubikey)
            # sind erlaubt.
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id)) for c in existing
        ],
    )
    request.session["webauthn_challenge"] = bytes_to_base64url(options.challenge)
    return schemas.WebAuthnOptionsOut(publicKey=json.loads(webauthn.options_to_json(options)))


@auth_protected_router.post("/webauthn/register/verify", response_model=schemas.PasskeyCredentialOut)
def webauthn_register_verify(data: schemas.WebAuthnCredentialIn, request: Request, db: Session = Depends(get_db)):
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
def list_passkeys(db: Session = Depends(get_db)):
    return db.query(models.PasskeyCredential).order_by(models.PasskeyCredential.created_at).all()


@auth_protected_router.delete("/webauthn/credentials/{credential_id}")
def delete_passkey(credential_id: int, db: Session = Depends(get_db)):
    cred = db.query(models.PasskeyCredential).filter(models.PasskeyCredential.id == credential_id).first()
    if not cred:
        raise HTTPException(404, "Nicht gefunden.")
    db.delete(cred)
    db.commit()
    return {"ok": True}


@auth_protected_router.get("/session-timeout", response_model=schemas.SessionTimeoutOut)
def get_session_timeout(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    return schemas.SessionTimeoutOut(session_idle_timeout_minutes=s.session_idle_timeout_minutes)


@auth_protected_router.put("/session-timeout", response_model=schemas.SessionTimeoutOut)
def update_session_timeout(data: schemas.SessionTimeoutUpdate, db: Session = Depends(get_db)):
    if not (auth.IDLE_TIMEOUT_MIN_MINUTES <= data.session_idle_timeout_minutes <= auth.IDLE_TIMEOUT_MAX_MINUTES):
        raise HTTPException(
            400, f"Timeout muss zwischen {auth.IDLE_TIMEOUT_MIN_MINUTES} und {auth.IDLE_TIMEOUT_MAX_MINUTES} Minuten liegen.",
        )
    s = auth.get_or_create_settings(db)
    s.session_idle_timeout_minutes = data.session_idle_timeout_minutes
    db.commit()
    return schemas.SessionTimeoutOut(session_idle_timeout_minutes=s.session_idle_timeout_minutes)

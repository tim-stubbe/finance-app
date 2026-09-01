import os
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Request
from passlib.context import CryptContext
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models
from .database import get_db


# ---------- Benutzer (Multi-User, siehe models.User) ----------
def get_user(db: Session, user_id) -> "models.User | None":
    if not user_id:
        return None
    return db.query(models.User).filter(models.User.id == user_id).first()


def find_user_by_name(db: Session, name: str) -> "models.User | None":
    if not name or not name.strip():
        return None
    return (
        db.query(models.User)
        .filter(func.lower(models.User.name) == name.strip().lower())
        .first()
    )


def current_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    """Dependency fuer geschuetzte Endpunkte, die den angemeldeten Nutzer
    brauchen (Passwort aendern, TOTP, Passkeys, Benutzerverwaltung)."""
    u = get_user(db, request.session.get("user_id"))
    if not u or not u.is_active:
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")
    return u


def get_or_create_settings(db: Session) -> models.Settings:
    settings = db.query(models.Settings).filter(models.Settings.id == 1).first()
    if not settings:
        settings = models.Settings(id=1, secret_key=secrets.token_hex(32))
        db.add(settings)
        db.commit()
        db.refresh(settings)
    # Container-weiter Override: ist KIES_OLLAMA_MODEL in der Env gesetzt, gilt
    # DIESES Modell fuer alles (proaktiver Assistent, Jarvis, Steuer-Q&A, Haus,
    # Hub) - unabhaengig davon, was im UI/DB steht. Nur im Speicher, wird nicht
    # zurueckgeschrieben.
    _env_model = os.environ.get("KIES_OLLAMA_MODEL")
    if _env_model and settings.ollama_model != _env_model:
        settings.ollama_model = _env_model
    return settings


def get_active_space_id(request: Request, db: Session = Depends(get_db)) -> int:
    # Multi-User Phase 2: nur Bereiche berücksichtigen, die dem angemeldeten
    # Nutzer gehören (owner_id == user.id) oder noch nicht migriert sind
    # (owner_id NULL). So kann die Session nie auf einen fremden Bereich
    # zeigen und der Auto-Pick unten wählt keinen fremden aus.
    user = get_user(db, request.session.get("user_id"))
    owned_q = db.query(models.Space)
    if user is not None:
        owned_q = owned_q.filter(
            (models.Space.owner_id == user.id) | (models.Space.owner_id.is_(None))
        )
    space_id = request.session.get("space_id")
    if space_id:
        if owned_q.filter(models.Space.id == space_id).first() is not None:
            return space_id
        # Session zeigt auf einen Bereich, der dem Nutzer nicht (mehr) gehört.
        request.session.pop("space_id", None)
        space_id = None
    # Gibt es genau einen (eigenen) Bereich, automatisch übernehmen statt eine
    # Bereichsauswahl anzuzeigen - die App hat keine UI mehr dafür. Bei mehreren
    # bleibt die alte Fehlermeldung als Sicherheitsnetz bestehen.
    spaces = owned_q.all()
    if len(spaces) == 1:
        space_id = spaces[0].id
        request.session["space_id"] = space_id
        return space_id
    raise HTTPException(status_code=400, detail="Kein Bereich ausgewählt")


# ---------- Web-Login (Passwort/TOTP/Passkeys) ----------
# Alles hier neu (siehe ROADMAP.md) - ersetzt die bisherige "keine Anmeldung"
# (README/SECURITY.md "Zugriffsschutz", jetzt angepasst). Bleibt Single-User:
# kein User-Model, kein Rollensystem - "eingeloggt" heißt schlicht "kennt das
# eine Passwort dieser Instanz".
#
# Argon2id über passlib statt selbst gebaut - siehe requirements.txt
# (passlib[argon2]). Geprüft, dass argon2-cffi-bindings ein fertiges
# manylinux-Wheel (cp36-abi3, funktioniert auf jeder neueren Python-Version
# inkl. der hier verwendeten 3.14) mitbringt, kein Compiler im schlanken
# Docker-Image nötig.
_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(password, password_hash)
    except ValueError:
        # Kaputter/leerer Hash (sollte nicht vorkommen) - als falsch werten
        # statt eine 500 zu werfen, ein Login-Fehlversuch ist die richtige
        # Reaktion, kein Serverfehler.
        return False


def hash_recovery_code(code: str) -> str:
    # Selbe Hash-Funktion wie fuers Passwort - ein Recovery-Code ist im Kern
    # auch nur ein (einmaliges) Passwort.
    return _pwd_context.hash(code)


def verify_recovery_code(code: str, code_hash: str) -> bool:
    return verify_password(code, code_hash)


# ---------- Brute-Force-Bremse ----------
# Passwort UND TOTP-Code teilen sich denselben Zähler (models.Settings.
# failed_login_count) - beides ist "ein Versuch, sich anzumelden", eine
# Trennung würde nur unnötige Komplexität bringen (Single-User, kein
# Multi-Account-Szenario, in dem man das pro Nutzer unterscheiden müsste).
# Progressive Sperre statt fester Wartezeit: je mehr Fehlversuche, desto
# länger die Sperre (Exponential, gedeckelt), macht automatisiertes Raten
# zunehmend unattraktiv, ohne einen einzelnen Tippfehler tagelang zu bestrafen.
FAILED_LOGIN_THRESHOLD = 5
LOCKOUT_BASE_SECONDS = 30
LOCKOUT_MAX_SECONDS = 15 * 60


def check_not_locked_out(settings: models.Settings) -> None:
    if settings.failed_login_locked_until and settings.failed_login_locked_until > datetime.utcnow():
        # Bewusst keine genaue Restzeit verraten - "versuch's gleich nochmal"
        # ist informativ genug, ohne einem Angreifer ein exaktes Zeitfenster
        # zum Nachjustieren zu liefern.
        raise HTTPException(429, "Zu viele Fehlversuche. Bitte in ein paar Minuten erneut versuchen.")


def register_failed_login(db: Session, settings: models.Settings) -> None:
    settings.failed_login_count += 1
    if settings.failed_login_count >= FAILED_LOGIN_THRESHOLD:
        backoff = min(
            LOCKOUT_MAX_SECONDS,
            LOCKOUT_BASE_SECONDS * (2 ** (settings.failed_login_count - FAILED_LOGIN_THRESHOLD)),
        )
        settings.failed_login_locked_until = datetime.utcnow() + timedelta(seconds=backoff)
    db.commit()


def reset_failed_login(db: Session, settings: models.Settings) -> None:
    if settings.failed_login_count or settings.failed_login_locked_until:
        settings.failed_login_count = 0
        settings.failed_login_locked_until = None
        db.commit()


# Zeitfenster für den Zwischenzustand "Passwort war richtig, TOTP-Code steht
# noch aus" (request.session["pending_login"], siehe routers/auth_login.py).
# Ohne dieses Fenster bliebe pending_login unbegrenzt in der Session stehen -
# ein gestohlenes/mitgelesenes Session-Cookie aus GENAU diesem Zwischenschritt
# hätte sonst zeitlich unbegrenzt Zeit, den TOTP-Code zu erraten (die
# eigentliche Bruteforce-Bremse ist check_not_locked_out, dieses Fenster ist
# eine zusätzliche, unabhängige Absicherung).
PENDING_LOGIN_MAX_MINUTES = 5


def check_pending_login_fresh(request: Request) -> None:
    """Wirft 401, wenn pending_login zu alt ist oder gar keinen Zeitstempel
    hat (z.B. eine Session von vor diesem Feature) - räumt die Session in
    beiden Fällen auf, damit ein erneuter /login-Versuch sauber startet."""
    started_raw = request.session.get("pending_login_at")
    started = datetime.fromisoformat(started_raw) if started_raw else None
    if not started or datetime.utcnow() - started > timedelta(minutes=PENDING_LOGIN_MAX_MINUTES):
        request.session.clear()
        raise HTTPException(401, "Anmeldung abgelaufen - bitte Passwort erneut eingeben.")


# ---------- Session-Gate für alle geschützten Routen ----------
# Statt einer globalen Middleware wird das hier als FastAPI-Dependency pro
# Router am Einbinde-Ort in main.py angehängt (`app.include_router(x,
# dependencies=[Depends(require_auth)])`) - erreicht dieselbe lückenlose
# Abdeckung, ist aber pro Router explizit sichtbar (main.py-Diff zeigt exakt,
# welche Router geschützt sind), statt sich auf String-Pfad-Vergleiche in
# einer Middleware zu verlassen. /api/sync/* und /api/webhook/* bleiben
# bewusst ausgenommen (eigene Header-Secrets, siehe sync.py/settings_misc.py)
# und laufen NICHT über diese Dependency.
IDLE_TIMEOUT_MIN_MINUTES = 1
IDLE_TIMEOUT_MAX_MINUTES = 1440  # 24h - "prakisch nie" ohne den Timeout ganz abzuschaffen


def require_auth(request: Request, db: Session = Depends(get_db)) -> None:
    user = get_user(db, request.session.get("user_id"))
    if not user or not user.is_active:
        request.session.pop("user_id", None)
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")

    timeout_minutes = user.session_idle_timeout_minutes or 5
    last_activity_raw = request.session.get("last_activity")
    if last_activity_raw:
        last_activity = datetime.fromisoformat(last_activity_raw)
        if datetime.utcnow() - last_activity > timedelta(minutes=timeout_minutes):
            request.session.clear()
            raise HTTPException(status_code=401, detail="Sitzung wegen Inaktivität abgelaufen. Bitte erneut anmelden.")

    # CSRF (Double-Submit-Cookie): SameSite=Lax deckt die Cross-Site-Fetch-
    # Fälle schon weitgehend ab (der Browser sendet den Cookie dabei gar
    # nicht erst mit), das hier ist zusätzliche Tiefenverteidigung für
    # zustandsändernde Requests, wie im Auftrag verlangt. Der Token wird beim
    # Login gesetzt (siehe routers/auth_login.py), das Frontend spiegelt ihn
    # bei jedem mutierenden Aufruf in den Header zurück (siehe frontend/js/
    # core.js:api()) - ein Angreifer, der den Cookie nicht per JS auslesen
    # kann (anderer Origin), kann den Header nicht korrekt setzen.
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        cookie_token = request.cookies.get("csrf_token")
        header_token = request.headers.get("x-csrf-token")
        if not cookie_token or not header_token or not secrets.compare_digest(cookie_token, header_token):
            raise HTTPException(status_code=403, detail="Ungültiges CSRF-Token.")

    request.session["last_activity"] = datetime.utcnow().isoformat()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)

"""Benachrichtigungs-/Verbindungs-Settings: Telegram, Twilio (Anrufe),
Radicale (To-Dos), Fahrzeit-Einstellungen (Heimadresse fuer Reisezeit-
Berechnung).

Zweiundzwanzigster Schritt der Code-Modularisierung (siehe ROADMAP.md),
nach investments/tax/debts/goals/trips/wishlist/personal/business_life/
budgets_alerts/deadlines/calendar_todos/categories/immich_routes/
bank_connections/enablebanking_ebay/mail_routes/spaces_accounts/
backup_restore/export_import/analytics/settings_misc. Vier verwandte
Test-Verbindung-Domaenen (jeweils Settings speichern + Testendpunkt),
standen im selben main.py-Abschnitt. Reine Verschiebung ohne
Verhaltensaenderung."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from typing import List

from .. import schemas, auth, bank_sync, notifications, calls, radicale_sync, travel_time, models, proactive
from ..database import get_db

notify_settings_router = APIRouter(prefix="/api")


# ---------------- Benachrichtigungen (Telegram) ----------------
def _notification_settings_out(s) -> schemas.NotificationSettingsOut:
    return schemas.NotificationSettingsOut(
        enabled=s.notifications_enabled,
        telegram_configured=bool(s.telegram_bot_token_encrypted and s.telegram_chat_id),
        proactive_assistant_enabled=bool(s.proactive_assistant_enabled),
        ntfy_enabled=bool(s.ntfy_enabled),
        ntfy_url=s.ntfy_url or "https://ntfy.sh",
        ntfy_topic=s.ntfy_topic,
    )


@notify_settings_router.get("/settings/notifications", response_model=schemas.NotificationSettingsOut)
def get_notification_settings(db: Session = Depends(get_db)):
    return _notification_settings_out(auth.get_or_create_settings(db))


@notify_settings_router.put("/settings/notifications", response_model=schemas.NotificationSettingsOut)
def update_notification_settings(data: schemas.NotificationSettingsUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.notifications_enabled = data.enabled
    if data.telegram_bot_token:
        settings.telegram_bot_token_encrypted = bank_sync.encrypt_secret(settings.secret_key, data.telegram_bot_token)
    if data.telegram_chat_id:
        settings.telegram_chat_id = data.telegram_chat_id.strip()
    if data.proactive_assistant_enabled is not None:
        settings.proactive_assistant_enabled = data.proactive_assistant_enabled
    if data.ntfy_enabled is not None:
        settings.ntfy_enabled = data.ntfy_enabled
    if data.ntfy_url is not None:
        settings.ntfy_url = data.ntfy_url.strip() or "https://ntfy.sh"
    if data.ntfy_topic is not None:
        settings.ntfy_topic = data.ntfy_topic.strip() or None
    db.commit()
    return _notification_settings_out(settings)


@notify_settings_router.post("/notifications/test-ntfy", response_model=schemas.NotificationTestResult)
def send_test_ntfy(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    if not (settings.ntfy_enabled and settings.ntfy_topic):
        return schemas.NotificationTestResult(ok=False, message="ntfy zuerst aktivieren und ein Thema (Topic) angeben.")
    try:
        notifications.send_ntfy(settings.ntfy_url or "https://ntfy.sh", settings.ntfy_topic,
                                "Testalarm von Kies – so klingelt es bei einer dringenden Meldung.", urgent=True)
    except Exception as e:  # noqa: BLE001
        return schemas.NotificationTestResult(ok=False, message=f"Fehlgeschlagen: {e}")
    return schemas.NotificationTestResult(ok=True, message="Gesendet – dein Handy sollte laut klingeln.")


@notify_settings_router.delete("/settings/notifications/telegram", response_model=schemas.NotificationSettingsOut)
def remove_telegram_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.telegram_bot_token_encrypted = None
    settings.telegram_chat_id = None
    db.commit()
    return schemas.NotificationSettingsOut(enabled=settings.notifications_enabled, telegram_configured=False)


@notify_settings_router.post("/notifications/test", response_model=schemas.NotificationTestResult)
def send_test_notification(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    if not settings.telegram_bot_token_encrypted or not settings.telegram_chat_id:
        return schemas.NotificationTestResult(ok=False, message="Bot-Token und Chat-ID zuerst speichern.")
    try:
        token = bank_sync.decrypt_secret(settings.secret_key, settings.telegram_bot_token_encrypted)
        notifications.send_telegram(token, settings.telegram_chat_id, "🔔 Testnachricht von Kies - Telegram ist korrekt eingerichtet.")
    except Exception as e:
        return schemas.NotificationTestResult(ok=False, message=f"Fehlgeschlagen: {e}")
    return schemas.NotificationTestResult(ok=True, message="Gesendet - schau in Telegram nach.")


@notify_settings_router.post("/notifications/test-proactive", response_model=schemas.NotificationTestResult)
def send_test_proactive_notification(db: Session = Depends(get_db)):
    """Schickt EINE proaktive Beispielmeldung per Telegram - genau so
    formatiert wie der echte Job (siehe main._scheduled_proactive_assistant),
    aber ohne dessen Gates. Zeigt, wie sich der proaktive Assistent meldet."""
    settings = auth.get_or_create_settings(db)
    if not settings.telegram_bot_token_encrypted or not settings.telegram_chat_id:
        return schemas.NotificationTestResult(ok=False, message="Bot-Token und Chat-ID zuerst speichern.")
    if not settings.notifications_enabled:
        return schemas.NotificationTestResult(ok=False, message="Benachrichtigungen sind aus.")
    try:
        text = proactive.preview(db, settings)
    except Exception as e:  # noqa: BLE001
        return schemas.NotificationTestResult(ok=False, message=f"Fehlgeschlagen: {e}")
    notifications.notify(
        settings,
        "🤖 " + text + "\n\n(/proaktiv pause 6 für Ruhe · /proaktiv aus zum Abschalten)",
        urgent=True,  # Testknopf -> auch in Ruhezeiten durchlassen
    )
    return schemas.NotificationTestResult(ok=True, message="Proaktive Testmeldung gesendet - schau in Telegram nach.")


@notify_settings_router.get("/notifications/log", response_model=List[schemas.NotificationLogEntry])
def get_notification_log(limit: int = 40, db: Session = Depends(get_db)):
    """Verlauf der zuletzt von Kies verschickten (bzw. wegen Ruhezeiten
    unterdrückten) Telegram-Meldungen - siehe models.NotificationLog."""
    return (
        db.query(models.NotificationLog)
        .order_by(models.NotificationLog.id.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )


# ---------------- Echte Anrufe (Twilio) für akute Fälle ----------------
@notify_settings_router.get("/settings/calls", response_model=schemas.CallSettingsOut)
def get_call_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.CallSettingsOut(
        enabled=settings.calls_enabled,
        twilio_configured=bool(
            settings.twilio_account_sid and settings.twilio_auth_token_encrypted
            and settings.twilio_from_number and settings.twilio_to_number
        ),
    )


@notify_settings_router.put("/settings/calls", response_model=schemas.CallSettingsOut)
def update_call_settings(data: schemas.CallSettingsUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.calls_enabled = data.enabled
    if data.twilio_account_sid:
        settings.twilio_account_sid = data.twilio_account_sid.strip()
    if data.twilio_auth_token:
        settings.twilio_auth_token_encrypted = bank_sync.encrypt_secret(settings.secret_key, data.twilio_auth_token)
    if data.twilio_from_number:
        settings.twilio_from_number = data.twilio_from_number.strip()
    if data.twilio_to_number:
        settings.twilio_to_number = data.twilio_to_number.strip()
    db.commit()
    return schemas.CallSettingsOut(
        enabled=settings.calls_enabled,
        twilio_configured=bool(
            settings.twilio_account_sid and settings.twilio_auth_token_encrypted
            and settings.twilio_from_number and settings.twilio_to_number
        ),
    )


@notify_settings_router.delete("/settings/calls/twilio", response_model=schemas.CallSettingsOut)
def remove_twilio_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.twilio_account_sid = None
    settings.twilio_auth_token_encrypted = None
    settings.twilio_from_number = None
    settings.twilio_to_number = None
    db.commit()
    return schemas.CallSettingsOut(enabled=settings.calls_enabled, twilio_configured=False)


@notify_settings_router.post("/calls/test", response_model=schemas.NotificationTestResult)
def send_test_call(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    if not (settings.twilio_account_sid and settings.twilio_auth_token_encrypted
            and settings.twilio_from_number and settings.twilio_to_number):
        return schemas.NotificationTestResult(ok=False, message="Twilio-Zugangsdaten und Nummern zuerst speichern.")
    try:
        token = bank_sync.decrypt_secret(settings.secret_key, settings.twilio_auth_token_encrypted)
        calls.make_call(
            settings.twilio_account_sid, token, settings.twilio_from_number, settings.twilio_to_number,
            "Testanruf von Kies. Wenn du das hörst, ist Twilio korrekt eingerichtet.",
        )
    except Exception as e:
        return schemas.NotificationTestResult(ok=False, message=f"Fehlgeschlagen: {e}")
    return schemas.NotificationTestResult(ok=True, message="Anruf ausgelöst - dein Telefon sollte gleich klingeln.")


# ---------------- To-Dos (Radicale/CalDAV) ----------------
@notify_settings_router.get("/settings/radicale", response_model=schemas.RadicaleSettingsOut)
def get_radicale_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.RadicaleSettingsOut(
        url=settings.radicale_url, username=settings.radicale_username,
        password_set=bool(settings.radicale_password_encrypted),
        calendar_url=settings.radicale_calendar_url,
    )


@notify_settings_router.put("/settings/radicale", response_model=schemas.RadicaleSettingsOut)
def update_radicale_settings(data: schemas.RadicaleSettingsUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.radicale_url = data.url
    settings.radicale_username = data.username
    settings.radicale_password_encrypted = bank_sync.encrypt_secret(settings.secret_key, data.password)
    settings.radicale_calendar_url = (data.calendar_url or "").strip() or None
    db.commit()
    return schemas.RadicaleSettingsOut(
        url=settings.radicale_url, username=settings.radicale_username, password_set=True,
        calendar_url=settings.radicale_calendar_url,
    )


@notify_settings_router.get("/settings/travel", response_model=schemas.TravelSettingsOut)
def get_travel_settings(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    return schemas.TravelSettingsOut(
        home_address=s.home_address, home_geocoded=bool(s.home_lat and s.home_lon),
        api_key_set=bool(s.openroute_api_key_encrypted),
    )


@notify_settings_router.put("/settings/travel", response_model=schemas.TravelSettingsOut)
def update_travel_settings(data: schemas.TravelSettingsUpdate, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    changes = data.model_dump(exclude_unset=True)
    # exclude_unset statt "leer heisst loeschen": beim Speichern nur des
    # API-Keys (Adresse nicht mitgeschickt) darf die schon gespeicherte
    # Adresse nicht verschwinden - live als echter Bug aufgetreten.
    if "home_address" in changes:
        address = (changes["home_address"] or "").strip()
        if address and address != s.home_address:
            # Bei jeder tatsaechlichen Adressaenderung neu geokodieren - ein
            # Fehlschlag hier soll das Speichern der uebrigen Felder nicht
            # verhindern, nur eben ohne Koordinaten (Fahrzeit-Berechnung greift
            # dann einfach nicht).
            try:
                coords = travel_time.geocode(address)
            except Exception:
                coords = None
            s.home_lat, s.home_lon = coords if coords else (None, None)
        elif not address:
            s.home_lat, s.home_lon = None, None
        s.home_address = address or None
    if changes.get("api_key"):
        s.openroute_api_key_encrypted = bank_sync.encrypt_secret(s.secret_key, changes["api_key"])
    db.commit()
    return get_travel_settings(db)


@notify_settings_router.post("/radicale/test")
def test_radicale(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    if not settings.radicale_url:
        raise HTTPException(400, "Bitte zuerst die Radicale-Adresse in den Einstellungen hinterlegen")
    password = bank_sync.decrypt_secret(settings.secret_key, settings.radicale_password_encrypted)
    try:
        n = radicale_sync.check_connection(settings.radicale_url, settings.radicale_username, password)
    except Exception as e:
        # Nur Fehlertyp + Nachricht statt roher Exception-Repraesentation
        # (koennte interne Details enthalten - CodeQL: py/stack-trace-exposure).
        # Bleibt fuer die Fehlersuche bei der eigenen Verbindung nuetzlich.
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return {"ok": True, "todo_count": n}

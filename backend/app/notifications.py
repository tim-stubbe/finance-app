"""Push-Benachrichtigungen per Telegram-Bot für Ereignisse, die sonst nur beim
Öffnen der App sichtbar wären (Ziel erreicht, Cashflow-Prognose rutscht ins
Minus, Budget überschritten). Fehler beim Versand dürfen nie einen Scheduler-Lauf
abbrechen - werden daher immer abgefangen, nie weitergeworfen."""

from datetime import datetime

import requests

from . import bank_sync

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

_LOG_KEEP = 500


def _log(text: str, urgent: bool, sent: bool) -> None:
    """Jede notify()-Meldung in models.NotificationLog schreiben (auch die per
    Ruhezeiten unterdrückten, dann sent=False) - eigener Session, best-effort,
    darf notify() nie sprengen. Beschneidet die Tabelle auf die letzten
    _LOG_KEEP Einträge."""
    try:
        from .database import SessionLocal
        from . import models
        db = SessionLocal()
        try:
            db.add(models.NotificationLog(text=text[:4000], urgent=urgent, sent=sent))
            db.commit()
            cutoff = (
                db.query(models.NotificationLog.id)
                .order_by(models.NotificationLog.id.desc())
                .offset(_LOG_KEEP).limit(1).scalar()
            )
            if cutoff:
                db.query(models.NotificationLog).filter(models.NotificationLog.id <= cutoff).delete()
                db.commit()
        finally:
            db.close()
    except Exception:
        pass


def send_telegram(token: str, chat_id: str, text: str) -> None:
    resp = requests.post(
        TELEGRAM_API.format(token=token),
        json={"chat_id": chat_id, "text": text},
        timeout=10,
    )
    resp.raise_for_status()


def _in_quiet_hours(settings, now: datetime) -> bool:
    """True, wenn `now` (LOKALE Zeit, siehe notify() - bewusst NICHT UTC wie
    sonst in der App üblich, da der Nutzer "22-7" als Wanduhrzeit meint, nicht
    als UTC-Stunden) innerhalb der konfigurierten Ruhezeiten liegt, oder
    innerhalb einer manuellen "Ruhe bis"-Überschreibung (quiet_until, ebenfalls
    lokal gespeichert, siehe telegram_bot._handle_quiet_command). Behandelt
    auch über Mitternacht laufende Fenster (z.B. 22-7: Start-Stunde liegt NACH
    der End-Stunde, das Fenster "wickelt" über den Tageswechsel)."""
    if settings.quiet_until and now < settings.quiet_until:
        return True
    if not settings.quiet_hours_enabled:
        return False
    start, end = settings.quiet_hours_start_hour, settings.quiet_hours_end_hour
    hour = now.hour
    if start == end:
        return False  # entartetes Intervall (0 Stunden) - nie aktiv statt "immer"
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # wickelt über Mitternacht, z.B. 22-7


def notify(settings, text: str, urgent: bool = False) -> None:
    """Best-effort-Versand: schickt nur, wenn Benachrichtigungen aktiv und
    Telegram konfiguriert sind. Schluckt alle Fehler bewusst (Netzwerk, falscher
    Token, ...) - eine kaputte Telegram-Verbindung soll nie den Sync/die
    Ziel-Auswertung zum Absturz bringen.

    `urgent=True` durchbricht Quiet Mode (Ruhezeiten/"Ruhe bis") - für wirklich
    zeitkritische Dinge wie "jetzt losfahren" oder ein akuter Dispo-/Risiko-
    Alarm (siehe Spezifikation "Jarvis"-Verhalten, Abschnitt C). Reine Info-
    Meldungen (Digest, Anomalie-Check, Wochenrückblick, ...) bleiben bei
    urgent=False (Default) und werden in Ruhezeiten NICHT verschickt, statt
    sie nur zu verzögern - andernfalls würden sich mehrere unterdrückte
    Meldungen morgens stapeln und genau das "nervige" Verhalten erzeugen, das
    Quiet Mode eigentlich vermeiden soll."""
    if not settings.notifications_enabled:
        return
    # datetime.now() (lokale Serverzeit, TZ=Europe/Berlin im Container) statt
    # des sonst in der App üblichen utcnow() - Ruhezeiten sind als Wanduhrzeit
    # gemeint (siehe _in_quiet_hours-Docstring), genau wie die CronTrigger-
    # Stunden des Schedulers selbst (APScheduler nutzt die System-Zeitzone).
    if not urgent and _in_quiet_hours(settings, datetime.now()):
        _log(text, urgent, sent=False)  # im Verlauf zeigen, aber nicht verschicken
        return
    if not settings.telegram_bot_token_encrypted or not settings.telegram_chat_id:
        return
    delivered = True
    try:
        token = bank_sync.decrypt_secret(settings.secret_key, settings.telegram_bot_token_encrypted)
        send_telegram(token, settings.telegram_chat_id, text)
    except Exception:
        delivered = False
    _log(text, urgent, sent=delivered)

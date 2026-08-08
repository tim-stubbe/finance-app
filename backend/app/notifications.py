"""Push-Benachrichtigungen per Telegram-Bot für Ereignisse, die sonst nur beim
Öffnen der App sichtbar wären (Ziel erreicht, Cashflow-Prognose rutscht ins
Minus, Budget überschritten). Fehler beim Versand dürfen nie einen Scheduler-Lauf
abbrechen - werden daher immer abgefangen, nie weitergeworfen."""

import requests

from . import bank_sync

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram(token: str, chat_id: str, text: str) -> None:
    resp = requests.post(
        TELEGRAM_API.format(token=token),
        json={"chat_id": chat_id, "text": text},
        timeout=10,
    )
    resp.raise_for_status()


def notify(settings, text: str) -> None:
    """Best-effort-Versand: schickt nur, wenn Benachrichtigungen aktiv und
    Telegram konfiguriert sind. Schluckt alle Fehler bewusst (Netzwerk, falscher
    Token, ...) - eine kaputte Telegram-Verbindung soll nie den Sync/die
    Ziel-Auswertung zum Absturz bringen."""
    if not settings.notifications_enabled:
        return
    if not settings.telegram_bot_token_encrypted or not settings.telegram_chat_id:
        return
    try:
        token = bank_sync.decrypt_secret(settings.secret_key, settings.telegram_bot_token_encrypted)
        send_telegram(token, settings.telegram_chat_id, text)
    except Exception:
        pass

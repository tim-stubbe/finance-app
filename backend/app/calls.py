"""Echte Sprachanrufe per Twilio für die zwei Fälle, die der Nutzer als wirklich
zeitkritisch eingestuft hat: ein akuter Cashflow-Notfall (Kontostand rutscht in
1-3 Tagen ins Minus) und ein automatisch erreichtes Ziel. Alles andere (Budget
überschritten, Cashflow-Warnung außerhalb des Notfall-Fensters) bleibt bei der
Telegram-Textbenachrichtigung - ein Anruf ist bewusst die Ausnahme, nicht die Regel.

Nutzt Twilios `Twiml`-Parameter direkt in der Call-Anfrage statt einer
Callback-URL, weil die App nur über Tailscale erreichbar ist und Twilio keinen
öffentlichen Endpunkt anfragen könnte."""

import xml.sax.saxutils

import requests

from . import bank_sync

TWILIO_CALLS_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json"


def _twiml(text: str) -> str:
    return f'<Response><Say language="de-DE">{xml.sax.saxutils.escape(text)}</Say></Response>'


def make_call(account_sid: str, auth_token: str, from_number: str, to_number: str, text: str) -> None:
    resp = requests.post(
        TWILIO_CALLS_URL.format(sid=account_sid),
        auth=(account_sid, auth_token),
        data={"To": to_number, "From": from_number, "Twiml": _twiml(text)},
        timeout=15,
    )
    resp.raise_for_status()


def call(settings, text: str) -> None:
    """Best-effort wie notifications.notify() - ein kaputter Twilio-Zugang darf
    den täglichen Sync/die Ziel-Auswertung nie zum Absturz bringen."""
    if not settings.calls_enabled:
        return
    if not (settings.twilio_account_sid and settings.twilio_auth_token_encrypted
            and settings.twilio_from_number and settings.twilio_to_number):
        return
    try:
        token = bank_sync.decrypt_secret(settings.secret_key, settings.twilio_auth_token_encrypted)
        make_call(settings.twilio_account_sid, token, settings.twilio_from_number, settings.twilio_to_number, text)
    except Exception:
        pass

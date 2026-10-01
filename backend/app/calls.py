"""Echte Sprachanrufe per Twilio für zeitkritische Fälle: akute Cashflow-
Notfälle, erreichte Ziele sowie explizit hoch eingestufte Jarvis- und
Dokumentenmeldungen. Gewöhnliche Hinweise bleiben Telegram-Nachrichten.

Nutzt Twilios `Twiml`-Parameter direkt in der Call-Anfrage statt einer
Callback-URL, weil die App nur über Tailscale erreichbar ist und Twilio keinen
öffentlichen Endpunkt anfragen könnte."""

import xml.sax.saxutils
import os
import re
import unicodedata

import requests

from . import bank_sync

TWILIO_CALLS_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json"
def _speech_safe(text: str) -> str:
    """Turn notification prose into short, understandable spoken German."""
    value = unicodedata.normalize("NFKC", text or "")
    value = re.sub(r"https?://\S+", " Link in Telegram ", value)
    value = re.sub(r"[#*_`~|<>\[\]{}]", " ", value)
    value = value.replace("€", " Euro ").replace("%", " Prozent ")
    value = re.sub(r"[\U00010000-\U0010ffff]", " ", value)
    value = "".join(" " if unicodedata.category(char) in ("So", "Sk") else char for char in value)
    value = re.sub(r"\s+", " ", value).strip()
    # A phone call must not read an entire generated report or raw payload.
    return value[:500].rsplit(" ", 1)[0] if len(value) > 500 else value
def make_local_call(url: str, token: str, to_number: str, text: str) -> None:
    """Lokales SIP-Gateway ansprechen (FRITZ!Box heute, VoLTE-Gateway später)."""
    resp = requests.post(
        url.rstrip("/") + "/call",
        headers={"Authorization": f"Bearer {token}"},
        json={"to": to_number, "text": text[:1200]}, timeout=20,
    )
    resp.raise_for_status()


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


def call(settings, text: str, *, interactive: bool = False) -> None:
    """Best-effort wie notifications.notify() - ein kaputter Twilio-Zugang darf
    den täglichen Sync/die Ziel-Auswertung nie zum Absturz bringen."""
    if not settings.calls_enabled:
        return
    # The current gateways only play a message and hang up. Never use that
    # path for automatic escalation: it cannot accept a reply and will speak
    # into voicemail. A future two-way gateway must opt in explicitly.
    if not interactive and os.environ.get("KIES_ALLOW_ONE_WAY_CALLS", "").lower() not in ("1", "true", "yes"):
        return
    text = _speech_safe(text)
    local_url = os.environ.get("KIES_LOCAL_CALL_URL", "").strip()
    local_token = os.environ.get("KIES_LOCAL_CALL_TOKEN", "").strip()
    local_to = (os.environ.get("KIES_CALL_TO", "").strip()
                or (settings.twilio_to_number or "").strip())
    if local_url and local_token and local_to:
        try:
            make_local_call(local_url, local_token, local_to, text)
        except Exception:
            pass
        return
    if not (settings.twilio_account_sid and settings.twilio_auth_token_encrypted
            and settings.twilio_from_number and settings.twilio_to_number):
        return
    try:
        token = bank_sync.decrypt_secret(settings.secret_key, settings.twilio_auth_token_encrypted)
        make_call(settings.twilio_account_sid, token, settings.twilio_from_number, settings.twilio_to_number, text)
    except Exception:
        pass

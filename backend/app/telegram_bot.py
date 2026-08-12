"""Long-Polling-Bot: beantwortet Nachrichten an den konfigurierten Telegram-Bot
über denselben Ollama-Assistenten wie der schwebende Web-Chat (inkl. Websuche
und Steuer-Einschätzungen). Reiner Lesezugriff/Auskunft über die KI-Chat-Runde -
bewusste Nutzerentscheidung, um das Risiko bei einem geleakten Bot-Token gering
zu halten. EINZIGE Ausnahme: das explizite Kommando /saldo (siehe
_BALANCE_CMD_RE) setzt den Kontostand direkt, an der KI vorbei (kein Raten bei
einer Geldsumme) - jede Änderung landet nachvollziehbar in AccountBalanceLog.

Läuft als Dauerschleife in einem Hintergrund-Thread statt über einen Webhook,
weil die App nur über Tailscale erreichbar ist, kein öffentlicher HTTPS-Endpunkt
existiert, den Telegram anfragen könnte.

Antwortet ausschließlich auf Nachrichten aus dem in den Einstellungen hinterlegten
Chat - Nachrichten von jeder anderen Chat-ID werden stillschweigend ignoriert
(aber trotzdem als "gesehen" markiert), damit niemand sonst, der die Bot-ID
errät, an Finanzdaten oder Ollama-Antworten herankommt."""

import re
import time

import requests

from . import auth, bank_sync, crud, models, ollama_client, websearch
from .database import SessionLocal

TELEGRAM_API = "https://api.telegram.org/bot{token}"
POLL_TIMEOUT = 30
IDLE_SLEEP_SECONDS = 10
ERROR_BACKOFF_SECONDS = 15
MAX_HISTORY = 20  # Nachrichten (User+Assistant zusammen); nur im Prozessspeicher

_SEARCH_BLOCK_RE = re.compile(r"```search\s*(.*?)\s*```", re.DOTALL)
# Bewusst ein explizites Kommando statt Freitext-Interpretation durch die KI -
# bei einer Geldsumme soll nichts geraten werden. Format: /saldo <Kontoname> <Betrag>
_BALANCE_CMD_RE = re.compile(r"^/saldo\s+(.+?)\s+(-?\d+(?:[.,]\d{1,2})?)\s*€?\s*$", re.IGNORECASE)

TELEGRAM_SYSTEM_PROMPT = """Du bist der KI-Assistent von Kies, einem privaten Finanztool, hier per Telegram erreichbar. \
Antworte immer kurz und freundlich auf Deutsch.

Du kannst hier nichts in Buchungen schreiben oder Konten anlegen/löschen - dafür sag dem Nutzer freundlich, dass \
er das in der App (schwebender KI-Chat oder direkt) erledigen soll. EINZIGE Ausnahme: den Saldo eines Kontos ODER \
einer Schuld (z.B. eine Kreditkarte als Kreditlinie) setzen kann der Nutzer direkt hier mit dem Kommando \
"/saldo <Name> <Betrag>" (z.B. "/saldo Tagesgeld 772,57") - weise bei einer entsprechenden Bitte auf genau \
dieses Kommando hin, statt es selbst als Fließtext zu versuchen.

Für Fragen zum aktuellen Stand (Kontostand, Vermögen, Ausgaben) nutze NUR die unten mitgelieferten Fakten und \
erfinde keine Zahlen.

Du darfst im Internet suchen, wenn du für eine Frage aktuelle, recherchierbare Informationen brauchst (z.B. \
aktuelle Steuersätze/Freibeträge, Rechtslage, Zinssätze, aktuelle Nachrichten). Brauchst du das, antworte NUR \
mit einem Suchblock, sonst NICHTS (kein Fließtext davor/danach):
```search
<eine kurze, gezielte Suchanfrage>
```
Du bekommst danach Suchergebnisse und antwortest DANN im Fließtext basierend darauf. Nutze das gezielt, nicht \
bei jeder Frage.

Für Steuerfragen (z.B. "Leasing gewerblich oder privat absetzen"): gib eine fundierte Einschätzung inkl. der \
wichtigsten Rechenlogik, aber das ist KEINE verbindliche Steuerberatung - weise IMMER kurz darauf hin, dass \
der Nutzer das bei komplexen/hohen Beträgen mit einem Steuerberater absichern sollte."""

_history: list[dict] = []


def _context_facts(db, space_id: int) -> str:
    accounts = crud.get_accounts(db, space_id)
    debts_list = crud.get_debts(db, space_id)
    nw = crud.net_worth(db, space_id)
    lines = ["Aktueller Stand:"]
    for a in accounts:
        lines.append(f"- Konto „{a.name}“: {crud.account_balance(db, a):.2f} EUR")
    for d in debts_list:
        if d.status == models.DebtStatus.active:
            lines.append(f"- Schuld „{d.name}“: {d.current_balance:.2f} EUR")
    lines.append(f"- Investments gesamt: {nw.investments_total:.2f} EUR")
    if nw.debts_total:
        lines.append(f"- Offene Schulden gesamt: {nw.debts_total:.2f} EUR")
    lines.append(f"- Nettovermögen: {nw.total:.2f} EUR")
    return "\n".join(lines)


def _send(token: str, chat_id: str, text: str) -> None:
    resp = requests.post(
        f"{TELEGRAM_API.format(token=token)}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=15,
    )
    resp.raise_for_status()


def _handle_balance_command(db, token: str, chat_id: str, text: str) -> bool:
    """Erkennt und verarbeitet /saldo <Kontoname> <Betrag>. Gibt True zurück,
    wenn die Nachricht als dieses Kommando erkannt wurde (dann ist sie
    abschließend behandelt, egal ob erfolgreich) - sonst False, damit der
    normale KI-Chat-Weg weiterläuft."""
    match = _BALANCE_CMD_RE.match(text.strip())
    if not match:
        return False
    name_query, amount_raw = match.groups()
    try:
        new_balance = float(amount_raw.replace(",", "."))
    except ValueError:
        _send(token, chat_id, f"„{amount_raw}“ ist kein gültiger Betrag.")
        return True
    space = crud.get_spaces(db)[0]
    obj, error = crud.set_balance_by_name(db, space.id, name_query, new_balance, source="telegram")
    db.commit()
    if error:
        _send(token, chat_id, error)
    else:
        _send(token, chat_id, f"✓ „{obj.name}“ auf {new_balance:.2f} € gesetzt.")
    return True


def _handle_message(db, settings, token: str, chat_id: str, text: str) -> None:
    if _handle_balance_command(db, token, chat_id, text):
        return

    chat_model = settings.ollama_model or settings.beleg_chat_model
    if not settings.ollama_url or not chat_model:
        _send(token, chat_id, "Ollama ist in der App noch nicht unter Einstellungen eingerichtet.")
        return

    space = crud.get_spaces(db)[0]
    system_content = TELEGRAM_SYSTEM_PROMPT + "\n\n" + _context_facts(db, space.id)
    messages = [{"role": "system", "content": system_content}]
    messages.extend(_history[-MAX_HISTORY:])
    messages.append({"role": "user", "content": text})

    reply = ollama_client.chat(settings.ollama_url, chat_model, messages)

    match = _SEARCH_BLOCK_RE.search(reply)
    if match:
        query = match.group(1).strip()
        if not settings.brave_search_api_key_encrypted:
            _send(token, chat_id, f"Würde dafür gern im Internet suchen („{query}“), aber in der App ist noch "
                                   "kein Brave-Search-API-Key hinterlegt.")
            return
        api_key = bank_sync.decrypt_secret(settings.secret_key, settings.brave_search_api_key_encrypted)
        results = websearch.search(api_key, query)
        _send(token, chat_id, f"🌐 hat im Internet gesucht: „{query}“")
        messages.append({"role": "assistant", "content": reply})
        messages.append({"role": "user", "content": websearch.format_for_prompt(query, results)
                         + "\n\nBeantworte jetzt meine ursprüngliche Frage auf Basis dieser Suchergebnisse."})
        reply = ollama_client.chat(settings.ollama_url, chat_model, messages)

    reply = _SEARCH_BLOCK_RE.sub("", reply).strip()
    _history.append({"role": "user", "content": text})
    _history.append({"role": "assistant", "content": reply})
    del _history[:-MAX_HISTORY]

    _send(token, chat_id, reply or "(keine Antwort erhalten)")


def _poll_once(db) -> None:
    settings = auth.get_or_create_settings(db)
    if not (settings.notifications_enabled and settings.telegram_bot_token_encrypted and settings.telegram_chat_id):
        time.sleep(IDLE_SLEEP_SECONDS)
        return

    token = bank_sync.decrypt_secret(settings.secret_key, settings.telegram_bot_token_encrypted)
    configured_chat_id = str(settings.telegram_chat_id)
    offset = (settings.telegram_last_update_id or 0) + 1

    resp = requests.get(
        f"{TELEGRAM_API.format(token=token)}/getUpdates",
        params={"offset": offset, "timeout": POLL_TIMEOUT},
        timeout=POLL_TIMEOUT + 10,
    )
    resp.raise_for_status()
    updates = resp.json().get("result", [])

    for upd in updates:
        settings.telegram_last_update_id = upd["update_id"]
        msg = upd.get("message") or {}
        incoming_chat_id = str((msg.get("chat") or {}).get("id", ""))
        text = msg.get("text")
        if text and incoming_chat_id == configured_chat_id:
            try:
                _handle_message(db, settings, token, configured_chat_id, text)
            except Exception as e:
                try:
                    _send(token, configured_chat_id, f"Fehler: {e}")
                except Exception:
                    pass
        db.commit()


def run_polling_loop() -> None:
    while True:
        db = SessionLocal()
        try:
            _poll_once(db)
        except Exception:
            db.rollback()
            time.sleep(ERROR_BACKOFF_SECONDS)
        finally:
            db.close()

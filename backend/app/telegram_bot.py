"""Long-Polling-Bot: beantwortet Nachrichten an den konfigurierten Telegram-Bot
über denselben Ollama-Assistenten wie der schwebende Web-Chat (inkl. Websuche
und Steuer-Einschätzungen). Reiner Lesezugriff/Auskunft über die KI-Chat-Runde -
bewusste Nutzerentscheidung, um das Risiko bei einem geleakten Bot-Token gering
zu halten. Ausnahmen sind ausschließlich fest kodierte, deterministische
Kommandos (Regex, keine KI-Interpretation): /saldo (Kontostand setzen,
_BALANCE_CMD_RE), /todo (To-Do anlegen, _TODO_CMD_RE), /erledigt (To-Do
abhaken, _DONE_CMD_RE) und /termin (Kalender-Termin anlegen, _TERMIN_CMD_RE) -
bei Geld/Terminen/Aufgaben soll nichts geraten werden. Jede Saldo-Änderung
landet nachvollziehbar in AccountBalanceLog.

Läuft als Dauerschleife in einem Hintergrund-Thread statt über einen Webhook,
weil die App nur über Tailscale erreichbar ist, kein öffentlicher HTTPS-Endpunkt
existiert, den Telegram anfragen könnte.

Antwortet ausschließlich auf Nachrichten aus dem in den Einstellungen hinterlegten
Chat - Nachrichten von jeder anderen Chat-ID werden stillschweigend ignoriert
(aber trotzdem als "gesehen" markiert), damit niemand sonst, der die Bot-ID
errät, an Finanzdaten oder Ollama-Antworten herankommt."""

import re
import time
from datetime import date, datetime

import requests

from . import auth, bank_sync, crud, models, ollama_client, radicale_sync, websearch
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
# Format: /todo <Text> [TT.MM.[JJJJ]] - optionales Fälligkeitsdatum am Ende.
_TODO_CMD_RE = re.compile(r"^/todo\s+(.+?)(?:\s+(\d{1,2})\.(\d{1,2})\.(\d{4})?)?\s*$", re.IGNORECASE)
# Format: /erledigt <Text> - hakt ein offenes To-Do per (Teil-)Name ab.
_DONE_CMD_RE = re.compile(r"^/erledigt\s+(.+)$", re.IGNORECASE)
# Format: /termin <Titel>; TT.MM.[JJJJ] [HH:MM][; Ort] - ohne Uhrzeit gilt der
# Termin als ganztägig, ohne Jahr wird das laufende Jahr angenommen.
_TERMIN_CMD_RE = re.compile(
    r"^/termin\s+(.+?)\s*;\s*(\d{1,2})\.(\d{1,2})\.(\d{4})?"
    r"(?:\s+(\d{1,2}):(\d{2}))?"
    r"(?:\s*;\s*(.+))?\s*$",
    re.IGNORECASE,
)

TELEGRAM_SYSTEM_PROMPT = """Du bist der KI-Assistent von Kies, einem privaten Finanztool, hier per Telegram erreichbar. \
Antworte immer kurz und freundlich auf Deutsch.

Du kannst hier nichts in Buchungen schreiben oder Konten anlegen/löschen - dafür sag dem Nutzer freundlich, dass \
er das in der App (schwebender KI-Chat oder direkt) erledigen soll. Es gibt vier feste Ausnahmen, jeweils über ein \
exaktes Kommando (nicht selbst als Fließtext nachbauen, sondern dem Nutzer das Kommando nennen):
- Saldo setzen: "/saldo <Name> <Betrag>" (z.B. "/saldo Tagesgeld 772,57") - für Konten UND Schulden/Kreditlinien.
- To-Do anlegen: "/todo <Text> [TT.MM.[JJJJ]]" (z.B. "/todo Wäsche waschen" oder "/todo Steuererklärung 15.09.").
- To-Do abhaken: "/erledigt <Text>" (z.B. "/erledigt Wäsche").
- Termin anlegen: "/termin <Titel>; TT.MM.[JJJJ] [HH:MM][; Ort]" (z.B. "/termin Zahnarzt; 20.08. 14:30; Praxis Müller" \
oder ganztägig ohne Uhrzeit: "/termin Urlaub Start; 01.09.").

Für Fragen zum aktuellen Stand (Kontostand, Vermögen, Ausgaben, anstehende Termine, offene To-Dos) nutze NUR die \
unten mitgelieferten Fakten und erfinde keine Zahlen/Termine.

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

    events = crud.get_upcoming_calendar_events(db, days=7, limit=10)
    if events:
        lines.append("\nAnstehende Termine (nächste 7 Tage):")
        for ev in events:
            when = "ganztägig" if ev.all_day else ev.start.strftime("%H:%M")
            lines.append(f"- {ev.start.strftime('%d.%m.')} {when}: „{ev.title}“" + (f" ({ev.location})" if ev.location else ""))

    todos = crud.get_todos(db, include_done=False)[:10]
    if todos:
        lines.append("\nOffene To-Dos:")
        for t in todos:
            lines.append(f"- {t.title}" + (f" (fällig {t.due_date.strftime('%d.%m.%Y')})" if t.due_date else ""))

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


def _first_calendar_url(settings) -> str | None:
    if not settings.radicale_calendar_url:
        return None
    urls = [u.strip() for u in settings.radicale_calendar_url.split(",") if u.strip()]
    return urls[0] if urls else None


def _handle_todo_command(db, settings, token: str, chat_id: str, text: str) -> bool:
    match = _TODO_CMD_RE.match(text.strip())
    if not match:
        return False
    title, day, month, year = match.groups()
    due_date = None
    if day:
        try:
            due_date = date(int(year) if year else date.today().year, int(month), int(day))
        except ValueError:
            _send(token, chat_id, f"„{day}.{month}.{year or ''}“ ist kein gültiges Datum.")
            return True
    todo = crud.create_todo(db, title.strip(), due_date)
    if settings.radicale_url:
        try:
            radicale_sync.sync(db, settings.radicale_url, settings.radicale_username,
                                bank_sync.decrypt_secret(settings.secret_key, settings.radicale_password_encrypted))
        except Exception:
            pass
    _send(token, chat_id, f"✓ To-Do „{todo.title}“ angelegt" + (f", fällig am {due_date.strftime('%d.%m.%Y')}." if due_date else "."))
    return True


def _handle_done_command(db, settings, token: str, chat_id: str, text: str) -> bool:
    match = _DONE_CMD_RE.match(text.strip())
    if not match:
        return False
    name_query = match.group(1)
    todo, error = crud.complete_todo_by_name(db, name_query)
    db.commit()
    if error:
        _send(token, chat_id, error)
        return True
    if settings.radicale_url:
        try:
            radicale_sync.sync(db, settings.radicale_url, settings.radicale_username,
                                bank_sync.decrypt_secret(settings.secret_key, settings.radicale_password_encrypted))
        except Exception:
            pass
    _send(token, chat_id, f"✓ „{todo.title}“ abgehakt.")
    return True


def _handle_termin_command(db, settings, token: str, chat_id: str, text: str) -> bool:
    match = _TERMIN_CMD_RE.match(text.strip())
    if not match:
        return False
    title, day, month, year, hour, minute, location = match.groups()
    try:
        event_date = date(int(year) if year else date.today().year, int(month), int(day))
    except ValueError:
        _send(token, chat_id, f"„{day}.{month}.{year or ''}“ ist kein gültiges Datum.")
        return True
    all_day = hour is None
    start = datetime(event_date.year, event_date.month, event_date.day, int(hour) if hour else 0, int(minute) if minute else 0)
    calendar_url = _first_calendar_url(settings)
    event = crud.create_calendar_event(db, title.strip(), start, None, (location or "").strip() or None, all_day, calendar_url)
    if calendar_url:
        try:
            radicale_sync.sync_calendar(db, calendar_url, settings.radicale_username,
                                         bank_sync.decrypt_secret(settings.secret_key, settings.radicale_password_encrypted))
        except Exception:
            pass
    when = "ganztägig" if all_day else start.strftime("%H:%M")
    _send(token, chat_id, f"✓ Termin „{event.title}“ am {event_date.strftime('%d.%m.%Y')} ({when}) angelegt.")
    return True


def _handle_message(db, settings, token: str, chat_id: str, text: str) -> None:
    if _handle_balance_command(db, token, chat_id, text):
        return
    if _handle_todo_command(db, settings, token, chat_id, text):
        return
    if _handle_done_command(db, settings, token, chat_id, text):
        return
    if _handle_termin_command(db, settings, token, chat_id, text):
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

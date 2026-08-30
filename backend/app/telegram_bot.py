"""Long-Polling-Bot: beantwortet Nachrichten an den konfigurierten Telegram-Bot
über denselben Ollama-Assistenten wie der schwebende Web-Chat (inkl. Websuche
und Steuer-Einschätzungen). Reiner Lesezugriff/Auskunft für Finanzdaten - der
Saldo bleibt bewusst ausschließlich über das feste Kommando /saldo (Regex,
_BALANCE_CMD_RE, keine KI-Interpretation) änderbar, bei Geld soll nichts
geraten werden. Jede Saldo-Änderung landet nachvollziehbar in AccountBalanceLog.

Termine, To-Dos, offene Punkte zu Business-Projekten (Nebenprojekte außerhalb
der Finanzverwaltung, siehe models.BusinessProject - Kies hat keinen
Datenzugriff auf z.B. Roblox/Kundensysteme, sammelt aber die vom Nutzer
gemeldeten offenen Punkte an einem Ort und erinnert per main.
_scheduled_business_check_reminder, wenn ein Projekt lange nicht bestätigt
wurde) und Check-ins zu persönlichen Lebensbereichen (models.LifeArea -
gleiches Prinzip, nur für Fitness/Auftreten/... statt Geschäftliches) dürfen
dagegen auch in normaler Sprache angelegt/abgehakt/abgesagt werden
(Nutzerentscheidung, das Risiko einer Fehlinterpretation hier in Kauf zu
nehmen) - die KI antwortet dafür mit einem ```action```-Block
(_ACTION_BLOCK_RE, siehe _execute_action), den der Bot statt der KI ausführt
und danach IMMER eine Bestätigung mit dem tatsächlich verstandenen Ergebnis
zurückschickt, damit ein Missverständnis sofort auffällt (und sich korrigieren
lässt). Für die Wunschliste (models.WishlistItem) darf die KI sogar einen
neuen Eintrag anlegen, wenn eindeutig genannt - einziger Unterschied zu
Projekten/Lebensbereichen, weil hier nichts Falsches passieren kann außer
einem überflüssigen Listeneintrag. Die festen Kommandos (/todo, /erledigt,
/termin, /termin_absagen, /projekt, /projekt_erledigt, /projekt_geprueft,
/leben, /wunsch, /wunsch_geprueft) bleiben parallel nutzbar, wenn Präzision
wichtiger ist als Bequemlichkeit. /status schickt
außerdem den sonst nur alle 3 Stunden automatisch verschickten Digest sofort
auf Zuruf.

Läuft als Dauerschleife in einem Hintergrund-Thread statt über einen Webhook,
weil die App nur über Tailscale erreichbar ist, kein öffentlicher HTTPS-Endpunkt
existiert, den Telegram anfragen könnte.

Antwortet ausschließlich auf Nachrichten aus dem in den Einstellungen hinterlegten
Chat - Nachrichten von jeder anderen Chat-ID werden stillschweigend ignoriert
(aber trotzdem als "gesehen" markiert), damit niemand sonst, der die Bot-ID
errät, an Finanzdaten oder Ollama-Antworten herankommt."""

import json
import re
import time
from datetime import date, datetime, timedelta

import requests

from . import ai_auto, auth, bank_sync, crud, models, ollama_client, radicale_sync, schemas, websearch, voice
from .database import SessionLocal

TELEGRAM_API = "https://api.telegram.org/bot{token}"
POLL_TIMEOUT = 30
IDLE_SLEEP_SECONDS = 10
ERROR_BACKOFF_SECONDS = 15
MAX_HISTORY = 20  # Nachrichten (User+Assistant zusammen); nur im Prozessspeicher

_SEARCH_BLOCK_RE = re.compile(r"```search\s*(.*?)\s*```", re.DOTALL)
_ACTION_BLOCK_RE = re.compile(r"```action\s*(.*?)\s*```", re.DOTALL)
# Bewusst ein explizites Kommando statt Freitext-Interpretation durch die KI -
# bei einer Geldsumme soll nichts geraten werden. Format: /saldo <Kontoname> <Betrag>
_BALANCE_CMD_RE = re.compile(r"^/saldo\s+(.+?)\s+(-?\d+(?:[.,]\d{1,2})?)\s*€?\s*$", re.IGNORECASE)
# Format: /todo <Text> [TT.MM.[JJJJ]] - optionales Fälligkeitsdatum am Ende.
_TODO_CMD_RE = re.compile(r"^/todo\s+(.+?)(?:\s+(\d{1,2})\.(\d{1,2})\.(\d{4})?)?\s*$", re.IGNORECASE)
# Format: /erledigt <Text> - hakt ein offenes To-Do per (Teil-)Name ab.
_DONE_CMD_RE = re.compile(r"^/erledigt\s+(.+)$", re.IGNORECASE)
# Format: /termin_absagen <Text> - sagt einen anstehenden Termin per (Teil-)Name ab.
_CANCEL_TERMIN_CMD_RE = re.compile(r"^/termin_absagen\s+(.+)$", re.IGNORECASE)
# Format: /termin <Titel>; TT.MM.[JJJJ] [HH:MM][; Ort] - ohne Uhrzeit gilt der
# Termin als ganztägig, ohne Jahr wird das laufende Jahr angenommen.
_TERMIN_CMD_RE = re.compile(
    r"^/termin\s+(.+?)\s*;\s*(\d{1,2})\.(\d{1,2})\.(\d{4})?"
    r"(?:\s+(\d{1,2}):(\d{2}))?"
    r"(?:\s*;\s*(.+))?\s*$",
    re.IGNORECASE,
)
# Format: /status - schickt den Digest sofort statt auf den naechsten
# 3-Stunden-Termin (siehe main.DIGEST_HOURS) zu warten.
_STATUS_CMD_RE = re.compile(r"^/status\s*$", re.IGNORECASE)
# Format: /projekt <Name>; <Titel> - legt einen offenen Punkt bei einem
# Business-Projekt an (siehe models.BusinessProject).
_PROJECT_ISSUE_CMD_RE = re.compile(r"^/projekt\s+(.+?)\s*;\s*(.+)$", re.IGNORECASE)
# Format: /projekt_erledigt <Name>; <Stichwort> - hakt einen offenen Punkt ab.
_PROJECT_RESOLVE_CMD_RE = re.compile(r"^/projekt_erledigt\s+(.+?)\s*;\s*(.+)$", re.IGNORECASE)
# Format: /projekt_geprueft <Name> - setzt den "zuletzt geprüft"-Zeitpunkt
# zurück, ohne einen neuen offenen Punkt anzulegen.
_PROJECT_CHECKED_CMD_RE = re.compile(r"^/projekt_geprueft\s+(.+)$", re.IGNORECASE)
# Format: /leben <Bereich>; <Notiz> - Check-in bei einem persönlichen
# Lebensbereich (siehe models.LifeArea).
_LIFE_CHECKIN_CMD_RE = re.compile(r"^/leben\s+(.+?)\s*;\s*(.+)$", re.IGNORECASE)
# Format: /wunsch <Name> - legt einen Wunschlisten-Eintrag an (siehe
# models.WishlistItem). Feineres (Zielpreis, Link, Auto-Prüfung) über die App.
_WISHLIST_ADD_CMD_RE = re.compile(r"^/wunsch\s+(.+)$", re.IGNORECASE)
# Format: /wunsch_geprueft <Name> - bestätigt "gerade nachgeschaut".
_WISHLIST_CHECKED_CMD_RE = re.compile(r"^/wunsch_geprueft\s+(.+)$", re.IGNORECASE)
# --- "Jarvis"-Kommandos (Quiet Mode, Vorschläge, "was hängt") ---
# Format: /ruhe HH:MM - manuelle Ruhe-bis-Überschreibung (siehe
# notifications._in_quiet_hours). /ruhe aus hebt sie vorzeitig auf.
_QUIET_CMD_RE = re.compile(r"^/ruhe\s+(\d{1,2}):(\d{2})\s*$", re.IGNORECASE)
_QUIET_OFF_CMD_RE = re.compile(r"^/ruhe\s+aus\s*$", re.IGNORECASE)
# Format: /ok, /später (oder /spaeter), /verwerfen - Antwort auf den aktuell
# einzigen offenen Vorschlag (siehe main._scheduled_suggestion_check).
_SUGGESTION_OK_CMD_RE = re.compile(r"^/ok\s*$", re.IGNORECASE)
_SUGGESTION_LATER_CMD_RE = re.compile(r"^/sp(ä|ae)ter\s*$", re.IGNORECASE)
_SUGGESTION_DISMISS_CMD_RE = re.compile(r"^/verwerfen\s*$", re.IGNORECASE)
# Format: /haengt - Zusammenfassung auf Zuruf (siehe crud.get_hanging_items).
_HANGING_CMD_RE = re.compile(r"^/h(ä|ae)ngt\s*$", re.IGNORECASE)
# Format: /proaktiv [an|aus|pause [N]] - proaktiven KI-Assistenten steuern
# (siehe proactive.py / main._scheduled_proactive_assistant). Ohne Argument:
# Status. "pause" ohne Zahl = 6 Stunden.
_PROACTIVE_CMD_RE = re.compile(
    r"^/proaktiv(?:\s+(an|ein|aus|off|on|pause|snooze)(?:\s+(\d{1,3}))?)?\s*$", re.IGNORECASE,
)
# Format: /nützlich bzw. /unnötig - Rückmeldung zur letzten proaktiven Meldung.
# Der Text wird in models.ProactiveFeedback abgelegt und fließt beim nächsten
# Lauf über proactive._feedback_hint in den System-Prompt ein.
_PROACTIVE_FEEDBACK_CMD_RE = re.compile(
    r"^/(n(?:ü|ue)tzlich|gut|unn(?:ö|oe)tig|schlecht|nervt)\s*$", re.IGNORECASE,
)
# Format: /ausgabe <Konto>; <Betrag>; <Text> - schnelle Ausgabe (Spezifikation
# Abschnitt D). Bewusst ein FESTES Kommando statt KI-Freitext-Erkennung wie
# bei Todo/Termin/Projekt/Leben (siehe _execute_action) - bei Geld soll
# genau wie bei /saldo nichts geraten werden, das Konto muss explizit
# genannt werden.
_EXPENSE_CMD_RE = re.compile(
    r"^/ausgabe\s+(.+?)\s*;\s*(-?\d+(?:[.,]\d{1,2})?)\s*€?\s*;\s*(.+)$", re.IGNORECASE,
)
# Format: /haus <Befehl> - Smart-Home-Steuerung/Abfrage ueber dieselbe
# Pipeline wie der Smart-Home-Tab (siehe smarthome.process_command).
_HOME_CMD_RE = re.compile(r"^/haus\s+(.+)$", re.IGNORECASE | re.DOTALL)
# Format: /steuer - die wichtigsten Steuer-Spar-Ansaetze auf Zuruf
# (siehe tax_advice.generate_tips). Ohne Argument.
_STEUER_CMD_RE = re.compile(r"^/steuer\s*$", re.IGNORECASE)

TELEGRAM_SYSTEM_PROMPT = """Du bist der KI-Assistent von Kies, einem privaten Finanztool, hier per Telegram erreichbar. \
Antworte immer kurz und freundlich auf Deutsch.

Du kannst hier nichts in Buchungen schreiben oder Konten anlegen/löschen - dafür sag dem Nutzer freundlich, dass \
er das in der App (schwebender KI-Chat oder direkt) erledigen soll. Der Kontostand ist NUR über das feste Kommando \
"/saldo <Name> <Betrag>" änderbar (z.B. "/saldo Tagesgeld 772,57") - das musst du dem Nutzer nennen, nicht selbst \
als Fließtext nachbauen, bei Geld wird nichts geraten.

Termine und To-Dos darfst du dagegen direkt aus normaler Sprache heraus anlegen/abhaken/absagen, ohne dass der \
Nutzer ein Kommando tippen muss. Erkennst du eindeutig eine solche Absicht, antworte AUSSCHLIESSLICH mit einem \
Aktions-Block (kein Fließtext davor/danach), einer der folgenden Formen:
```action
{"type": "create_todo", "title": "<Text>", "due_date": "JJJJ-MM-TT oder null"}
```
```action
{"type": "complete_todo", "title": "<Stichwort aus dem Titel>"}
```
```action
{"type": "create_termin", "title": "<Text OHNE den Ort>", "date": "JJJJ-MM-TT", "time": "HH:MM oder null bei ganztägig", "location": "<Ort oder null>"}
```
```action
{"type": "cancel_termin", "title": "<Stichwort aus dem Titel>"}
```
Genauso darfst du offene Punkte zu einem Business-Projekt (Nebenprojekte außerhalb der Finanzverwaltung, z.B. \
"Roblox-Spiel X", siehe unten mitgelieferte Liste) anlegen/abhaken, und ein Projekt als "gerade geprüft" bestätigen:
```action
{"type": "create_business_issue", "project": "<Projektname oder Stichwort davon>", "title": "<worum es geht>"}
```
```action
{"type": "resolve_business_issue", "project": "<Projektname oder Stichwort davon>", "title": "<Stichwort aus dem offenen Punkt>"}
```
```action
{"type": "mark_project_checked", "project": "<Projektname oder Stichwort davon>"}
```
Nutze diese NUR für eines der unten mitgelieferten, bereits angelegten Projekte - erfinde kein neues Projekt, das \
muss der Nutzer erst in der App anlegen. Ist unklar, welches Projekt gemeint ist, frag lieber nach.

Genauso gibt es persönliche Lebensbereiche (Fitness/Körper, Auftreten, ...), auch dafür NUR bereits angelegte \
Bereiche aus der unten mitgelieferten Liste verwenden:
```action
{"type": "life_checkin", "area": "<Bereichsname oder Stichwort davon>", "note": "<worum es geht/was passiert ist>", "progress_percent": <0-100 oder weglassen, wenn nicht genannt>}
```

Und die Wunschliste (Dinge, die der Nutzer kaufen will, wenn sie günstig sind, z.B. ein Flug oder ein Produkt) - \
hier DARFST du (anders als bei Projekten/Lebensbereichen) auch einen neuen Eintrag erfinden, wenn der Nutzer klar \
etwas Neues nennt, das noch nicht in der Liste steht:
```action
{"type": "add_wishlist_item", "name": "<worum es geht>", "target_price": <Zahl in EUR oder weglassen>}
```
```action
{"type": "mark_wishlist_checked", "name": "<Name oder Stichwort aus der Wunschliste>"}
```
Wichtig: Kies hat KEINE echten Preisdaten (keine Flug-/Preis-API) - sag dem Nutzer nie, dass etwas gerade günstig \
ist, außer er hat das selbst gesagt oder es kommt so aus den unten mitgelieferten Fakten.

Rechne relative Datumsangaben anhand des unten mitgelieferten heutigen Datums IMMER selbst in JJJJ-MM-TT um, auch \
bei einem To-Do - lass due_date/date NIE auf null, wenn der Nutzer irgendeine Zeitangabe genannt hat. "morgen" = \
heute + 1 Tag, "übermorgen" = heute + 2 Tage, "in 3 Tagen" = heute + 3 Tage - zähl das genau nach, verwechsle \
"morgen" und "übermorgen" nicht. Beispiel bei "Heutiges Datum: 2026-08-12": "morgen" → "2026-08-13", "übermorgen" \
→ "2026-08-14". Nur wenn WIRKLICH keinerlei Zeitangabe im Text vorkommt, darf due_date null sein bzw. musst du bei \
einem Termin (date ist dort Pflicht) stattdessen nachfragen statt zu raten.

Nennt der Nutzer bei einem Termin einen Ort (z.B. "beim Zahnarzt in der Praxis Müller", "im Büro"), gehört der \
IMMER ins separate Feld "location", NIEMALS in "title" hineingemischt - "title" bleibt kurz (z.B. "Zahnarzt"), \
"location" bekommt den Ort (z.B. "Praxis Müller"). Der Bot führt den Aktions-Block aus und schickt dem Nutzer \
danach selbst eine Bestätigung - du musst dem Aktions-Block nichts hinzufügen.

Für Fragen zum aktuellen Stand (Kontostand, Vermögen, Ausgaben, anstehende Termine, offene To-Dos) nutze NUR die \
unten mitgelieferten Fakten und erfinde keine Zahlen/Termine. Für einen vollständigen, tagesaktuellen Statusbericht \
(sonst nur alle 3 Stunden automatisch) verweise auf das Kommando "/status".

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

# Kommunikationsstil (Spezifikation Abschnitt I) - gilt bewusst NUR für
# Telegram-Fließtext-Antworten (dieser Prompt-Zusatz) und KI-Systemprompts
# (siehe ai_assistant.py-Prompts), NICHT für Zahlen selbst - die bleiben in
# jedem Stil nüchtern, siehe TELEGRAM_SYSTEM_PROMPT oben ("bei Geld wird
# nichts geraten"). Feste Vorlagen-Meldungen (Digest, Alerts, Erinnerungen)
# bleiben bewusst unverändert neutral - Dutzende Textbausteine je Stil
# umzuschreiben stünde für ein NIEDRIG-priorisiertes Feature außer
# Verhältnis, hier zählt vor allem der freie KI-Chat.
COMMUNICATION_STYLE_INSTRUCTIONS = {
    "kurz": "Antworte extrem knapp - möglichst ein Satz oder Stichpunkte, keine Füllwörter, keine Höflichkeitsfloskeln.",
    "freundlich": "Antworte freundlich und locker, wie ein hilfsbereiter Kumpel - ruhig auch mal ein Emoji.",
    "streng": "Antworte direkt und konsequent, wie ein strenger Vater - sag klar, wenn etwas liegen geblieben ist "
               "oder aus dem Ruder läuft, aber bleib fair, keine Beleidigungen.",
}


def _tone_instruction(style: str | None) -> str:
    return COMMUNICATION_STYLE_INSTRUCTIONS.get(style or "freundlich", COMMUNICATION_STYLE_INSTRUCTIONS["freundlich"])


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

    projects = crud.get_business_projects(db)
    if projects:
        lines.append("\nBusiness-Projekte (Nebenprojekte, für create_business_issue/resolve_business_issue/mark_project_checked NUR diese Namen verwenden):")
        for p in projects:
            lines.append(f"- „{p.name}“" + (f" ({p.open_issue_count} offene(r) Punkt(e))" if p.open_issue_count else ""))
        open_issues = crud.get_business_issues(db)[:10]
        if open_issues:
            lines.append("\nOffene Punkte in Business-Projekten:")
            for i in open_issues:
                lines.append(f"- [{i.project_name}] {i.title}")

    life_areas = crud.get_life_areas(db)
    if life_areas:
        lines.append("\nPersönliche Lebensbereiche (für life_checkin NUR diese Namen verwenden):")
        for a in life_areas:
            fortschritt = f" ({a.progress_percent}%)" if a.progress_percent is not None else ""
            lines.append(f"- „{a.name}“{fortschritt}")

    wishlist = crud.get_wishlist_items(db)
    if wishlist:
        lines.append("\nWunschliste:")
        for w in wishlist:
            preis = f" (Zielpreis {w.target_price:.2f} EUR)" if w.target_price else ""
            lines.append(f"- „{w.name}“{preis}")

    return "\n".join(lines)


# Pro eingehender Nachricht gesetzt (siehe _poll_once): wenn der Nutzer eine
# SPRACHnachricht geschickt hat UND settings.telegram_voice_replies an ist,
# steht hier das TTS-Objekt - _send() hängt dann an längere Antworten eine
# gesprochene Version (Telegram-Voice-Note) an.
_VOICE_REPLY: dict = {"tts": None}
_VOICE_ECHO_PREFIX = "🎤 verstanden:"


def _send_audio(token: str, chat_id: str, audio: bytes) -> None:
    """Antwort als Audio (Piper-WAV) - Telegram sendVoice will OGG/OPUS, für
    WAV nehmen wir sendAudio (spielt trotzdem im Chat ab)."""
    is_ogg = audio[:4] == b"OggS"
    method = "sendVoice" if is_ogg else "sendAudio"
    field = "voice" if is_ogg else "audio"
    fname = "antwort.ogg" if is_ogg else "antwort.wav"
    resp = requests.post(
        f"{TELEGRAM_API.format(token=token)}/{method}",
        data={"chat_id": chat_id},
        files={field: (fname, audio, "audio/ogg" if is_ogg else "audio/wav")},
        timeout=30,
    )
    resp.raise_for_status()


def _send(token: str, chat_id: str, text: str) -> None:
    resp = requests.post(
        f"{TELEGRAM_API.format(token=token)}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=15,
    )
    resp.raise_for_status()

    tts = _VOICE_REPLY["tts"]
    # Nur die eigentliche Antwort vertonen, nicht kurze Bestätigungen ("✓ …")
    # oder das "🎤 verstanden: …"-Echo.
    if tts and len(text.strip()) >= 40 and not text.lstrip().startswith(_VOICE_ECHO_PREFIX):
        try:
            audio = tts.speak(text)
            if audio:
                _send_audio(token, chat_id, audio)
        except Exception:
            pass


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


def _handle_cancel_termin_command(db, settings, token: str, chat_id: str, text: str) -> bool:
    match = _CANCEL_TERMIN_CMD_RE.match(text.strip())
    if not match:
        return False
    name_query = match.group(1)
    event, error = crud.cancel_calendar_event_by_name(db, name_query)
    if error:
        _send(token, chat_id, error)
        return True
    calendar_url = event.calendar_url or _first_calendar_url(settings)
    if calendar_url:
        try:
            radicale_sync.sync_calendar(db, calendar_url, settings.radicale_username,
                                         bank_sync.decrypt_secret(settings.secret_key, settings.radicale_password_encrypted))
        except Exception:
            pass
    _send(token, chat_id, f"✓ Termin „{event.title}“ am {event.start.strftime('%d.%m.%Y')} abgesagt.")
    return True


def _handle_status_command(db, settings, token: str, chat_id: str, text: str) -> bool:
    """Schickt den Digest sofort auf Zuruf, statt auf den nächsten der festen
    3-Stunden-Termine zu warten (main._scheduled_digest) - baut ihn mit den
    aktuell gültigen since/transfers_marked-Werten, rührt aber last_digest_
    sent_at/transfers_marked_since_digest NICHT an, damit der nächste
    planmäßige Digest weiterhin denselben Zeitraum abdeckt wie ohne /status."""
    if not _STATUS_CMD_RE.match(text.strip()):
        return False
    home_coords = (settings.home_lat, settings.home_lon) if settings.home_lat and settings.home_lon else None
    ors_api_key = (
        bank_sync.decrypt_secret(settings.secret_key, settings.openroute_api_key_encrypted)
        if settings.openroute_api_key_encrypted else None
    )
    space = crud.get_spaces(db)[0]
    text_out = crud.build_digest(
        db, space.id, home_coords=home_coords, ors_api_key=ors_api_key,
        since=settings.last_digest_sent_at, transfers_marked=settings.transfers_marked_since_digest or 0,
    )
    _send(token, chat_id, text_out)
    return True


def _create_project_issue(db, project_name: str, title: str) -> str:
    project, error = crud.find_business_project_by_name(db, project_name)
    if error:
        return error
    title = title.strip()
    if not title:
        return "Kein Titel für den offenen Punkt erkannt."
    project.last_checked_at = datetime.utcnow()
    db.commit()
    crud.create_business_issue(db, project.id, title)
    return f"✓ Offener Punkt bei „{project.name}“ angelegt: „{title}“."


def _resolve_project_issue(db, project_name: str, title_query: str) -> str:
    project, error = crud.find_business_project_by_name(db, project_name)
    if error:
        return error
    issue, error = crud.find_open_business_issue(db, project.id, title_query)
    if error:
        return error
    crud.resolve_business_issue(db, issue)
    return f"✓ „{issue.title}“ bei „{project.name}“ als erledigt markiert."


def _mark_project_checked(db, project_name: str) -> str:
    project, error = crud.find_business_project_by_name(db, project_name)
    if error:
        return error
    crud.mark_business_project_checked(db, project)
    return f"✓ „{project.name}“ als geprüft bestätigt."


def _handle_project_issue_command(db, settings, token: str, chat_id: str, text: str) -> bool:
    match = _PROJECT_ISSUE_CMD_RE.match(text.strip())
    if not match:
        return False
    project_name, title = match.groups()
    _send(token, chat_id, _create_project_issue(db, project_name, title))
    return True


def _handle_project_resolve_command(db, settings, token: str, chat_id: str, text: str) -> bool:
    match = _PROJECT_RESOLVE_CMD_RE.match(text.strip())
    if not match:
        return False
    project_name, title_query = match.groups()
    _send(token, chat_id, _resolve_project_issue(db, project_name, title_query))
    return True


def _handle_project_checked_command(db, settings, token: str, chat_id: str, text: str) -> bool:
    match = _PROJECT_CHECKED_CMD_RE.match(text.strip())
    if not match:
        return False
    _send(token, chat_id, _mark_project_checked(db, match.group(1)))
    return True


def _create_life_checkin(db, area_name: str, note: str) -> str:
    area, error = crud.find_life_area_by_name(db, area_name)
    if error:
        return error
    note = note.strip()
    if not note:
        return "Keine Notiz für den Check-in erkannt."
    crud.create_life_checkin(db, area.id, note)
    return f"✓ Check-in bei „{area.name}“ gespeichert: „{note}“."


def _handle_life_checkin_command(db, settings, token: str, chat_id: str, text: str) -> bool:
    match = _LIFE_CHECKIN_CMD_RE.match(text.strip())
    if not match:
        return False
    area_name, note = match.groups()
    _send(token, chat_id, _create_life_checkin(db, area_name, note))
    return True


def _add_wishlist_item(db, name: str, target_price: float | None = None) -> str:
    name = name.strip()
    if not name:
        return "Kein Name erkannt."
    item = crud.create_wishlist_item(db, schemas.WishlistItemCreate(name=name, target_price=target_price))
    preis = f" (Zielpreis {target_price:.2f} EUR)" if target_price else ""
    return f"✓ „{item.name}“ auf die Wunschliste{preis}."


def _mark_wishlist_checked(db, name: str) -> str:
    item, error = crud.find_wishlist_item_by_name(db, name)
    if error:
        return error
    crud.mark_wishlist_item_checked(db, item)
    return f"✓ „{item.name}“ als geprüft bestätigt."


def _handle_wishlist_add_command(db, settings, token: str, chat_id: str, text: str) -> bool:
    match = _WISHLIST_ADD_CMD_RE.match(text.strip())
    if not match:
        return False
    _send(token, chat_id, _add_wishlist_item(db, match.group(1)))
    return True


def _handle_wishlist_checked_command(db, settings, token: str, chat_id: str, text: str) -> bool:
    match = _WISHLIST_CHECKED_CMD_RE.match(text.strip())
    if not match:
        return False
    _send(token, chat_id, _mark_wishlist_checked(db, match.group(1)))
    return True


def _handle_quiet_command(db, settings, token: str, chat_id: str, text: str) -> bool:
    """/ruhe HH:MM setzt eine manuelle "Ruhe bis"-Überschreibung (siehe
    notifications._in_quiet_hours), /ruhe aus hebt sie vorzeitig auf. Nächster
    Tag, falls HH:MM heute schon vorbei ist - "/ruhe 8:00" um 20 Uhr abends
    gesagt meint offensichtlich morgen früh, nicht in der Vergangenheit
    (was sofort wirkungslos wäre)."""
    stripped = text.strip()
    if _QUIET_OFF_CMD_RE.match(stripped):
        settings.quiet_until = None
        db.commit()
        _send(token, chat_id, "🔔 Ruhe-Überschreibung aufgehoben.")
        return True
    match = _QUIET_CMD_RE.match(stripped)
    if not match:
        return False
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        _send(token, chat_id, "Ungültige Uhrzeit - Format /ruhe HH:MM.")
        return True
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    settings.quiet_until = target
    db.commit()
    _send(token, chat_id, f"🔕 Ruhe bis {target.strftime('%d.%m. %H:%M')} - nur wirklich Dringendes kommt noch durch.")
    return True


def _handle_proactive_command(db, settings, token: str, chat_id: str, text: str) -> bool:
    """/proaktiv steuert den proaktiven KI-Assistenten (siehe proactive.py):
    ohne Argument Status, "an"/"aus" schaltet ihn um, "pause [N]" legt ihn
    für N Stunden (Default 6) schlafen, ohne alle Benachrichtigungen stumm
    zu schalten."""
    m = _PROACTIVE_CMD_RE.match(text.strip())
    if not m:
        return False
    verb = (m.group(1) or "").lower()

    if verb in ("aus", "off"):
        settings.proactive_assistant_enabled = False
        db.commit()
        _send(token, chat_id, "🤖 Proaktiver Assistent aus. Wieder an mit /proaktiv an.")
        return True
    if verb in ("an", "ein", "on"):
        settings.proactive_assistant_enabled = True
        settings.proactive_assistant_snoozed_until = None
        db.commit()
        _send(token, chat_id, "🤖 Proaktiver Assistent an - meldet sich, sobald es etwas Nützliches gibt.")
        return True
    if verb in ("pause", "snooze"):
        hours = int(m.group(2)) if m.group(2) else 6
        hours = max(1, min(hours, 72))
        until = datetime.utcnow() + timedelta(hours=hours)
        settings.proactive_assistant_snoozed_until = until
        db.commit()
        local = datetime.now() + timedelta(hours=hours)
        _send(token, chat_id, f"🤖 Proaktiver Assistent pausiert bis {local.strftime('%d.%m. %H:%M')}.")
        return True

    # Nur "/proaktiv" -> Status
    if not settings.proactive_assistant_enabled:
        _send(token, chat_id, "🤖 Proaktiver Assistent ist aus. Einschalten: /proaktiv an")
    elif settings.proactive_assistant_snoozed_until and datetime.utcnow() < settings.proactive_assistant_snoozed_until:
        local = settings.proactive_assistant_snoozed_until + (datetime.now() - datetime.utcnow())
        _send(token, chat_id, f"🤖 Proaktiver Assistent an, aber pausiert bis {local.strftime('%d.%m. %H:%M')}.")
    else:
        _send(token, chat_id, "🤖 Proaktiver Assistent ist an. /proaktiv pause 6 für eine Pause, /proaktiv aus zum Abschalten.")
    return True


def _handle_proactive_feedback_command(db, settings, token: str, chat_id: str, text: str) -> bool:
    """/nützlich bzw. /unnötig - Bewertung der zuletzt gesendeten proaktiven
    Meldung. Wird als models.ProactiveFeedback gespeichert und beim nächsten
    Lauf über proactive._feedback_hint in den System-Prompt eingespeist, damit
    der Assistent seinen Ton nachjustiert."""
    m = _PROACTIVE_FEEDBACK_CMD_RE.match(text.strip())
    if not m:
        return False
    verb = m.group(1).lower()
    useful = verb.startswith("n") or verb == "gut"
    last = (settings.proactive_assistant_last_text or "").strip()
    if not last:
        _send(token, chat_id, "🤖 Mir liegt gerade keine letzte proaktive Meldung zum Bewerten vor.")
        return True
    db.add(models.ProactiveFeedback(text=last[:1000], useful=useful))
    db.commit()
    if useful:
        _send(token, chat_id, "🤖 Notiert - mehr in die Richtung. Danke!")
    else:
        _send(token, chat_id, "🤖 Verstanden - so etwas melde ich künftig seltener.")
    return True


def _handle_suggestion_reply(db, settings, token: str, chat_id: str, text: str) -> bool:
    """/ok, /später (oder /spaeter), /verwerfen - Antwort auf den aktuell
    einzigen offenen Jarvis-Vorschlag (siehe crud.decide_pending_suggestion)."""
    stripped = text.strip()
    if _SUGGESTION_OK_CMD_RE.match(stripped):
        decision = "accept"
    elif _SUGGESTION_LATER_CMD_RE.match(stripped):
        decision = "snooze"
    elif _SUGGESTION_DISMISS_CMD_RE.match(stripped):
        decision = "reject"
    else:
        return False
    _, reply = crud.decide_pending_suggestion(db, decision)
    _send(token, chat_id, reply)
    return True


def _handle_hanging_command(db, settings, token: str, chat_id: str, text: str) -> bool:
    if not _HANGING_CMD_RE.match(text.strip()):
        return False
    _send(token, chat_id, crud.build_hanging_summary(db))
    return True


def _handle_home_command(db, settings, token: str, chat_id: str, text: str) -> bool:
    """/haus <Befehl> - Smart-Home ueber dieselbe Pipeline wie der Web-Tab.
    Bestaetigung laeuft ueber '/haus ja' (process_command kennt "ja")."""
    m = _HOME_CMD_RE.match(text.strip())
    if not m:
        return False
    if not (settings.homeassistant_url and settings.homeassistant_token_encrypted):
        _send(token, chat_id, "Smart Home ist in der App noch nicht eingerichtet (Einstellungen -> Smart Home).")
        return True
    from . import jarvis
    res = jarvis.handle(db, settings, m.group(1).strip(), 0, source="telegram")
    reply = res.get("reply") or ("Erledigt." if res.get("ok") else "Das hat nicht geklappt.")
    if res.get("needs_confirmation"):
        reply += "\n\nZum Bestaetigen: /haus ja"
    _send(token, chat_id, reply)
    return True


def _handle_steuer_command(db, settings, token: str, chat_id: str, text: str) -> bool:
    """/steuer - die wichtigsten Steuer-Spar-Ansaetze auf Zuruf (regelbasiert,
    siehe tax_advice.generate_tips). Keine Steuerberatung."""
    if not _STEUER_CMD_RE.match(text.strip()):
        return False
    from . import tax_advice
    space = crud.get_spaces(db)[0]
    try:
        data = tax_advice.generate_tips(db, settings, space.id, date.today().year)
    except Exception as exc:  # noqa: BLE001
        _send(token, chat_id, f"Konnte die Steuer-Tipps nicht berechnen: {exc}")
        return True
    tips = data["tips"][:5]
    land = "Schweiz" if data["country"] == "CH" else "Deutschland"
    if not tips:
        _send(token, chat_id, f"🧾 Steuern ({land}): aktuell keine offensichtlichen Ansatzpunkte.")
        return True
    body = "\n\n".join(f"• {t['title']}\n{t['detail']}" for t in tips)
    _send(token, chat_id, f"🧾 Steuern sparen ({land}) – keine Steuerberatung:\n\n{body}")
    return True


def _handle_expense_command(db, settings, token: str, chat_id: str, text: str) -> bool:
    """/ausgabe <Konto>; <Betrag>; <Text> - schnelle Ausgabe (Spezifikation
    Abschnitt D). Legt die Buchung sofort an (Betrag als Ausgabe, also negativ,
    unabhängig vom Vorzeichen in der Nachricht - "/ausgabe Girokonto; 12,50;
    Rewe" ist eindeutig eine Ausgabe, kein Zwang für den Nutzer, ein Minus zu
    tippen). Kategorie NUR gesetzt, wenn eine bestehende feste Regel
    (eigene-regeln, siehe ai_auto._apply_deterministic_rules) sofort und
    ohne KI-Rateversuch zutrifft - sonst bleibt sie offen und wird wie jede
    andere unkategorisierte Buchung vom stündlichen Lauf (oder der KI-Review-
    Warteschlange) übernommen. Kein KI-Aufruf hier: der wäre bei einer
    Geldbuchung ("Kategorie vorschlagen") ein Ratespiel, keine feste Regel -
    passt nicht zu Leitprinzip 2."""
    match = _EXPENSE_CMD_RE.match(text.strip())
    if not match:
        return False
    account_query, amount_raw, description = match.groups()
    try:
        amount = -abs(float(amount_raw.replace(",", ".")))
    except ValueError:
        _send(token, chat_id, f"„{amount_raw}“ ist kein gültiger Betrag.")
        return True
    space = crud.get_spaces(db)[0]
    account, error = crud.find_account_by_name(db, space.id, account_query)
    if error:
        _send(token, chat_id, error)
        return True
    tx = crud.create_transaction(db, schemas.TransactionCreate(
        date=date.today(), amount=amount, description=description.strip(), account_id=account.id,
    ))
    kategorie_hinweis = "wird automatisch kategorisiert"
    categories = crud.get_categories(db)
    cat_by_name = {c.name.strip().lower(): c for c in categories}
    _, hits = ai_auto._apply_deterministic_rules([tx], cat_by_name)
    if hits:
        db.commit()
        matched_cat = next((c for c in cat_by_name.values() if c.id == tx.category_id), None)
        if matched_cat:
            kategorie_hinweis = f"Kategorie „{matched_cat.name}“ (per Regel erkannt)"
    _send(
        token, chat_id,
        f"✓ {abs(amount):.2f} € „{description.strip()}“ auf „{account.name}“ gebucht - {kategorie_hinweis}.",
    )
    return True


def _execute_action(db, settings, action: dict) -> str:
    """Führt einen von der KI erkannten Aktions-Block aus und gibt die
    Bestätigungs-/Fehlermeldung zurück, die dem Nutzer geschickt wird - nutzt
    dieselben crud-Funktionen wie die festen Kommandos (/todo, /erledigt,
    /termin, /termin_absagen), nur mit von der KI statt per Regex extrahierten
    Parametern. Jede Rückgabe macht explizit, was verstanden wurde, damit ein
    Missverständnis sofort auffällt."""
    action_type = action.get("type")

    if action_type == "create_todo":
        title = (action.get("title") or "").strip()
        if not title:
            return "Konnte kein To-Do-Titel erkannt werden."
        due_date = None
        if action.get("due_date"):
            try:
                due_date = date.fromisoformat(action["due_date"])
            except ValueError:
                pass
        todo = crud.create_todo(db, title, due_date)
        if settings.radicale_url:
            try:
                radicale_sync.sync(db, settings.radicale_url, settings.radicale_username,
                                    bank_sync.decrypt_secret(settings.secret_key, settings.radicale_password_encrypted))
            except Exception:
                pass
        return f"✓ To-Do „{todo.title}“ angelegt" + (f", fällig am {due_date.strftime('%d.%m.%Y')}." if due_date else ".")

    if action_type == "complete_todo":
        title = (action.get("title") or "").strip()
        if not title:
            # Leerer Suchbegriff wuerde in complete_todo_by_name jedes offene
            # To-Do treffen (leerer String ist Teilstring von allem) - bei
            # genau einem offenen To-Do sonst ein stiller Fehltreffer ohne
            # echte Nutzerabsicht.
            return "Konnte nicht erkennen, welches To-Do gemeint ist - bitte den Titel nennen."
        todo, error = crud.complete_todo_by_name(db, title)
        db.commit()
        return error or f"✓ „{todo.title}“ abgehakt."

    if action_type == "create_termin":
        title = (action.get("title") or "").strip()
        if not title or not action.get("date"):
            return "Konnte Titel oder Datum für den Termin nicht eindeutig erkennen - bitte genauer beschreiben."
        try:
            event_date = date.fromisoformat(action["date"])
        except ValueError:
            return f"„{action.get('date')}“ ist kein gültiges Datum."
        time_str = action.get("time")
        all_day = not time_str
        hour, minute = 0, 0
        if time_str:
            try:
                hour, minute = (int(p) for p in time_str.split(":"))
            except (ValueError, TypeError):
                all_day = True
        start = datetime(event_date.year, event_date.month, event_date.day, hour, minute)
        calendar_url = _first_calendar_url(settings)
        location = (action.get("location") or "").strip() or None
        event = crud.create_calendar_event(db, title, start, None, location, all_day, calendar_url)
        if calendar_url:
            try:
                radicale_sync.sync_calendar(db, calendar_url, settings.radicale_username,
                                             bank_sync.decrypt_secret(settings.secret_key, settings.radicale_password_encrypted))
            except Exception:
                pass
        when = "ganztägig" if all_day else start.strftime("%H:%M")
        return f"✓ Termin „{event.title}“ am {event_date.strftime('%d.%m.%Y')} ({when}) angelegt."

    if action_type == "cancel_termin":
        title = (action.get("title") or "").strip()
        if not title:
            # Dieselbe Absicherung wie bei complete_todo oben - leerer Titel
            # wuerde sonst bei genau einem anstehenden Termin diesen ohne
            # echten Treffer stumm absagen.
            return "Konnte nicht erkennen, welcher Termin gemeint ist - bitte den Titel nennen."
        event, error = crud.cancel_calendar_event_by_name(db, title)
        if error:
            return error
        calendar_url = event.calendar_url or _first_calendar_url(settings)
        if calendar_url:
            try:
                radicale_sync.sync_calendar(db, calendar_url, settings.radicale_username,
                                             bank_sync.decrypt_secret(settings.secret_key, settings.radicale_password_encrypted))
            except Exception:
                pass
        return f"✓ Termin „{event.title}“ am {event.start.strftime('%d.%m.%Y')} abgesagt."

    if action_type == "create_business_issue":
        project = (action.get("project") or "").strip()
        title = (action.get("title") or "").strip()
        if not project or not title:
            return "Konnte Projekt oder Titel nicht eindeutig erkennen - bitte genauer beschreiben."
        return _create_project_issue(db, project, title)

    if action_type == "resolve_business_issue":
        project = (action.get("project") or "").strip()
        title = (action.get("title") or "").strip()
        if not project or not title:
            return "Konnte nicht erkennen, welcher Punkt bei welchem Projekt gemeint ist - bitte genauer beschreiben."
        return _resolve_project_issue(db, project, title)

    if action_type == "mark_project_checked":
        project = (action.get("project") or "").strip()
        if not project:
            return "Konnte nicht erkennen, welches Projekt gemeint ist."
        return _mark_project_checked(db, project)

    if action_type == "life_checkin":
        area = (action.get("area") or "").strip()
        note = (action.get("note") or "").strip()
        if not area or not note:
            return "Konnte Lebensbereich oder Notiz nicht eindeutig erkennen - bitte genauer beschreiben."
        result = _create_life_checkin(db, area, note)
        percent = action.get("progress_percent")
        if percent is not None and result.startswith("✓"):
            life_area, error = crud.find_life_area_by_name(db, area)
            if life_area and not error:
                try:
                    life_area.progress_percent = max(0, min(100, int(percent)))
                    db.commit()
                    result += f" Fortschritt auf {life_area.progress_percent}% gesetzt."
                except (TypeError, ValueError):
                    pass
        return result

    if action_type == "add_wishlist_item":
        name = (action.get("name") or "").strip()
        if not name:
            return "Konnte nicht erkennen, was auf die Wunschliste soll."
        price = action.get("target_price")
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None
        return _add_wishlist_item(db, name, price)

    if action_type == "mark_wishlist_checked":
        name = (action.get("name") or "").strip()
        if not name:
            return "Konnte nicht erkennen, welcher Wunschlisten-Eintrag gemeint ist."
        return _mark_wishlist_checked(db, name)

    return "Konnte die Anfrage nicht eindeutig einer Aktion zuordnen."


def _handle_message(db, settings, token: str, chat_id: str, text: str) -> None:
    if _handle_balance_command(db, token, chat_id, text):
        return
    if _handle_todo_command(db, settings, token, chat_id, text):
        return
    if _handle_done_command(db, settings, token, chat_id, text):
        return
    if _handle_cancel_termin_command(db, settings, token, chat_id, text):
        return
    if _handle_termin_command(db, settings, token, chat_id, text):
        return
    if _handle_status_command(db, settings, token, chat_id, text):
        return
    if _handle_project_resolve_command(db, settings, token, chat_id, text):
        return
    if _handle_project_checked_command(db, settings, token, chat_id, text):
        return
    if _handle_project_issue_command(db, settings, token, chat_id, text):
        return
    if _handle_life_checkin_command(db, settings, token, chat_id, text):
        return
    if _handle_wishlist_checked_command(db, settings, token, chat_id, text):
        return
    if _handle_wishlist_add_command(db, settings, token, chat_id, text):
        return
    if _handle_quiet_command(db, settings, token, chat_id, text):
        return
    if _handle_proactive_command(db, settings, token, chat_id, text):
        return
    if _handle_proactive_feedback_command(db, settings, token, chat_id, text):
        return
    if _handle_suggestion_reply(db, settings, token, chat_id, text):
        return
    if _handle_hanging_command(db, settings, token, chat_id, text):
        return
    if _handle_home_command(db, settings, token, chat_id, text):
        return
    if _handle_expense_command(db, settings, token, chat_id, text):
        return
    if _handle_steuer_command(db, settings, token, chat_id, text):
        return

    # Freier Text, der klar das Haus meint ("mach das licht im bad aus") -
    # ohne vorangestelltes /haus durch dieselbe Jarvis-Schicht schicken.
    if settings.homeassistant_url and settings.homeassistant_token_encrypted:
        from . import jarvis
        if jarvis._is_house_command(db, settings, text):
            res = jarvis.handle(db, settings, text, 0, source="telegram")
            reply = res.get("reply") or ("Erledigt." if res.get("ok") else "Das hat nicht geklappt.")
            if res.get("needs_confirmation"):
                reply += "\n\nZum Bestaetigen: /haus ja"
            _send(token, chat_id, reply)
            return

    chat_model = settings.ollama_model or settings.beleg_chat_model
    if not settings.ollama_url or not chat_model:
        _send(token, chat_id, "Ollama ist in der App noch nicht unter Einstellungen eingerichtet.")
        return

    space = crud.get_spaces(db)[0]
    today = date.today()
    weekday_de = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"][today.weekday()]
    heute_zeile = f"\n\nHeutiges Datum: {today.isoformat()} ({weekday_de})."
    system_content = (
        TELEGRAM_SYSTEM_PROMPT + heute_zeile + "\n\n" + _tone_instruction(settings.communication_style)
        + "\n\n" + _context_facts(db, space.id)
    )
    messages = [{"role": "system", "content": system_content}]
    messages.extend(_history[-MAX_HISTORY:])
    messages.append({"role": "user", "content": text})

    reply = ollama_client.chat(settings.ollama_url, chat_model, messages)

    action_match = _ACTION_BLOCK_RE.search(reply)
    if action_match:
        try:
            action = json.loads(action_match.group(1).strip())
            confirmation = _execute_action(db, settings, action)
        except (json.JSONDecodeError, AttributeError):
            confirmation = "Habe die Anfrage nicht als eindeutige Aktion verstanden - bitte anders formulieren " \
                            "oder das passende Kommando nutzen (/todo, /erledigt, /termin, /termin_absagen)."
        _history.append({"role": "user", "content": text})
        _history.append({"role": "assistant", "content": confirmation})
        del _history[:-MAX_HISTORY]
        _send(token, chat_id, confirmation)
        return

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


def _transcribe_voice(token: str, file_id: str) -> str:
    """Telegram-Sprachnachricht (.oga/Opus) herunterladen und lokal per
    voice.get_stt() zu Text machen - kein Cloud-STT. Wirft weiter, wenn kein
    STT-Backend aktiv ist (STT_BACKEND=stub) oder der Download scheitert."""
    info = requests.get(
        f"{TELEGRAM_API.format(token=token)}/getFile",
        params={"file_id": file_id}, timeout=20,
    )
    info.raise_for_status()
    file_path = info.json()["result"]["file_path"]
    audio = requests.get(
        f"https://api.telegram.org/file/bot{token}/{file_path}", timeout=60,
    )
    audio.raise_for_status()
    return voice.get_stt().transcribe(audio.content).strip()


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

        # Sprachnachricht (oder gesendete Audiodatei / Video-Notiz) -> lokal
        # zu Text machen und dann wie eine getippte Nachricht behandeln.
        was_voice = False
        if not text and incoming_chat_id == configured_chat_id:
            media = msg.get("voice") or msg.get("audio") or msg.get("video_note")
            if media and media.get("file_id"):
                was_voice = True
                try:
                    text = _transcribe_voice(token, media["file_id"])
                except NotImplementedError:
                    _send(token, configured_chat_id,
                          "Sprachnachrichten brauchen einen Spracherkennungs-Dienst. In der "
                          "App STT_BACKEND=faster-whisper (eigenes Image) oder STT_BACKEND=http "
                          "mit WHISPER_HTTP_URL setzen.")
                except Exception as e:  # noqa: BLE001
                    _send(token, configured_chat_id, f"Sprachnachricht konnte nicht verarbeitet werden: {e}")
                if text:
                    _send(token, configured_chat_id, f"{_VOICE_ECHO_PREFIX} „{text}“")

        # Auf eine Sprachnachricht ggf. auch gesprochen antworten
        if was_voice and text and getattr(settings, "telegram_voice_replies", False):
            try:
                _VOICE_REPLY["tts"] = voice.get_tts()
            except Exception:
                _VOICE_REPLY["tts"] = None
        else:
            _VOICE_REPLY["tts"] = None

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

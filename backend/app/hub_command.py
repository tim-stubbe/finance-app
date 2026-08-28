"""Universelle Hub-Kommandozeile.

Ein Eingabefeld im Hub, das per Ollama-Intent in die passende Domaene routet
(Smart Home, To-do, Kalender, Wunschliste, Ausgabe, Frage, Navigation) -
statt fester Slash-Syntax wie beim Telegram-Bot.

Leitprinzip: irreversible / geldbezogene Aktionen werden NUR vorgeschlagen
(der Nutzer bucht selbst), alles andere direkt mit kurzer Rueckmeldung.
Faellt nichts, antwortet Ollama frei bzw. beantwortet eine Frage mit
Faktenkontext. Einzige KI: die lokale Ollama-Instanz.
"""

import re
from datetime import date, datetime

from . import crud, schemas, ollama_client, smarthome

NAV_TABS = {
    "hub", "dashboard", "transactions", "accounts", "recurring", "categories",
    "investments", "business", "debts", "goals", "ai", "photos", "trips",
    "projects", "life", "wishlist", "vehicle", "smarthome", "settings",
}

SYSTEM = (
    "Du bist der Assistent von Kies (Finanz- und Life-OS). Ordne die Eingabe "
    "GENAU EINER Domaene zu und antworte NUR mit einem JSON-Objekt:\n"
    '{"domain": "...", "reply": "kurze Antwort auf Deutsch", ...domain-Felder...}\n\n'
    "Domaenen:\n"
    '- "smarthome": {"text": "<Steuer-/Abfragebefehl fuers Haus>"} - Licht, '
    "Rollladen, Heizung, Geraetezustand.\n"
    '- "todo": {"title": "...", "due": "YYYY-MM-DD" oder null}\n'
    '- "termin": {"title": "...", "date": "YYYY-MM-DD", "time": "HH:MM" oder null, "location": null}\n'
    '- "wunschliste": {"name": "...", "price": Zahl oder null}\n'
    '- "ausgabe": {"amount": Zahl, "merchant": "...", "note": "..."} - wird NICHT '
    "gebucht, nur vorgeschlagen.\n"
    f'- "navigation": {{"tab": "einer von: {", ".join(sorted(NAV_TABS))}"}}\n'
    '- "frage": {} - Frage zu den eigenen Daten/Finanzen; beantworte sie in reply.\n'
    '- "chat": {} - Smalltalk / alles andere.\n'
    '- "clarify": {} - unklar, Rueckfrage in reply.\n'
    "Heutiges Datum: {today}."
)


def _num(v):
    try:
        return round(float(str(v).replace(",", ".")), 2)
    except (TypeError, ValueError):
        return None


def _parse_date(v):
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _r(ok, domain, reply, **extra):
    return {"ok": ok, "domain": domain, "reply": reply, **extra}


def route(db, settings, text: str, space_id: int, confirm: bool = False) -> dict:
    text = (text or "").strip()
    if not text:
        return _r(False, "chat", "Bitte etwas eingeben.")
    if not settings.ollama_url or not settings.ollama_model:
        return _r(False, "chat", "Kein Ollama-Modell eingerichtet (Einstellungen -> KI-Assistent).")

    system = SYSTEM.replace("{today}", date.today().isoformat())
    try:
        raw = ollama_client.chat(
            settings.ollama_url, settings.ollama_model,
            [{"role": "system", "content": system}, {"role": "user", "content": text}],
            timeout=120,
        )
    except Exception as exc:  # noqa: BLE001
        return _r(False, "chat", f"KI nicht erreichbar: {exc}")

    try:
        p = smarthome.parse_json_lenient(raw)
    except ValueError:
        return _r(True, "chat", re.sub(r"```.*?```", "", raw, flags=re.DOTALL).strip()[:600] or "Ok.")

    domain = (p.get("domain") or "chat").lower()
    reply = (p.get("reply") or "").strip()

    if domain == "smarthome":
        res = smarthome.process_command(db, settings, p.get("text") or text,
                                        confirm=confirm, source="hub")
        res["domain"] = "smarthome"
        return res

    if domain == "todo":
        title = (p.get("title") or "").strip()
        if not title:
            return _r(False, "todo", "Worum geht es beim To-do?")
        due = _parse_date(p.get("due"))
        todo = crud.create_todo(db, title, due)
        return _r(True, "todo", reply or (f"To-do „{todo.title}“ angelegt"
                  + (f", fällig {due.strftime('%d.%m.%Y')}." if due else ".")))

    if domain == "termin":
        title = (p.get("title") or "").strip()
        d = _parse_date(p.get("date"))
        if not title or not d:
            return _r(False, "termin", "Für den Termin brauche ich Titel und Datum.")
        tm = (p.get("time") or "").strip()
        all_day = not tm
        hh, mm = (tm.split(":") + ["0", "0"])[:2] if tm else ("0", "0")
        start = datetime(d.year, d.month, d.day, int(hh or 0), int(mm or 0))
        cal_url = getattr(settings, "radicale_calendar_url", None)
        ev = crud.create_calendar_event(db, title, start, None,
                                        (p.get("location") or "").strip() or None,
                                        all_day, cal_url)
        return _r(True, "termin", reply or (f"Termin „{ev.title}“ am {d.strftime('%d.%m.%Y')}"
                  + (f" um {tm}." if tm else " (ganztägig).")))

    if domain == "wunschliste":
        name = (p.get("name") or "").strip()
        if not name:
            return _r(False, "wunschliste", "Was soll auf die Wunschliste?")
        item = crud.create_wishlist_item(
            db, schemas.WishlistItemCreate(name=name, target_price=_num(p.get("price"))))
        return _r(True, "wunschliste", reply or f"„{item.name}“ auf die Wunschliste.")

    if domain == "ausgabe":
        amount = _num(p.get("amount"))
        merchant = (p.get("merchant") or "").strip()
        return _r(True, "ausgabe",
                  reply or (f"Vorschlag: {amount:.2f} € bei {merchant or '?'} – "
                            "im Buchungen-Tab prüfen und eintragen." if amount
                            else "Trag die Ausgabe im Buchungen-Tab ein."),
                  route="expense", params={"amount": amount, "merchant": merchant,
                                           "note": (p.get("note") or "").strip()})

    if domain == "navigation":
        tab = (p.get("tab") or "").strip().lower()
        if tab not in NAV_TABS:
            return _r(True, "clarify", reply or "Welchen Bereich soll ich öffnen?")
        return _r(True, "navigation", reply or f"Öffne {tab}.", tab=tab)

    if domain == "clarify":
        return _r(True, "clarify", reply or "Kannst du das genauer sagen?")

    # frage / chat -> zweiter Ollama-Call mit Faktenkontext
    try:
        from .telegram_bot import _context_facts, TELEGRAM_SYSTEM_PROMPT
        facts = _context_facts(db, space_id)
        answer = ollama_client.chat(
            settings.ollama_url, settings.ollama_model,
            [{"role": "system", "content": TELEGRAM_SYSTEM_PROMPT + "\n\n" + facts},
             {"role": "user", "content": text}],
            timeout=120,
        )
        answer = re.sub(r"```.*?```", "", answer, flags=re.DOTALL).strip()
        return _r(True, "frage" if domain == "frage" else "chat", answer or reply or "Ok.")
    except Exception as exc:  # noqa: BLE001
        return _r(True, "chat", reply or f"Ich konnte das nicht beantworten: {exc}")

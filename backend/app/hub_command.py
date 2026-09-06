"""Universelle Hub-Kommandozeile.

Ein Eingabefeld im Hub, das per Ollama-Intent in die passende Domaene routet
(Smart Home, To-do, Kalender, Wunschliste, Ausgabe, Frage, Navigation) -
statt fester Slash-Syntax wie beim Telegram-Bot.

Leitprinzip: irreversible / geldbezogene Aktionen werden NUR vorgeschlagen
(der Nutzer bucht selbst), alles andere direkt mit kurzer Rueckmeldung.
Faellt nichts, übernimmt der Kies Agent Core: private Daten werden nur über
gezielte Tools geholt, aktuelle Fragen können Web-Recherche nutzen. Die
bestehenden Aktions-Domänen bleiben unverändert.
"""

import re
from datetime import date, datetime

from . import agent_core, crud, schemas, ollama_client, smarthome

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
    '- "frage": {} - Frage zu eigenen Daten, Finanzen, Organisation, Steuer/Recht oder aktuellem Wissen.\n'
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
        # Falls schon der Intent-Classifier nur Freitext liefert, geben wir die
        # ursprüngliche Frage trotzdem an den Agent Core statt private Daten als
        # pauschalen Faktenblock anzuhängen.
        return agent_core.handle(db, settings, text, space_id)

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

    # frage / chat -> Agent Core. Anders als der alte _context_facts-Pfad
    # bekommt das Modell nicht mehr vorsorglich alle Finanz-/Life-Daten, sondern
    # ruft nur die für diese Frage benötigten Tools ab. Aktuelle Steuer-/Rechts-
    # fragen erzwingen dort zuerst Web-Recherche.
    return agent_core.handle(db, settings, text, space_id)

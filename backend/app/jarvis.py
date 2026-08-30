"""Einheitliche Jarvis-Intent-Schicht - EIN Einstieg für Text/Sprache.

Ziel (siehe CLAUDE.md "Life OS"): egal ob der Befehl per Web-Kommandozeile,
Telegram (`/haus`, freier Bot), Voice oder Cockpit kommt - er läuft durch
`jarvis.handle()` und kommt in derselben Struktur zurück:

    {"ok": bool, "reply": str, "actions": [...], "domain": str}

Routing (in dieser Reihenfolge, Schnellpfade OHNE Ollama zuerst):

  1. Kurzzeitgedächtnis auflösen  ("mach das aus", "und heller")  -> Haus
  2. Haus: Alias/Anzeigename + Stichwort            -> smarthome.process_command
  3. Alltag per Regex:  "was hängt", "kalender heute",
     "todo: …", "… abhaken"                        -> direkte crud-Aufrufe
  4. Finanzen NUR lesend:  "saldo", "kontostand"    -> crud (read-only)
  5. sonst  -> hub_command.route()  (Ollama-Intent inkl. Haus/Chat/Frage)

Nichts wird hier doppelt gebaut: Haus geht weiter über
`smarthome.process_command` (Aliase, Allowlist, Bestätigungs-Flow), unklare
Fälle über `hub_command.route`. Diese Schicht ist nur die schnelle,
regelbasierte Vorsortierung + das Kurzzeitgedächtnis darüber.
"""

import re
from datetime import date, datetime, timedelta

from . import crud, hub_command, smarthome

# --------------------------------------------------------------------------
# Kurzzeitgedächtnis (F) - Single-User, deshalb ein Modul-Dict, analog zu
# smarthome._LAST_PENDING. Hält die letzte aufgelöste Entity / Raum / Intent,
# damit sich "mach das aus" / "und dimm auf 30%" darauf beziehen kann.
# --------------------------------------------------------------------------
_MEMORY: dict = {
    "entity_id": None, "friendly": None, "area": None,
    "domain": None, "intent": None, "updated_at": None,
}
_MEMORY_MINUTES_DEFAULT = 10


def _memory_ttl(settings) -> int:
    return int(getattr(settings, "jarvis_memory_minutes", None) or _MEMORY_MINUTES_DEFAULT)


def recall(settings) -> dict | None:
    """Frischer Gedächtnis-Eintrag oder None (nach Timeout)."""
    ts = _MEMORY.get("updated_at")
    if not ts:
        return None
    if datetime.utcnow() - ts > timedelta(minutes=_memory_ttl(settings)):
        return None
    return dict(_MEMORY)


def remember(*, entity_id=None, friendly=None, area=None, domain=None, intent=None) -> None:
    if entity_id:
        _MEMORY.update(entity_id=entity_id, friendly=friendly, area=area, domain=domain)
    if intent:
        _MEMORY["intent"] = intent
    _MEMORY["updated_at"] = datetime.utcnow()


def forget() -> None:
    _MEMORY.update(entity_id=None, friendly=None, area=None, domain=None,
                   intent=None, updated_at=None)


# Folgebefehl ohne eigenes Geräte-/Raumwort ("das", "es", "auch", "und …",
# "wieder an", "heller", "wärmer") - dann greift das Gedächtnis.
_FOLLOWUP_RE = re.compile(
    r"^(und |auch |das |die |der |es |die auch |nochmal |wieder )?"
    r"(mach(s| es| das)?|schalt|stell|dimm|dreh|heller|dunkler|wärmer|kälter|lauter|leiser|"
    r"aus|an|ein|zu|auf|hoch|runter|weiter|stopp?)\b",
    re.IGNORECASE,
)
_HAS_NOUN_RE = re.compile(
    r"licht|lampe|lampen|rollo|rolllad|jalousie|vorhang|heiz|klima|thermostat|"
    r"steckdose|schalter|ventilator|fernseh|tv|musik|player|szene|"
    r"küche|kueche|wohnzimmer|schlafzimmer|bad|flur|büro|buero|garage|zimmer|raum",
    re.IGNORECASE,
)


def _looks_like_followup(text: str) -> bool:
    t = text.strip().lower()
    if len(t) > 40:
        return False
    if _HAS_NOUN_RE.search(t):
        return False
    return bool(_FOLLOWUP_RE.match(t))


# --------------------------------------------------------------------------
# Alltags-Schnellpfade (Regex, ohne Ollama)
# --------------------------------------------------------------------------
_HANGING_RE = re.compile(r"\b(was h[äa]ngt|h[äa]ngt (noch|was)|offene punkte|todo.?liste offen)\b", re.IGNORECASE)
_CAL_TODAY_RE = re.compile(r"\b(kalender|termin[e]?)\b.*\b(heute|jetzt|an|gleich)\b|^termine heute", re.IGNORECASE)
_TODO_ADD_RE = re.compile(r"^\s*(todo|aufgabe|merk[e]?|to-?do)\s*[:\-]?\s+(.{2,})$", re.IGNORECASE)
_TODO_DONE_RE = re.compile(r"^\s*(.{2,}?)\s+(abhaken|erledigt|abgehakt|fertig)\s*$", re.IGNORECASE)
_SALDO_RE = re.compile(r"\b(saldo|kontostand|wie viel .* konto|was ist auf .* konto)\b", re.IGNORECASE)


def _r(ok, domain, reply, **extra):
    return {"ok": ok, "domain": domain, "reply": reply, "actions": extra.pop("actions", []), **extra}


def _hanging_reply(db) -> str:
    h = crud.get_hanging_items(db)
    parts = []
    if h["todos_overdue"]:
        parts.append("Überfällig: " + "; ".join(t.title for t in h["todos_overdue"][:6]))
    if h["todos_no_date"]:
        parts.append("Ohne Datum liegen lange: " + "; ".join(t.title for t in h["todos_no_date"][:6]))
    if h["business_issues"]:
        parts.append("Business offen: " + "; ".join(i.title for i in h["business_issues"][:6]))
    return "\n".join(parts) if parts else "Nichts hängt – alles im grünen Bereich."


def _calendar_today_reply(db) -> str:
    evs = crud.get_upcoming_calendar_events(db, days=1, limit=12)
    today = date.today().isoformat()
    todays = [e for e in evs if (e.start or "")[:10] == today]
    if not todays:
        return "Heute stehen keine Termine an."
    return "Heute: " + "; ".join(
        f"{e.title} ({(e.start or '')[11:16] or 'ganztägig'})" for e in todays)


def _saldo_reply(db, space_id: int) -> str:
    accounts = crud.get_accounts(db, space_id)
    if not accounts:
        return "Es sind keine Konten angelegt."
    rows = [(a.name, crud.account_balance(db, a)) for a in accounts]
    total = sum(b for _, b in rows)
    top = "; ".join(f"{n}: {b:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
                    for n, b in rows[:6])
    return f"{top}  —  Summe: {total:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


# --------------------------------------------------------------------------
# Öffentliche API
# --------------------------------------------------------------------------
def handle(db, settings, text: str, space_id: int, *, source: str = "text",
           confirm: bool = False) -> dict:
    """DER eine Einstieg. Wirft nie - Fehler kommen als ok=False."""
    text = (text or "").strip()
    if not text:
        return _r(False, "chat", "Bitte einen Befehl eingeben.")
    if not space_id:
        spaces = crud.get_spaces(db)
        space_id = spaces[0].id if spaces else 1

    low = text.lower()

    # 1) Kurzzeitgedächtnis: Folgebefehl auf das zuletzt gesteuerte Gerät
    mem = recall(settings)
    if mem and mem.get("friendly") and _looks_like_followup(text):
        merged = f"{text} {mem['friendly']}"
        res = smarthome.process_command(db, settings, merged, confirm=confirm, source=source)
        _absorb_memory(res, mem, settings)
        return _shape(res, "smarthome")

    # 2) Haus-Schnellpfad: klarer Geräte-/Raumbezug ODER Bestätigungswort bei
    #    offener Rückfrage -> direkt an die HA-Pipeline (die ihren eigenen
    #    Schnellpfad + LLM-Fallback + Bestätigungs-Flow hat).
    if _is_house_command(db, settings, text) or (confirm and smarthome._LAST_PENDING["action"]):
        res = smarthome.process_command(db, settings, text, confirm=confirm, source=source)
        _absorb_memory(res, None, settings)
        return _shape(res, "smarthome")

    # 3) Alltags-Regex ohne Ollama
    if _HANGING_RE.search(low):
        return _r(True, "alltag", _hanging_reply(db))
    if _CAL_TODAY_RE.search(low):
        return _r(True, "alltag", _calendar_today_reply(db))
    m = _TODO_ADD_RE.match(text)
    if m:
        todo = crud.create_todo(db, m.group(2).strip(), None)
        return _r(True, "alltag", f"To-do „{todo.title}“ notiert.",
                  actions=[{"type": "todo_created", "id": todo.id}])
    m = _TODO_DONE_RE.match(text)
    if m:
        todo, _err = crud.complete_todo_by_name(db, m.group(1).strip())
        if todo:
            return _r(True, "alltag", f"„{todo.title}“ abgehakt.")
        # kein/mehrdeutiger Treffer -> weiter zum LLM-Router (könnte was anderes sein)

    # 4) Finanzen NUR lesend
    if _SALDO_RE.search(low):
        return _r(True, "finanzen", _saldo_reply(db, space_id))

    # 5) Alles andere -> bestehender Ollama-Router (Haus/Chat/Frage/Nav/…)
    res = hub_command.route(db, settings, text, space_id, confirm=confirm)
    if res.get("domain") == "smarthome":
        _absorb_memory(res, None, settings)
    return _shape(res, res.get("domain") or "chat")


# --------------------------------------------------------------------------
# Intern
# --------------------------------------------------------------------------
def _shape(res: dict, domain: str) -> dict:
    """Vereinheitlicht die Antwort auf {ok, reply, actions, domain}."""
    return {
        "ok": bool(res.get("ok", True)),
        "reply": res.get("reply") or "Ok.",
        "actions": res.get("actions") or [],
        "domain": res.get("domain") or domain,
        # Zusatzfelder der Haus-Pipeline durchreichen (UI nutzt sie)
        **{k: res[k] for k in ("intent", "needs_confirmation", "candidates", "tab", "route", "params")
           if k in res},
    }


def _is_house_command(db, settings, text: str) -> bool:
    """Billig entscheiden, ob das ein Haus-Befehl ist: passt ein Alias oder
    Anzeigename UND eine simple an/aus/dimm-Absicht? Dann ja. Kein HA
    eingerichtet -> immer nein (dann übernimmt der LLM-Router / Chat)."""
    if not getattr(settings, "homeassistant_url", None) or not smarthome._token(settings):
        return False
    if not smarthome.parse_fast_intent(text):
        return False
    try:
        states = smarthome._get_states(settings)
    except Exception:
        states = []
    if smarthome.match_aliases(text, smarthome._load_aliases(db)):
        return True
    return bool(smarthome.match_by_friendly_name(text, states, smarthome._allowed_domains(settings)))


def _absorb_memory(res: dict, prev_mem: dict | None, settings=None) -> None:
    """Nach einer Haus-Aktion: gesteuerte Entity ins Gedächtnis übernehmen."""
    acts = res.get("actions") or []
    ent = next((a.get("entity_id") for a in acts if a.get("entity_id")), None)
    if not ent and res.get("candidates") and len(res["candidates"]) == 1:
        ent = res["candidates"][0]
    if ent:
        friendly = _friendly_from_actions(acts, ent) or _friendly_from_states(settings, ent) or ent
        remember(entity_id=ent, friendly=friendly,
                 domain=ent.split(".")[0], intent=res.get("intent"))
    elif prev_mem:
        remember(intent=res.get("intent"))


def _friendly_from_actions(acts, ent):
    for a in acts:
        if a.get("entity_id") == ent and a.get("friendly"):
            return a["friendly"]
    return None


def _friendly_from_states(settings, ent):
    if not settings:
        return None
    try:
        for st in smarthome._get_states(settings):
            if st.get("entity_id") == ent:
                return st.get("attributes", {}).get("friendly_name")
    except Exception:
        pass
    return None



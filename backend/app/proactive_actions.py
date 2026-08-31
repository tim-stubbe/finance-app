"""Feste Allowlist der Aktionen, die der proaktive Assistent hinter einer
Vorschlags-Option auslösen darf (siehe proactive.py, models.ProactiveProposal).

Grundregel wie überall im Projekt: die KI wählt nur `type` + `params` aus
diesem Katalog. Es gibt hier absichtlich NICHTS, was Geld bewegt, Daten
löscht oder ein Gerät ohne Rückfrage schaltet - nur kleine, umkehrbare
Organisations-Handgriffe, die Tim sonst selbst im UI machen müsste.

Jeder Handler: execute(db, settings, params) -> kurzer deutscher Ergebnistext.
Unbekannter/ungültiger `type` -> die Option wird beim Anlegen zu reiner Info
degradiert (keine Aktion), siehe proactive._sanitize_options.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from . import crud, models, schemas

_PURPOSES = ("geschaeftlich", "privat")


def _q(s) -> str:
    return "»" + str(s) + "«"


def _todo_add(db, settings, p) -> str:
    title = (p.get("title") or "").strip()
    if not title:
        raise ValueError("todo_add ohne title")
    due = None
    raw = p.get("due_date")
    if raw:
        try:
            due = date.fromisoformat(str(raw)[:10])
        except ValueError:
            due = None
    t = crud.create_todo(db, title, due)
    tail = f" (fällig {due.isoformat()})" if due else ""
    return f"To-do {_q(t.title)} angelegt{tail}."


def _todo_done(db, settings, p) -> str:
    query = (p.get("title") or p.get("match") or "").strip()
    if not query:
        raise ValueError("todo_done ohne title")
    todo, err = crud.complete_todo_by_name(db, query)
    if todo:
        return f"{_q(todo.title)} abgehakt."
    return err or "Kein passendes To-do gefunden."


def _note_add(db, settings, p) -> str:
    text = (p.get("text") or "").strip()
    if not text:
        raise ValueError("note_add ohne text")
    et = p.get("entity_type") or "schweiz"
    eid = int(p.get("entity_id") or 0)
    if et not in schemas.NOTE_ENTITY_TYPES:
        et, eid = "schweiz", 0
    crud.create_note(db, schemas.NoteCreate(entity_type=et, entity_id=eid, text=text))
    return "Notiz gespeichert."


_GOAL_STATUS_MAP = {"done": "completed", "erreicht": "completed", "fertig": "completed",
                    "completed": "completed", "open": "open", "offen": "open",
                    "archived": "archived", "archiviert": "archived"}


def _goal_status(db, settings, p) -> str:
    gid = int(p.get("goal_id") or 0)
    status = _GOAL_STATUS_MAP.get((p.get("status") or "done").lower(), "completed")
    spaces = crud.get_spaces(db)
    sid = int(spaces[0].id) if spaces else 1
    g = crud.get_goal(db, gid, sid)
    if not g:
        return "Ziel nicht gefunden."
    crud.update_goal(db, gid, sid, schemas.GoalUpdate(status=models.GoalStatus(status)))
    return f"Ziel {_q(g.title)} auf {_q(status)} gesetzt."


def _trips_classify_all(db, settings, p) -> str:
    purpose = p.get("purpose")
    if purpose not in _PURPOSES:
        raise ValueError("trips_classify_all: purpose muss geschaeftlich|privat sein")
    veh = db.query(models.Vehicle).order_by(models.Vehicle.id).first()
    if not veh:
        return "Kein Fahrzeug angelegt."
    rows = db.query(models.VehicleTrip).filter_by(vehicle_id=veh.id, purpose="unbekannt").all()
    for t in rows:
        t.purpose = purpose
    db.commit()
    return f"{len(rows)} unklassifizierte Fahrt(en) auf {_q(purpose)} gesetzt."


def _meal_plan_fill(db, settings, p) -> str:
    try:
        from . import crud_meals
        res = crud_meals.suggest_and_fill_week(db, settings)
        return res if isinstance(res, str) else "Wochenplan mit Vorschlägen gefüllt."
    except Exception:
        return ("Öffne den Essen-Tab und tippe auf KI-Vorschläge - automatisches "
                "Füllen ist hier noch nicht verdrahtet.")


def _open(db, settings, p) -> str:
    tab = (p.get("tab") or "").strip()
    return f"Alles klar - schau im Tab {_q(tab)} nach." if tab else "Alles klar."


def _remind_later(db, settings, p) -> str:
    days = max(int(p.get("days") or 1), 1)
    settings.proactive_assistant_snoozed_until = datetime.utcnow() + timedelta(days=days)
    db.commit()
    return f"Okay, ich melde mich in {days} Tag(en) wieder."


def _dismiss(db, settings, p) -> str:
    return "Erledigt, ignoriere ich."


REGISTRY = {
    "todo_add": _todo_add,
    "todo_done": _todo_done,
    "note_add": _note_add,
    "goal_status": _goal_status,
    "trips_classify_all": _trips_classify_all,
    "meal_plan_fill": _meal_plan_fill,
    "open": _open,
    "remind_later": _remind_later,
    "dismiss": _dismiss,
}

# Für den LLM-Prompt: knappe Beschreibung jeder erlaubten Aktion.
CATALOG_FOR_PROMPT = (
    "todo_add {title, due_date?}   - neues To-do\n"
    "todo_done {title}             - To-do abhaken (Textsuche)\n"
    "note_add {text}              - Notiz ablegen\n"
    "goal_status {goal_id, status} - Ziel-Status setzen (open|done|archived)\n"
    "trips_classify_all {purpose} - alle unklassifizierten Fahrten auf geschaeftlich|privat\n"
    "meal_plan_fill {}            - Wochenplan mit KI-Rezepten fuellen\n"
    "open {tab}                   - nur Hinweis, Tim schaut selbst nach\n"
    "remind_later {days}          - Vorschlag vertagen\n"
    "dismiss {}                   - verwerfen"
)


def is_allowed(action: dict | None) -> bool:
    return bool(action) and action.get("type") in REGISTRY


def execute(db, settings, action: dict) -> str:
    fn = REGISTRY.get((action or {}).get("type"))
    if fn is None:
        return "Diese Aktion kenne ich nicht (mehr)."
    return fn(db, settings, action.get("params") or {})

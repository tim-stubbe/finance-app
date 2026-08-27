"""Routinen (wiederkehrende Jarvis-Checklisten, Spezifikation Abschnitt G) -
neue, aber bewusst schlanke Domäne, eigenes Modul analog zu den bereits
modularisierten crud_*.py-Dateien (siehe ROADMAP.md), statt crud.py weiter
wachsen zu lassen.

crud.py importiert alle hier definierten Namen zurück, damit main.py/
routers/telegram_bot.py sie unter dem gewohnten `crud.`-Aufrufstil nutzen
können."""

from datetime import date, datetime
import json

from sqlalchemy.orm import Session

from . import models, schemas

# Feste, locale-unabhängige Kürzel statt date.strftime("%a") (dessen Ausgabe
# von der System-Locale abhängt, siehe auch telegram_bot.py: weekday_de wird
# dort aus demselben Grund über eine feste Liste statt strftime gebaut).
WEEKDAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _routine_out(routine: models.Routine, checked_items: list[str] | None = None) -> schemas.RoutineOut:
    return schemas.RoutineOut(
        id=routine.id,
        name=routine.name,
        weekdays=[w.strip() for w in routine.weekdays.split(",") if w.strip()],
        hour=routine.hour,
        minute=routine.minute,
        items=[i for i in routine.items_text.split("\n") if i.strip()],
        active=routine.active,
        checked_items=checked_items or [],
    )


def get_routines(db: Session) -> list[schemas.RoutineOut]:
    today = date.today()
    routines = db.query(models.Routine).order_by(models.Routine.name).all()
    out = []
    for r in routines:
        run = db.query(models.RoutineRun).filter_by(routine_id=r.id, date=today).first()
        checked = json.loads(run.checked_items_json) if run else []
        out.append(_routine_out(r, checked))
    return out


def create_routine(db: Session, data: schemas.RoutineCreate) -> schemas.RoutineOut:
    routine = models.Routine(
        name=data.name.strip(),
        weekdays=",".join(w.strip().lower() for w in data.weekdays if w.strip()),
        hour=data.hour, minute=data.minute,
        items_text="\n".join(i.strip() for i in data.items if i.strip()),
        active=data.active,
    )
    db.add(routine)
    db.commit()
    db.refresh(routine)
    return _routine_out(routine)


def update_routine(db: Session, routine_id: int, data: schemas.RoutineUpdate) -> schemas.RoutineOut | None:
    routine = db.query(models.Routine).filter(models.Routine.id == routine_id).first()
    if not routine:
        return None
    routine.name = data.name.strip()
    routine.weekdays = ",".join(w.strip().lower() for w in data.weekdays if w.strip())
    routine.hour = data.hour
    routine.minute = data.minute
    routine.items_text = "\n".join(i.strip() for i in data.items if i.strip())
    routine.active = data.active
    db.commit()
    return _routine_out(routine)


def delete_routine(db: Session, routine_id: int) -> bool:
    routine = db.query(models.Routine).filter(models.Routine.id == routine_id).first()
    if not routine:
        return False
    db.query(models.RoutineRun).filter(models.RoutineRun.routine_id == routine_id).delete()
    db.delete(routine)
    db.commit()
    return True


def toggle_routine_item(db: Session, routine_id: int, item: str, checked: bool) -> schemas.RoutineOut | None:
    """Hakt ein Item für HEUTE ab/wieder auf - legt den RoutineRun für heute
    bei der ersten Interaktion an (nicht schon beim Versand der Erinnerung,
    siehe models.RoutineRun-Docstring)."""
    routine = db.query(models.Routine).filter(models.Routine.id == routine_id).first()
    if not routine:
        return None
    today = date.today()
    run = db.query(models.RoutineRun).filter_by(routine_id=routine_id, date=today).first()
    if not run:
        run = models.RoutineRun(routine_id=routine_id, date=today, checked_items_json="[]")
        db.add(run)
    checked_items = set(json.loads(run.checked_items_json))
    if checked:
        checked_items.add(item)
    else:
        checked_items.discard(item)
    run.checked_items_json = json.dumps(sorted(checked_items))
    db.commit()
    return _routine_out(routine, sorted(checked_items))


def get_due_routines(db: Session, now: datetime) -> list[models.Routine]:
    """Routinen, die jetzt fällig sind und heute noch nicht verschickt wurden.
    main._scheduled_routines läuft alle 15 Minuten (:00/:15/:30/:45) - die
    Settings-UI bietet für die Routine-Uhrzeit bewusst nur dieselben vier
    Minutenwerte an (wie beim Morgen-Briefing, siehe settings-assistent.js).

    Bugfix (Selbst-Review, Nacht 27./28.08., durch den echten Server-
    Ausfall in derselben Nacht entdeckt): ein exakter hour/minute-Treffer
    (frühere Version) fängt einen verpassten Prüflauf NICHT ab, obwohl das
    genauso hier stand - ein 15-Minuten-Slot, der verpasst wird (Server
    kurz down, o.ä.), matcht beim nächsten Lauf mit anderer minute()
    einfach nie mehr, die Routine bleibt für den Tag stumm. Jetzt echtes
    Nachholen: fällig ist alles, dessen (hour, minute) <= jetzt liegt und
    das heute noch nicht verschickt wurde - `last_sent_date` verhindert
    Mehrfachversand am selben Tag, ein zukünftiger Slot feuert weiterhin
    nicht vorzeitig."""
    weekday_code = WEEKDAY_CODES[now.weekday()]
    today = now.date()
    now_minutes = now.hour * 60 + now.minute
    routines = db.query(models.Routine).filter(models.Routine.active.is_(True)).all()
    return [
        r for r in routines
        if weekday_code in [w.strip() for w in r.weekdays.split(",")]
        and r.last_sent_date != today
        and (r.hour * 60 + r.minute) <= now_minutes
    ]

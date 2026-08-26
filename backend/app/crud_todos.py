"""To-Dos & Kalender-Termine (inkl. RRULE-Expansion) - zweiter Schritt der
crud.py-Modularisierung (siehe ROADMAP.md), analog zu crud_investments.py.
Reine Verschiebung ohne Verhaltensänderung.

crud.py importiert alle hier definierten Namen zurück (z.B. build_digest
ruft get_upcoming_calendar_events auf), damit jeder bestehende
`crud.get_todos(...)`-Aufrufstil in main.py/routers/ unverändert
weiterfunktioniert."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from . import models, radicale_sync


# ---------- To-Dos ----------
def get_todos(db: Session, include_done: bool = True):
    q = db.query(models.Todo).filter(models.Todo.pending_delete.is_(False))
    if not include_done:
        q = q.filter(models.Todo.done.is_(False))
    return q.order_by(models.Todo.done, models.Todo.due_date.is_(None), models.Todo.due_date, models.Todo.created_at).all()


def get_todo(db: Session, todo_id: int):
    return db.query(models.Todo).filter(models.Todo.id == todo_id, models.Todo.pending_delete.is_(False)).first()


def create_todo(db: Session, title: str, due_date=None):
    todo = models.Todo(uid=radicale_sync.new_uid(), title=title, due_date=due_date)
    db.add(todo)
    db.commit()
    db.refresh(todo)
    return todo


def update_todo(db: Session, todo: models.Todo, title=None, done=None, due_date=None):
    if title is not None:
        todo.title = title
    if done is not None and done != todo.done:
        todo.done = done
        # Zeitpunkt des Abhakens merken (bzw. beim Zurücknehmen wieder
        # löschen) - Grundlage für die automatische Aufräumung nach 2 Tagen.
        todo.completed_at = datetime.utcnow() if done else None
    if due_date is not None:
        todo.due_date = due_date
    db.commit()
    db.refresh(todo)
    return todo


def complete_todo_by_name(db: Session, name_query: str):
    """Hakt ein offenes To-Do über einen (Teil-)Namen ab - fürs Telegram-
    Kommando /erledigt, analog zu set_balance_by_name. Gibt (todo, error)
    zurück: error ist None bei Erfolg, sonst ein Text zum direkten
    Zurücksenden (kein Treffer / mehrdeutig)."""
    open_todos = get_todos(db, include_done=False)
    q = name_query.strip().lower()
    if not q:
        # Ein leerer Suchbegriff waere Teilstring von jedem Titel und wuerde
        # sonst bei genau einem offenen To-Do dieses ohne echten Treffer
        # abhaken - lieber explizit "kein Treffer" als das.
        return None, "Kein Suchbegriff angegeben."
    matches = [t for t in open_todos if q in t.title.lower()]
    if not matches:
        namen = ", ".join(t.title for t in open_todos) or "keine offenen To-Dos"
        return None, f"Nichts mit „{name_query}“ gefunden. Offen: {namen}"
    if len(matches) > 1:
        namen = ", ".join(t.title for t in matches)
        return None, f"„{name_query}“ ist nicht eindeutig, passt auf: {namen}. Bitte genauer benennen."
    todo = update_todo(db, matches[0], done=True)
    return todo, None


def cleanup_old_done_todos(db: Session, days: int = 2) -> int:
    """Erledigte To-Dos verschwinden 2 Tage, nachdem sie abgehakt wurden, von
    selbst - abgehakt heißt hier "erledigt, kann weg", nicht "soll dauerhaft
    als Liste stehen bleiben". Löschung läuft über denselben pending_delete-
    Weg wie eine manuelle Löschung, damit sie beim nächsten Sync auch auf dem
    Radicale-Server verschwindet."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    old = (
        db.query(models.Todo)
        .filter(models.Todo.done.is_(True), models.Todo.completed_at.isnot(None),
                models.Todo.completed_at < cutoff, models.Todo.pending_delete.is_(False))
        .all()
    )
    for todo in old:
        todo.pending_delete = True
    if old:
        db.commit()
    return len(old)


class _CalendarOccurrence:
    """Eine einzelne, aus einer RRULE errechnete Vorkommen-Instanz eines
    wiederkehrenden Termins - kein eigener DB-Eintrag (siehe radicale_sync.
    expand_rrule-Docstring: Kies speichert weiterhin nur den Master-VEVENT).
    Traegt dieselben Attribute wie models.CalendarEvent, damit schemas.
    CalendarEventOut (from_attributes) beide gleich serialisieren kann.
    `id`/`recurring_master_id` zeigen auf den Master - Bearbeiten/Loeschen
    einzelner Instanzen ist bewusst nicht vorgesehen (Serie bleibt Aufgabe
    des Telefon-Clients), das Frontend blendet dafuer bei is_recurring=True
    die entsprechenden Aktionen aus."""

    def __init__(self, master: "models.CalendarEvent", occ_start: datetime, occ_end):
        self.id = master.id
        self.title = master.title
        self.start = occ_start
        self.end = occ_end
        self.location = master.location
        self.lat = master.lat
        self.lon = master.lon
        self.all_day = master.all_day
        self.calendar_url = master.calendar_url
        self.travel_minutes = None
        self.is_recurring = True
        self.recurring_master_id = master.id


def _expand_calendar_window(events: list, start: datetime, end: datetime) -> list:
    """Ersetzt jeden Termin mit gesetzter RRULE durch seine Vorkommen im
    Fenster [start, end) (siehe radicale_sync.expand_rrule), laesst
    Einzeltermine unveraendert - beide Faelle bekommen is_recurring/
    recurring_master_id fuer eine einheitliche Serialisierung."""
    result = []
    for ev in events:
        if not ev.rrule:
            ev.is_recurring = False
            ev.recurring_master_id = None
            result.append(ev)
            continue
        duration = (ev.end - ev.start) if ev.end else None
        try:
            occ_starts = radicale_sync.expand_rrule(ev.start, ev.rrule, start, end)
        except Exception:
            occ_starts = [ev.start] if start <= ev.start < end else []
        for occ_start in occ_starts:
            occ_end = occ_start + duration if duration else None
            result.append(_CalendarOccurrence(ev, occ_start, occ_end))
    result.sort(key=lambda e: e.start)
    return result


def get_upcoming_calendar_events(db: Session, days: int = 7, limit: int = 20) -> list[models.CalendarEvent]:
    now = datetime.utcnow()
    cutoff = now + timedelta(days=days)
    return (
        db.query(models.CalendarEvent)
        .filter(models.CalendarEvent.start >= now, models.CalendarEvent.start <= cutoff)
        .order_by(models.CalendarEvent.start)
        .limit(limit)
        .all()
    )


def detect_calendar_conflicts(db: Session, days: int = 14) -> list[dict]:
    """Findet sich zeitlich überschneidende Termine in den nächsten `days`
    Tagen - reine Auswertung der ohnehin geladenen Termine, kein Ändern.
    Ganztägige Termine werden bewusst ausgeklammert (die überschneiden sich
    fast immer mit irgendwas, ohne dass das ein echtes Problem wäre). Termine
    ohne Ende gelten für den Vergleich als 30 Minuten lang - eine Annahme nur
    für diese Prüfung, nicht gespeichert."""
    now = datetime.utcnow()
    cutoff = now + timedelta(days=days)
    events = [ev for ev in get_calendar_events(db, now, cutoff) if not ev.all_day]
    events.sort(key=lambda e: e.start)

    def effective_end(ev):
        return ev.end or (ev.start + timedelta(minutes=30))

    conflicts = []
    for i in range(len(events)):
        a = events[i]
        a_end = effective_end(a)
        for j in range(i + 1, len(events)):
            b = events[j]
            if b.start >= a_end:
                break  # nach Start sortiert - ab hier kann nichts mehr ueberlappen
            conflicts.append({
                "event_a_id": a.id, "event_a_title": a.title, "event_a_start": a.start,
                "event_b_id": b.id, "event_b_title": b.title, "event_b_start": b.start,
            })
    return conflicts


def delete_todo(db: Session, todo: models.Todo):
    # Erst zum Löschen markieren, damit der nächste Sync die Löschung noch auf
    # den Server übertragen kann - direktes db.delete() würde die Radicale-
    # Ressource verwaist zurücklassen.
    todo.pending_delete = True
    db.commit()


def get_calendar_events(db: Session, start: datetime, end: datetime) -> list:
    """Termine im Fenster [start, end] - inklusive der Vorkommen wieder-
    kehrender Serien (siehe _expand_calendar_window), deren Master-Termin
    auch deutlich vor `start` liegen kann. Rueckgabetyp bewusst nicht mehr
    rein models.CalendarEvent, sondern gemischt mit _CalendarOccurrence."""
    single = (
        db.query(models.CalendarEvent)
        .filter(
            models.CalendarEvent.pending_delete.is_(False),
            models.CalendarEvent.rrule.is_(None),
            models.CalendarEvent.start >= start,
            models.CalendarEvent.start <= end,
        )
        .all()
    )
    recurring = (
        db.query(models.CalendarEvent)
        .filter(
            models.CalendarEvent.pending_delete.is_(False),
            models.CalendarEvent.rrule.isnot(None),
            models.CalendarEvent.start <= end,
        )
        .all()
    )
    return _expand_calendar_window(single + recurring, start, end)


def get_calendar_event(db: Session, event_id: int):
    return (
        db.query(models.CalendarEvent)
        .filter(models.CalendarEvent.id == event_id, models.CalendarEvent.pending_delete.is_(False))
        .first()
    )


def create_calendar_event(db: Session, title, start, end, location, all_day, calendar_url):
    event = models.CalendarEvent(
        uid=radicale_sync.new_uid(), title=title, start=start, end=end,
        location=location, all_day=all_day, calendar_url=calendar_url,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def update_calendar_event(db: Session, event: models.CalendarEvent, title=None, start=None, end=None, location=None, all_day=None):
    if title is not None:
        event.title = title
    if start is not None:
        event.start = start
    if end is not None:
        event.end = end
    if location is not None:
        event.location = location or None
    if all_day is not None:
        event.all_day = all_day
    event.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(event)
    return event


def cancel_calendar_event_by_name(db: Session, name_query: str):
    """Sagt einen zukünftigen Termin über einen (Teil-)Namen ab - fürs
    Telegram-Kommando /termin_absagen, analog zu set_balance_by_name/
    complete_todo_by_name. Gibt (event, error) zurück: error ist None bei
    Erfolg, sonst ein Text zum direkten Zurücksenden (kein Treffer /
    mehrdeutig)."""
    upcoming = get_upcoming_calendar_events(db, days=365, limit=1000)
    q = name_query.strip().lower()
    if not q:
        # Siehe complete_todo_by_name: ein leerer Suchbegriff waere sonst
        # Teilstring von jedem Titel und wuerde bei genau einem anstehenden
        # Termin diesen ohne echten Treffer absagen.
        return None, "Kein Suchbegriff angegeben."
    matches = [e for e in upcoming if q in e.title.lower()]
    if not matches:
        namen = ", ".join(e.title for e in upcoming[:10]) or "keine anstehenden Termine"
        return None, f"Nichts mit „{name_query}“ gefunden. Anstehend: {namen}"
    if len(matches) > 1:
        namen = ", ".join(e.title for e in matches)
        return None, f"„{name_query}“ ist nicht eindeutig, passt auf: {namen}. Bitte genauer benennen."
    event = matches[0]
    delete_calendar_event(db, event)
    return event, None


def delete_calendar_event(db: Session, event: models.CalendarEvent):
    # Wie bei Todo: erst markieren, damit der nächste Sync die Löschung noch
    # auf den Server überträgt, statt die Radicale-Ressource verwaist zurück-
    # zulassen. Ein Termin ohne calendar_url (nie synchronisiert) kann direkt
    # gelöscht werden.
    if event.calendar_url and event.href:
        event.pending_delete = True
        db.commit()
    else:
        db.delete(event)
        db.commit()

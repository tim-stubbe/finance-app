"""Kalender (Radicale/CalDAV) + To-Dos (zweiseitig mit Radicale synchronisiert).

Elfter Schritt der Code-Modularisierung (siehe ROADMAP.md), nach
investments/tax/debts/goals/trips/wishlist/personal/business_life/
budgets_alerts/deadlines. Beide Domänen teilen sich dieselbe Radicale-
Verbindung und standen im selben main.py-Abschnitt. Reine Verschiebung ohne
Verhaltensänderung.

`_scheduled_radicale_sync` (main.py, alle 3 Minuten) dupliziert die
Grundlogik von `_radicale_credentials`/`settings_has_radicale` bewusst
inline statt diese Helfer hier zu importieren - eigenständig gewachsen,
keine Abhängigkeit hierher, deshalb unverändert in main.py belassen."""

from datetime import datetime, timedelta
from typing import List
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas, crud, auth, bank_sync, radicale_sync, travel_time
from ..database import get_db

calendar_todos_router = APIRouter(prefix="/api")


def _radicale_credentials(db: Session) -> tuple[str, str, str]:
    settings = auth.get_or_create_settings(db)
    if not settings.radicale_url:
        raise HTTPException(400, "Radicale ist noch nicht eingerichtet. Trage unter Einstellungen die Adresse ein.")
    password = bank_sync.decrypt_secret(settings.secret_key, settings.radicale_password_encrypted)
    return settings.radicale_url, settings.radicale_username, password


def settings_has_radicale(db: Session) -> bool:
    settings = auth.get_or_create_settings(db)
    return bool(settings.radicale_url)


@calendar_todos_router.get("/calendar/upcoming", response_model=List[schemas.CalendarEventOut])
def get_upcoming_calendar_events(days: int = 7, db: Session = Depends(get_db)):
    return crud.get_upcoming_calendar_events(db, days=days)


@calendar_todos_router.get("/calendar/conflicts", response_model=List[schemas.CalendarConflictOut])
def get_calendar_conflicts(days: int = 14, db: Session = Depends(get_db)):
    return crud.detect_calendar_conflicts(db, days=days)


def _calendar_urls(db: Session) -> list[str]:
    settings = auth.get_or_create_settings(db)
    if not settings.radicale_calendar_url:
        return []
    return [u.strip() for u in settings.radicale_calendar_url.split(",") if u.strip()]


def _sync_all_calendars(db: Session) -> None:
    urls = _calendar_urls(db)
    if not urls:
        return
    settings = auth.get_or_create_settings(db)
    password = bank_sync.decrypt_secret(settings.secret_key, settings.radicale_password_encrypted)
    for cal_url in urls:
        try:
            radicale_sync.sync_calendar(db, cal_url, settings.radicale_username, password)
        except Exception:
            pass


@calendar_todos_router.get("/calendar/collections", response_model=List[schemas.CalendarCollectionOut])
def get_calendar_collections(db: Session = Depends(get_db)):
    collections = []
    for url in _calendar_urls(db):
        segment = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
        name = segment.replace("_", " ").replace("-", " ").strip().title() or url
        collections.append(schemas.CalendarCollectionOut(url=url, name=name))
    return collections


@calendar_todos_router.get("/calendar-events", response_model=List[schemas.CalendarEventOut])
def list_calendar_events(start: datetime, end: datetime, sync: bool = True, db: Session = Depends(get_db)):
    # Beim Öffnen des Kalender-Tabs direkt abgleichen statt auf den nächsten
    # Hintergrund-Sync zu warten (analog zu den Todos) - kann per sync=false
    # übersprungen werden (z.B. beim reinen Monat-weiterklicken).
    if sync:
        _sync_all_calendars(db)
    events = crud.get_calendar_events(db, start, end)

    settings = auth.get_or_create_settings(db)
    if settings.home_lat and settings.home_lon and settings.openroute_api_key_encrypted:
        api_key = bank_sync.decrypt_secret(settings.secret_key, settings.openroute_api_key_encrypted)
        home_coords = (settings.home_lat, settings.home_lon)
        now = datetime.utcnow()
        for ev in events:
            # Nur fuer Termine der naechsten 24h (siehe crud.build_digest fuer
            # dieselbe Begruendung: sonst taeglich wiederholte Anfragen fuer
            # laengst noch nicht relevante Termine).
            if ev.all_day or not (ev.lat and ev.lon) or not (now <= ev.start <= now + timedelta(hours=24)):
                continue
            try:
                ev.travel_minutes = travel_time.travel_time_minutes(api_key, home_coords, (ev.lat, ev.lon))
            except Exception:
                pass
    return events


@calendar_todos_router.post("/calendar-events", response_model=schemas.CalendarEventOut)
def create_calendar_event(data: schemas.CalendarEventCreate, db: Session = Depends(get_db)):
    urls = _calendar_urls(db)
    calendar_url = data.calendar_url or (urls[0] if urls else None)
    if data.calendar_url and data.calendar_url not in urls:
        raise HTTPException(400, "Unbekannter Kalender")
    event = crud.create_calendar_event(db, data.title, data.start, data.end, data.location, data.all_day, calendar_url)
    _sync_all_calendars(db)
    return event


@calendar_todos_router.put("/calendar-events/{event_id}", response_model=schemas.CalendarEventOut)
def update_calendar_event(event_id: int, data: schemas.CalendarEventUpdate, db: Session = Depends(get_db)):
    event = crud.get_calendar_event(db, event_id)
    if not event:
        raise HTTPException(404, "Termin nicht gefunden")
    event = crud.update_calendar_event(db, event, data.title, data.start, data.end, data.location, data.all_day)
    _sync_all_calendars(db)
    return event


@calendar_todos_router.delete("/calendar-events/{event_id}")
def remove_calendar_event(event_id: int, db: Session = Depends(get_db)):
    event = crud.get_calendar_event(db, event_id)
    if not event:
        raise HTTPException(404, "Termin nicht gefunden")
    crud.delete_calendar_event(db, event)
    _sync_all_calendars(db)
    return {"ok": True}


@calendar_todos_router.get("/todos", response_model=List[schemas.TodoOut])
def list_todos(include_done: bool = True, db: Session = Depends(get_db)):
    # Beim Öffnen des Tabs direkt abgleichen statt auf den nächsten
    # Hintergrund-Sync (alle 3 Minuten) zu warten oder auf die nächste lokale
    # Änderung - sonst wirkt es, als kämen am Handy eingetragene To-Dos gar
    # nicht an, bis man selbst etwas hier ändert.
    if settings_has_radicale(db):
        url, username, password = _radicale_credentials(db)
        try:
            radicale_sync.sync(db, url, username, password)
        except Exception:
            pass
    return crud.get_todos(db, include_done)


@calendar_todos_router.post("/todos", response_model=schemas.TodoOut)
def create_todo(data: schemas.TodoCreate, db: Session = Depends(get_db)):
    todo = crud.create_todo(db, data.title, data.due_date)
    # Sofort hochladen, damit ein neues To-Do nicht erst auf den nächsten
    # Hintergrund-Sync warten muss, um am Handy sichtbar zu werden.
    if settings_has_radicale(db):
        url, username, password = _radicale_credentials(db)
        try:
            radicale_sync.sync(db, url, username, password)
        except Exception:
            pass
    return todo


@calendar_todos_router.patch("/todos/{todo_id}", response_model=schemas.TodoOut)
def update_todo(todo_id: int, data: schemas.TodoUpdate, db: Session = Depends(get_db)):
    todo = crud.get_todo(db, todo_id)
    if not todo:
        raise HTTPException(404, "To-Do nicht gefunden")
    todo = crud.update_todo(db, todo, data.title, data.done, data.due_date)
    if settings_has_radicale(db):
        url, username, password = _radicale_credentials(db)
        try:
            radicale_sync.sync(db, url, username, password)
        except Exception:
            pass
    return todo


@calendar_todos_router.delete("/todos/{todo_id}")
def remove_todo(todo_id: int, db: Session = Depends(get_db)):
    todo = crud.get_todo(db, todo_id)
    if not todo:
        raise HTTPException(404, "To-Do nicht gefunden")
    if settings_has_radicale(db):
        crud.delete_todo(db, todo)
        url, username, password = _radicale_credentials(db)
        try:
            radicale_sync.sync(db, url, username, password)
        except Exception:
            pass
    else:
        # Ohne Radicale gibt es nichts zum Nachtragen - sofort endgültig
        # löschen, statt als "pending_delete" liegen zu bleiben, bis
        # irgendwann doch noch eine Verbindung eingerichtet wird.
        db.delete(todo)
        db.commit()
    return {"ok": True}


@calendar_todos_router.post("/todos/sync", response_model=schemas.TodoSyncResult)
def sync_todos(db: Session = Depends(get_db)):
    url, username, password = _radicale_credentials(db)
    result = radicale_sync.sync(db, url, username, password)
    return schemas.TodoSyncResult(**result)

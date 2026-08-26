"""Kontextbezogene Notizen, Zeiterfassung, People/CRM-Light, Leseliste/
Medien-Tracking und Gesundheits-Grunddaten - sechster Schritt der
crud.py-Modularisierung (siehe ROADMAP.md), analog zu crud_life_areas.py.
Reine Verschiebung ohne Verhaltensänderung: fünf kleinere, voneinander
unabhängige Domänen wurden hier zusammengefasst statt fünf Mini-Module
anzulegen. project_time_summaries fragt models.BusinessProject direkt ab,
ohne Abhängigkeit zu crud_life_areas.py.

crud.py importiert alle hier definierten Namen zurück (search_notes wird
z.B. von der Globalen Suche weiter unten in crud.py gebraucht), damit
jeder bestehende `crud.get_contacts(...)`-Aufrufstil in main.py/routers/
unverändert weiterfunktioniert."""

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from . import models, schemas


# ---------- Kontextbezogene Notizen ----------
def get_notes(db: Session, entity_type: str, entity_id: int) -> list[models.Note]:
    return (
        db.query(models.Note)
        .filter(models.Note.entity_type == entity_type, models.Note.entity_id == entity_id)
        .order_by(models.Note.created_at.desc())
        .all()
    )


def create_note(db: Session, data: schemas.NoteCreate) -> models.Note:
    note = models.Note(entity_type=data.entity_type, entity_id=data.entity_id, text=data.text)
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


def delete_note(db: Session, note_id: int) -> bool:
    note = db.query(models.Note).filter(models.Note.id == note_id).first()
    if not note:
        return False
    db.delete(note)
    db.commit()
    return True


def search_notes(db: Session, q: str, limit: int = 30) -> list[models.Note]:
    return (
        db.query(models.Note)
        .filter(models.Note.text.ilike(f"%{q}%"))
        .order_by(models.Note.created_at.desc())
        .limit(limit)
        .all()
    )


# ---------- Zeiterfassung ----------
def _time_entry_minutes(e: models.TimeEntry) -> float | None:
    end = e.stopped_at or datetime.utcnow()
    return round((end - e.started_at).total_seconds() / 60, 1)


def _time_entry_out(e: models.TimeEntry) -> schemas.TimeEntryOut:
    out = schemas.TimeEntryOut.model_validate(e)
    out.minutes = _time_entry_minutes(e)
    return out


def get_time_entries(db: Session, project_id: int) -> list[models.TimeEntry]:
    return (
        db.query(models.TimeEntry)
        .filter(models.TimeEntry.project_id == project_id)
        .order_by(models.TimeEntry.started_at.desc())
        .all()
    )


def get_running_time_entry(db: Session, project_id: int) -> models.TimeEntry | None:
    return (
        db.query(models.TimeEntry)
        .filter(models.TimeEntry.project_id == project_id, models.TimeEntry.stopped_at.is_(None))
        .first()
    )


def start_time_entry(db: Session, project_id: int, note: str | None) -> models.TimeEntry:
    entry = models.TimeEntry(project_id=project_id, note=note, started_at=datetime.utcnow())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def stop_time_entry(db: Session, entry: models.TimeEntry) -> models.TimeEntry:
    entry.stopped_at = datetime.utcnow()
    db.commit()
    db.refresh(entry)
    return entry


def create_manual_time_entry(db: Session, data: schemas.TimeEntryCreate) -> models.TimeEntry:
    entry = models.TimeEntry(
        project_id=data.project_id, note=data.note,
        started_at=data.started_at or datetime.utcnow(), stopped_at=data.stopped_at,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def delete_time_entry(db: Session, entry_id: int) -> bool:
    entry = db.query(models.TimeEntry).filter(models.TimeEntry.id == entry_id).first()
    if not entry:
        return False
    db.delete(entry)
    db.commit()
    return True


def project_time_summaries(db: Session) -> list[schemas.ProjectTimeSummary]:
    """Summe abgeschlossener Minuten je Projekt plus laufender Eintrag, falls
    einer läuft (der zählt erst nach dem Stoppen zur Summe, sonst müsste die
    Anzeige minütlich neu berechnet werden statt einmal pro Laden)."""
    projects = db.query(models.BusinessProject).all()
    out = []
    for p in projects:
        entries = get_time_entries(db, p.id)
        total = sum(_time_entry_minutes(e) for e in entries if e.stopped_at)
        running = next((e for e in entries if e.stopped_at is None), None)
        if total > 0 or running or entries:
            out.append(schemas.ProjectTimeSummary(
                project_id=p.id, project_name=p.name,
                total_minutes=round(total, 1), running_entry_id=running.id if running else None,
            ))
    return out


# ---------- People / CRM-Light ----------
def get_contacts(db: Session) -> list[models.Contact]:
    return db.query(models.Contact).order_by(models.Contact.name).all()


def create_contact(db: Session, data: schemas.ContactCreate) -> models.Contact:
    contact = models.Contact(**data.model_dump())
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def update_contact(db: Session, contact: models.Contact, data: schemas.ContactUpdate) -> models.Contact:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(contact, key, value)
    db.commit()
    db.refresh(contact)
    return contact


def delete_contact(db: Session, contact_id: int) -> bool:
    contact = db.query(models.Contact).filter(models.Contact.id == contact_id).first()
    if not contact:
        return False
    db.delete(contact)
    db.commit()
    return True


def touch_contact(db: Session, contact: models.Contact) -> models.Contact:
    contact.last_interaction_at = date.today()
    db.commit()
    db.refresh(contact)
    return contact


# ---------- Leseliste / Medien-Tracking ----------
def _media_item_out(m: models.MediaItem) -> schemas.MediaItemOut:
    out = schemas.MediaItemOut.model_validate(m)
    out.linked_goal_title = m.linked_goal.title if m.linked_goal else None
    out.linked_project_name = m.linked_project.name if m.linked_project else None
    return out


def get_media_items(db: Session) -> list[schemas.MediaItemOut]:
    items = db.query(models.MediaItem).order_by(models.MediaItem.created_at.desc()).all()
    return [_media_item_out(m) for m in items]


def create_media_item(db: Session, data: schemas.MediaItemCreate) -> schemas.MediaItemOut:
    item = models.MediaItem(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return _media_item_out(item)


def update_media_item(db: Session, item: models.MediaItem, data: schemas.MediaItemUpdate) -> schemas.MediaItemOut:
    changes = data.model_dump(exclude_unset=True)
    was_finished = item.status == models.MediaStatus.fertig
    for key, value in changes.items():
        setattr(item, key, value)
    if item.status == models.MediaStatus.fertig and not was_finished:
        item.finished_at = date.today()
    db.commit()
    db.refresh(item)
    return _media_item_out(item)


def delete_media_item(db: Session, item_id: int) -> bool:
    item = db.query(models.MediaItem).filter(models.MediaItem.id == item_id).first()
    if not item:
        return False
    db.delete(item)
    db.commit()
    return True


# ---------- Gesundheits-Grunddaten ----------
def get_health_metrics(db: Session, metric_type: models.HealthMetricType, days: int = 90) -> list[models.HealthMetric]:
    cutoff = date.today() - timedelta(days=days)
    return (
        db.query(models.HealthMetric)
        .filter(models.HealthMetric.metric_type == metric_type, models.HealthMetric.date >= cutoff)
        .order_by(models.HealthMetric.date)
        .all()
    )


def create_health_metric(db: Session, data: schemas.HealthMetricCreate) -> models.HealthMetric:
    existing = (
        db.query(models.HealthMetric)
        .filter(models.HealthMetric.metric_type == data.metric_type, models.HealthMetric.date == data.date)
        .first()
    )
    if existing:
        existing.value = data.value
        db.commit()
        db.refresh(existing)
        return existing
    metric = models.HealthMetric(**data.model_dump())
    db.add(metric)
    db.commit()
    db.refresh(metric)
    return metric


def delete_health_metric(db: Session, metric_id: int) -> bool:
    metric = db.query(models.HealthMetric).filter(models.HealthMetric.id == metric_id).first()
    if not metric:
        return False
    db.delete(metric)
    db.commit()
    return True


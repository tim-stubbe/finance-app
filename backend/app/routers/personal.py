"""Persönliche Bereiche außerhalb der Finanzen: Notizen, globale Suche,
Zeiterfassung, Kontakte (People/CRM-Light), Leseliste und Gesundheits-
Grunddaten.

Siebter Schritt der Code-Modularisierung (siehe ROADMAP.md), nach
investments/tax/debts/goals/trips/wishlist. Reine Verschiebung ohne
Verhaltensänderung. Diese fünf/sechs kleinen Domänen wurden im selben
main.py-Abschnitt eingeführt (siehe git-Historie: "Kontextbezogene Notizen",
"Niedrige Priorität: Zeiterfassung, Kontakte, Leseliste, Gesundheits-
Grunddaten", "Globale Volltextsuche") und bleiben deshalb auch hier
zusammen, statt für jede einzeln eine Ein-Endpunkt-Datei anzulegen."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, crud, auth
from ..database import get_db

personal_router = APIRouter(prefix="/api")

# Zeiterfassung ist zusätzlich per Device-Token erreichbar (native Live
# Activity / Lock-Screen-Widget auf iOS, siehe ROADMAP.md), analog zu
# `jarvis_chat_router` in routers/jarvis.py: bewusst KEIN pauschales
# `dependencies=_require_auth` in main.py, sondern `auth.require_session_or_device`
# direkt an jedem Endpunkt. Deshalb liegen diese Routen in einem eigenen
# Router statt im session-only `personal_router`.
personal_device_router = APIRouter(prefix="/api")


# ---------------- Kontextbezogene Notizen ----------------
def _note_entity_label(db: Session, entity_type: str, entity_id: int,
                       space_id: Optional[int] = None) -> Optional[str]:
    """Für die Notiz-Suche: ein lesbarer Titel des Objekts, an dem die Notiz
    hängt, damit ein Treffer nicht nur "Notiz #17" zeigt. Best-effort - fehlt
    das Objekt (gelöscht), bleibt es None statt eines Fehlers.

    Bereichs-gebundene Objekte (Ziel, Business-Projekt) werden auf den aktiven
    Bereich eingeschränkt (`space_id`), damit ein Notiz-Treffer nie den Titel
    eines fremden Bereichs durchsickern lässt (Multi-User Phase 2 / Audit)."""
    def _scoped(model):
        q = db.query(model).filter(model.id == entity_id)
        if space_id is not None and hasattr(model, "space_id"):
            q = q.filter((model.space_id == space_id) | (model.space_id.is_(None)))
        return q.first()

    if entity_type == "goal":
        g = _scoped(models.Goal)
        return g.title if g else None
    if entity_type == "todo":
        # Todos hängen (noch) an keinem Bereich - instanzweit wie bisher.
        t = db.query(models.Todo).filter(models.Todo.id == entity_id).first()
        return t.title if t else None
    if entity_type == "business_project":
        p = _scoped(models.BusinessProject)
        return p.name if p else None
    if entity_type == "life_area":
        # LifeArea ist ebenfalls instanzweit (kein space_id).
        a = db.query(models.LifeArea).filter(models.LifeArea.id == entity_id).first()
        return a.name if a else None
    if entity_type == "schweiz":
        return "Schweiz-Tab"
    return None


@personal_router.get("/notes", response_model=List[schemas.NoteOut])
def list_notes(entity_type: str, entity_id: int, db: Session = Depends(get_db)):
    return crud.get_notes(db, entity_type, entity_id)


@personal_router.post("/notes", response_model=schemas.NoteOut)
def create_note(data: schemas.NoteCreate, db: Session = Depends(get_db)):
    if data.entity_type not in schemas.NOTE_ENTITY_TYPES:
        raise HTTPException(400, "Unbekannter Notiz-Typ")
    if not data.text.strip():
        raise HTTPException(400, "Notiz ist leer")
    return crud.create_note(db, data)


@personal_router.delete("/notes/{note_id}")
def remove_note(note_id: int, db: Session = Depends(get_db)):
    if not crud.delete_note(db, note_id):
        raise HTTPException(404, "Notiz nicht gefunden")
    return {"ok": True}


@personal_router.get("/notes/search", response_model=List[schemas.NoteSearchResult])
def search_notes(q: str, db: Session = Depends(get_db),
                 space_id: int = Depends(auth.get_active_space_id)):
    if len(q.strip()) < 2:
        return []
    notes = crud.search_notes(db, q.strip())
    results = []
    for n in notes:
        results.append(schemas.NoteSearchResult(
            id=n.id, entity_type=n.entity_type, entity_id=n.entity_id, text=n.text,
            created_at=n.created_at, updated_at=n.updated_at,
            entity_label=_note_entity_label(db, n.entity_type, n.entity_id, space_id),
        ))
    return results


# ---------------- Globale Suche ----------------
@personal_router.get("/search", response_model=List[schemas.GlobalSearchResult])
def global_search(q: str, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if len(q.strip()) < 2:
        return []
    return crud.global_search(db, space_id, q.strip())


# ---------------- Zeiterfassung ----------------
# Per Device-Token erreichbar (siehe personal_device_router oben) für die
# native Live Activity / das Lock-Screen-Widget - nicht nur per Web-Session.
@personal_device_router.get("/projects/{project_id}/time-entries", response_model=List[schemas.TimeEntryOut])
def list_time_entries(project_id: int, db: Session = Depends(get_db),
                      principal: models.AuthenticatedPrincipal = Depends(auth.require_session_or_device)):
    return [crud._time_entry_out(e) for e in crud.get_time_entries(db, project_id)]


@personal_device_router.post("/projects/{project_id}/time-entries/start", response_model=schemas.TimeEntryOut)
def start_time_entry(project_id: int, note: Optional[str] = None, db: Session = Depends(get_db),
                     principal: models.AuthenticatedPrincipal = Depends(auth.require_session_or_device)):
    if crud.get_running_time_entry(db, project_id):
        raise HTTPException(400, "Für dieses Projekt läuft schon eine Zeiterfassung")
    entry = crud.start_time_entry(db, project_id, note)
    return crud._time_entry_out(entry)


@personal_device_router.post("/time-entries/{entry_id}/stop", response_model=schemas.TimeEntryOut)
def stop_time_entry(entry_id: int, db: Session = Depends(get_db),
                    principal: models.AuthenticatedPrincipal = Depends(auth.require_session_or_device)):
    entry = db.query(models.TimeEntry).filter(models.TimeEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Eintrag nicht gefunden")
    if entry.stopped_at:
        raise HTTPException(400, "Eintrag läuft nicht mehr")
    return crud._time_entry_out(crud.stop_time_entry(db, entry))


@personal_device_router.post("/time-entries", response_model=schemas.TimeEntryOut)
def create_time_entry(data: schemas.TimeEntryCreate, db: Session = Depends(get_db),
                      principal: models.AuthenticatedPrincipal = Depends(auth.require_session_or_device)):
    return crud._time_entry_out(crud.create_manual_time_entry(db, data))


@personal_device_router.delete("/time-entries/{entry_id}")
def remove_time_entry(entry_id: int, db: Session = Depends(get_db),
                      principal: models.AuthenticatedPrincipal = Depends(auth.require_session_or_device)):
    if not crud.delete_time_entry(db, entry_id):
        raise HTTPException(404, "Eintrag nicht gefunden")
    return {"ok": True}


@personal_device_router.get("/time-entries/summary", response_model=List[schemas.ProjectTimeSummary])
def get_time_summary(db: Session = Depends(get_db),
                     principal: models.AuthenticatedPrincipal = Depends(auth.require_session_or_device)):
    return crud.project_time_summaries(db)


@personal_device_router.get("/time-entries/running", response_model=Optional[schemas.TimeEntryOut])
def get_running_time_entry_any(db: Session = Depends(get_db),
                               principal: models.AuthenticatedPrincipal = Depends(auth.require_session_or_device)):
    """Läuft gerade irgendwo eine Zeiterfassung? Für die native App, um nach
    Neustart/Resume eine Live Activity wiederherzustellen, ohne die
    Projekt-ID schon zu kennen."""
    summaries = crud.project_time_summaries(db)
    for s in summaries:
        if s.running_entry_id:
            entry = db.query(models.TimeEntry).filter(models.TimeEntry.id == s.running_entry_id).first()
            if entry:
                return crud._time_entry_out(entry)
    return None


@personal_device_router.get("/projects", response_model=List[schemas.BusinessProjectOut])
def list_projects_for_device(db: Session = Depends(get_db),
                             principal: models.AuthenticatedPrincipal = Depends(auth.require_session_or_device)):
    """Schlanke Projektliste für die native App (Live Activity: Projekt
    auswählen, um eine Zeiterfassung zu starten). Nur aktive Projekte, keine
    Web-Session nötig - siehe personal_device_router oben."""
    return crud.get_business_projects(db, include_inactive=False)


# ---------------- People / CRM-Light ----------------
@personal_router.get("/contacts", response_model=List[schemas.ContactOut])
def list_contacts(db: Session = Depends(get_db)):
    return crud.get_contacts(db)


@personal_router.post("/contacts", response_model=schemas.ContactOut)
def create_contact(data: schemas.ContactCreate, db: Session = Depends(get_db)):
    return crud.create_contact(db, data)


@personal_router.patch("/contacts/{contact_id}", response_model=schemas.ContactOut)
def update_contact(contact_id: int, data: schemas.ContactUpdate, db: Session = Depends(get_db)):
    contact = db.query(models.Contact).filter(models.Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(404, "Kontakt nicht gefunden")
    return crud.update_contact(db, contact, data)


@personal_router.post("/contacts/{contact_id}/touch", response_model=schemas.ContactOut)
def touch_contact(contact_id: int, db: Session = Depends(get_db)):
    contact = db.query(models.Contact).filter(models.Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(404, "Kontakt nicht gefunden")
    return crud.touch_contact(db, contact)


@personal_router.delete("/contacts/{contact_id}")
def remove_contact(contact_id: int, db: Session = Depends(get_db)):
    if not crud.delete_contact(db, contact_id):
        raise HTTPException(404, "Kontakt nicht gefunden")
    return {"ok": True}


# ---------------- Leseliste / Medien-Tracking ----------------
@personal_router.get("/media", response_model=List[schemas.MediaItemOut])
def list_media_items(db: Session = Depends(get_db)):
    return crud.get_media_items(db)


@personal_router.post("/media", response_model=schemas.MediaItemOut)
def create_media_item(data: schemas.MediaItemCreate, db: Session = Depends(get_db)):
    return crud.create_media_item(db, data)


@personal_router.patch("/media/{item_id}", response_model=schemas.MediaItemOut)
def update_media_item(item_id: int, data: schemas.MediaItemUpdate, db: Session = Depends(get_db)):
    item = db.query(models.MediaItem).filter(models.MediaItem.id == item_id).first()
    if not item:
        raise HTTPException(404, "Eintrag nicht gefunden")
    return crud.update_media_item(db, item, data)


@personal_router.delete("/media/{item_id}")
def remove_media_item(item_id: int, db: Session = Depends(get_db)):
    if not crud.delete_media_item(db, item_id):
        raise HTTPException(404, "Eintrag nicht gefunden")
    return {"ok": True}


# ---------------- Gesundheits-Grunddaten ----------------
@personal_router.get("/health-metrics", response_model=List[schemas.HealthMetricOut])
def list_health_metrics(metric_type: models.HealthMetricType, days: int = 90, db: Session = Depends(get_db)):
    return crud.get_health_metrics(db, metric_type, days)


@personal_router.post("/health-metrics", response_model=schemas.HealthMetricOut)
def create_health_metric(data: schemas.HealthMetricCreate, db: Session = Depends(get_db)):
    return crud.create_health_metric(db, data)


@personal_router.delete("/health-metrics/{metric_id}")
def remove_health_metric(metric_id: int, db: Session = Depends(get_db)):
    if not crud.delete_health_metric(db, metric_id):
        raise HTTPException(404, "Eintrag nicht gefunden")
    return {"ok": True}

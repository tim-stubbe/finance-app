"""Business-Projekte (Nebenprojekte) + Leben (persönliche Lebensbereiche).

Achter Schritt der Code-Modularisierung (siehe ROADMAP.md), nach
investments/tax/debts/goals/trips/wishlist/personal. Beide Domänen leben
hier zusammen, weil sie im gleichen main.py-Abschnitt nebeneinander standen
und beide dem "Sekretariats-Prinzip" folgen (BusinessProject/LifeArea:
aktives Nachfragen statt nur passiver Anzeige, siehe models.py-Docstrings) -
inhaltlich näher beieinander als z.B. bei personal.py. Reine Verschiebung
ohne Verhaltensänderung.

Bewusst NICHT mit hierher gezogen: /business/summary (Dashboard-Auswertung,
ruft crud.dashboard_summary auf) - das ist Reporting, keine Projekte/Issues-
CRUD, bleibt bei den anderen Dashboard-Endpunkten in main.py."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, crud
from ..database import get_db

business_life_router = APIRouter(prefix="/api")


# ---------------- Business-Projekte (Nebenprojekte) ----------------
@business_life_router.get("/business-projects", response_model=List[schemas.BusinessProjectOut])
def list_business_projects(include_inactive: bool = False, db: Session = Depends(get_db)):
    return crud.get_business_projects(db, include_inactive)


@business_life_router.post("/business-projects", response_model=schemas.BusinessProjectOut)
def create_business_project(data: schemas.BusinessProjectCreate, db: Session = Depends(get_db)):
    return crud.create_business_project(db, data)


@business_life_router.patch("/business-projects/{project_id}", response_model=schemas.BusinessProjectOut)
def update_business_project(project_id: int, data: schemas.BusinessProjectUpdate, db: Session = Depends(get_db)):
    project = crud.get_business_project(db, project_id)
    if not project:
        raise HTTPException(404, "Projekt nicht gefunden")
    return crud.update_business_project(db, project, data)


@business_life_router.post("/business-projects/{project_id}/checked", response_model=schemas.BusinessProjectOut)
def mark_business_project_checked(project_id: int, db: Session = Depends(get_db)):
    project = crud.get_business_project(db, project_id)
    if not project:
        raise HTTPException(404, "Projekt nicht gefunden")
    return crud.mark_business_project_checked(db, project)


@business_life_router.get("/business-issues", response_model=List[schemas.BusinessIssueOut])
def list_business_issues(project_id: Optional[int] = None, include_resolved: bool = False, db: Session = Depends(get_db)):
    return crud.get_business_issues(db, project_id, include_resolved)


@business_life_router.post("/business-issues", response_model=schemas.BusinessIssueOut)
def create_business_issue(data: schemas.BusinessIssueCreate, db: Session = Depends(get_db)):
    project = crud.get_business_project(db, data.project_id)
    if not project:
        raise HTTPException(404, "Projekt nicht gefunden")
    project.last_checked_at = datetime.utcnow()
    db.commit()
    return crud.create_business_issue(db, data.project_id, data.title, data.notes)


@business_life_router.post("/business-issues/{issue_id}/resolve", response_model=schemas.BusinessIssueOut)
def resolve_business_issue(issue_id: int, db: Session = Depends(get_db)):
    issue = db.query(models.BusinessIssue).filter(models.BusinessIssue.id == issue_id).first()
    if not issue:
        raise HTTPException(404, "Eintrag nicht gefunden")
    return crud.resolve_business_issue(db, issue)


# ---------------- Leben (persönliche Lebensbereiche) ----------------
@business_life_router.get("/life-areas", response_model=List[schemas.LifeAreaOut])
def list_life_areas(include_inactive: bool = False, db: Session = Depends(get_db)):
    return crud.get_life_areas(db, include_inactive)


@business_life_router.post("/life-areas", response_model=schemas.LifeAreaOut)
def create_life_area(data: schemas.LifeAreaCreate, db: Session = Depends(get_db)):
    return crud.create_life_area(db, data)


@business_life_router.patch("/life-areas/{area_id}", response_model=schemas.LifeAreaOut)
def update_life_area(area_id: int, data: schemas.LifeAreaUpdate, db: Session = Depends(get_db)):
    area = crud.get_life_area(db, area_id)
    if not area:
        raise HTTPException(404, "Lebensbereich nicht gefunden")
    return crud.update_life_area(db, area, data)


@business_life_router.get("/life-areas/heatmap")
def life_areas_heatmap(days: int = 371, area_id: Optional[int] = None, db: Session = Depends(get_db)):
    return crud.life_heatmap(db, days=max(7, min(days, 400)), area_id=area_id)


@business_life_router.get("/life-checkins", response_model=List[schemas.LifeCheckInOut])
def list_life_checkins(area_id: Optional[int] = None, db: Session = Depends(get_db)):
    return crud.get_life_checkins(db, area_id)


@business_life_router.post("/life-checkins", response_model=schemas.LifeCheckInOut)
def create_life_checkin(data: schemas.LifeCheckInCreate, db: Session = Depends(get_db)):
    area = crud.get_life_area(db, data.area_id)
    if not area:
        raise HTTPException(404, "Lebensbereich nicht gefunden")
    return crud.create_life_checkin(db, data.area_id, data.note, data.progress_percent)

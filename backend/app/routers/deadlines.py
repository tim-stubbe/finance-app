"""Kündigungsfristen (Abos) + Rückgabefristen (einzelne Käufe).

Zehnter Schritt der Code-Modularisierung (siehe ROADMAP.md), nach
investments/tax/debts/goals/trips/wishlist/personal/business_life/
budgets_alerts. Beide Domänen sind "Fristen zu bestehenden Buchungen/Abos"
und standen im selben main.py-Abschnitt. Reine Verschiebung ohne
Verhaltensänderung."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import schemas, crud, auth
from ..database import get_db

deadlines_router = APIRouter(prefix="/api")


# ---------------- Kündigungsfristen ----------------
@deadlines_router.get("/contract-reminders", response_model=List[schemas.ContractReminderOut])
def list_contract_reminders(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.get_contract_reminders(db, space_id)


@deadlines_router.post("/contract-reminders", response_model=schemas.ContractReminderOut)
def add_contract_reminder(
    data: schemas.ContractReminderCreate,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    try:
        return crud.create_contract_reminder(db, space_id, data)
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Für dieses Abo ist schon eine Kündigungsfrist hinterlegt.")


@deadlines_router.put("/contract-reminders/{reminder_id}", response_model=schemas.ContractReminderOut)
def edit_contract_reminder(
    reminder_id: int,
    data: schemas.ContractReminderUpdate,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    result = crud.update_contract_reminder(db, reminder_id, space_id, data)
    if not result:
        raise HTTPException(404, "Erinnerung nicht gefunden.")
    return result


@deadlines_router.delete("/contract-reminders/{reminder_id}")
def remove_contract_reminder(
    reminder_id: int,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    if not crud.delete_contract_reminder(db, reminder_id, space_id):
        raise HTTPException(404, "Erinnerung nicht gefunden.")
    return {"ok": True}


# ---------------- Rückgabefristen ----------------
@deadlines_router.get("/return-deadlines", response_model=List[schemas.ReturnDeadlineOut])
def list_return_deadlines(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.get_return_deadlines(db, space_id)


@deadlines_router.post("/return-deadlines", response_model=schemas.ReturnDeadlineOut)
def add_return_deadline(
    data: schemas.ReturnDeadlineCreate,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    try:
        result = crud.create_return_deadline(db, space_id, data)
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Für diese Buchung ist schon eine Rückgabefrist hinterlegt.")
    if not result:
        raise HTTPException(404, "Buchung nicht gefunden.")
    return result


@deadlines_router.put("/return-deadlines/{deadline_id}", response_model=schemas.ReturnDeadlineOut)
def edit_return_deadline(
    deadline_id: int,
    data: schemas.ReturnDeadlineUpdate,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    result = crud.update_return_deadline(db, deadline_id, space_id, data)
    if not result:
        raise HTTPException(404, "Rückgabefrist nicht gefunden.")
    return result


@deadlines_router.delete("/return-deadlines/{deadline_id}")
def remove_return_deadline(
    deadline_id: int,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    if not crud.delete_return_deadline(db, deadline_id, space_id):
        raise HTTPException(404, "Rückgabefrist nicht gefunden.")
    return {"ok": True}

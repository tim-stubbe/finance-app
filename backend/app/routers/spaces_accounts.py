"""Spaces (Bereiche, z.B. Privat) + Accounts (Konten).

Siebzehnter Schritt der Code-Modularisierung (siehe ROADMAP.md), nach
investments/tax/debts/goals/trips/wishlist/personal/business_life/
budgets_alerts/deadlines/calendar_todos/categories/immich_routes/
bank_connections/enablebanking_ebay/mail_routes. Spaces sind die
Grundlage, aus der `auth.get_active_space_id` den aktiven Bereich
ermittelt (Session-basiert, siehe current_space) - Accounts hängen direkt
daran und standen im selben main.py-Abschnitt. Reine Verschiebung ohne
Verhaltensänderung."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import schemas, crud, auth
from ..database import get_db

spaces_accounts_router = APIRouter(prefix="/api")


# ---------------- Spaces (Bereiche) ----------------
@spaces_accounts_router.get("/spaces", response_model=List[schemas.SpaceOut])
def list_spaces(db: Session = Depends(get_db)):
    return crud.get_spaces(db)


@spaces_accounts_router.post("/spaces", response_model=schemas.SpaceOut)
def create_space(data: schemas.SpaceCreate, db: Session = Depends(get_db)):
    return crud.create_space(db, data)


@spaces_accounts_router.delete("/spaces/{space_id}")
def remove_space(space_id: int, request: Request, db: Session = Depends(get_db)):
    space = crud.delete_space(db, space_id)
    if not space:
        raise HTTPException(404, "Bereich nicht gefunden")
    if request.session.get("space_id") == space_id:
        request.session.pop("space_id", None)
    return {"ok": True}


@spaces_accounts_router.post("/spaces/{space_id}/select", response_model=schemas.SpaceOut)
def select_space(space_id: int, request: Request, db: Session = Depends(get_db)):
    space = crud.get_space(db, space_id)
    if not space:
        raise HTTPException(404, "Bereich nicht gefunden")
    request.session["space_id"] = space_id
    return space


@spaces_accounts_router.get("/spaces/current")
def current_space(request: Request, db: Session = Depends(get_db)):
    space_id = request.session.get("space_id")
    if not space_id:
        # Gibt es nur einen Bereich, automatisch übernehmen - siehe
        # auth.get_active_space_id für die Begründung. Ohne das würde die
        # Bereichsauswahl beim ersten Laden trotzdem kurz aufblitzen.
        spaces = crud.get_spaces(db)
        if len(spaces) == 1:
            space_id = spaces[0].id
            request.session["space_id"] = space_id
        else:
            return None
    space = crud.get_space(db, space_id)
    if not space:
        request.session.pop("space_id", None)
        return None
    return schemas.SpaceOut.model_validate(space)


# ---------------- Accounts ----------------
@spaces_accounts_router.get("/accounts", response_model=List[schemas.AccountOut])
def list_accounts(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    accounts = crud.get_accounts(db, space_id)
    result = []
    for acc in accounts:
        bal = crud.account_balance(db, acc)
        result.append(
            schemas.AccountOut(
                id=acc.id, name=acc.name, type=acc.type,
                initial_balance=acc.initial_balance, is_business=acc.is_business,
                created_at=acc.created_at, current_balance=bal,
            )
        )
    return result


@spaces_accounts_router.post("/accounts", response_model=schemas.AccountOut)
def create_account(account: schemas.AccountCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    acc = crud.create_account(db, account, space_id)
    return schemas.AccountOut(
        id=acc.id, name=acc.name, type=acc.type,
        initial_balance=acc.initial_balance, is_business=acc.is_business,
        created_at=acc.created_at, current_balance=acc.initial_balance,
    )


@spaces_accounts_router.put("/accounts/{account_id}", response_model=schemas.AccountOut)
def update_account(account_id: int, data: schemas.AccountUpdate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    acc = crud.update_account(db, account_id, space_id, data)
    if not acc:
        raise HTTPException(404, "Konto nicht gefunden")
    bal = crud.account_balance(db, acc)
    return schemas.AccountOut(
        id=acc.id, name=acc.name, type=acc.type,
        initial_balance=acc.initial_balance, is_business=acc.is_business,
        created_at=acc.created_at, current_balance=bal,
    )


@spaces_accounts_router.delete("/accounts/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    acc = crud.delete_account(db, account_id, space_id)
    if not acc:
        raise HTTPException(404, "Konto nicht gefunden")
    return {"ok": True}


@spaces_accounts_router.get("/accounts/balance-log", response_model=List[schemas.AccountBalanceLogOut])
def get_balance_log(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.recent_balance_changes(db, space_id)

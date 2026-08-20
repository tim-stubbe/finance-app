"""Schulden-Endpunkte (Kredite, Zahlungen, Tilgungsplan).

Dritter Schritt der Code-Modularisierung (siehe ROADMAP.md), nach
routers/investments.py und routers/tax_endpoints.py. Reine Verschiebung ohne
Verhaltensänderung. `app/debts.py` (Berechnungslogik: Tilgungsplan, Zinsen)
bleibt unverändert und wird hier importiert - `app.debts` und
`app.routers.debts` sind unterschiedliche Modulpfade, keine Kollision."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, crud, auth, debts
from ..database import get_db

debts_router = APIRouter(prefix="/api")


def _debt_out(db: Session, debt: models.Debt, with_projection: bool = False) -> schemas.DebtOut:
    out = schemas.DebtOut.model_validate(debt)
    out.account_name = debt.account.name if debt.account else None
    out.payment_count = len(debt.payments)
    out.total_interest_paid = debts.total_interest_paid(debt)
    out.total_fees_paid = debts.total_fees_paid(debt)
    out.monthly_total_burden = round((debt.monthly_payment or 0.0) + debts.monthly_side_costs(debt), 2)
    out.monthly_commitment_interest = debts.monthly_commitment_interest(debt)
    paid_off = round(debt.original_amount - max(0.0, debt.current_balance), 2)
    out.paid_off_amount = paid_off
    out.paid_off_percent = round(paid_off / debt.original_amount * 100, 1) if debt.original_amount else 0.0
    if with_projection:
        rows, note = debts.projection(debt)
        out.projection_note = note
        out.balance_at_fixed_interest_end = debts.balance_at_fixed_interest_end(debt)
        if rows:
            out.projected_end_date = rows[-1].date
            out.projected_remaining_interest = round(sum(r.interest for r in rows), 2)
            out.projected_remaining_fees = round(sum(r.fee for r in rows), 2)
    return out


@debts_router.get("/debts", response_model=List[schemas.DebtOut])
def list_debts(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return [_debt_out(db, d) for d in crud.get_debts(db, space_id)]


@debts_router.get("/debts/summary", response_model=schemas.DebtSummaryOut)
def get_debt_summary(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.debt_summary(db, space_id)


@debts_router.get("/debts/{debt_id}", response_model=schemas.DebtOut)
def get_debt(debt_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    debt = crud.get_debt(db, debt_id, space_id)
    if not debt:
        raise HTTPException(404, "Kredit nicht gefunden")
    return _debt_out(db, debt, with_projection=True)


@debts_router.post("/debts", response_model=schemas.DebtOut)
def create_debt(data: schemas.DebtCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if data.original_amount <= 0:
        raise HTTPException(400, "Der Kreditbetrag muss größer als 0 sein")
    if data.account_id and not crud.get_account(db, data.account_id, space_id):
        raise HTTPException(400, "Das gewählte Konto existiert nicht in diesem Bereich")
    return _debt_out(db, crud.create_debt(db, data, space_id))


@debts_router.put("/debts/{debt_id}", response_model=schemas.DebtOut)
def update_debt(debt_id: int, data: schemas.DebtUpdate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if data.account_id and not crud.get_account(db, data.account_id, space_id):
        raise HTTPException(400, "Das gewählte Konto existiert nicht in diesem Bereich")
    debt = crud.update_debt(db, debt_id, space_id, data)
    if not debt:
        raise HTTPException(404, "Kredit nicht gefunden")
    return _debt_out(db, debt, with_projection=True)


@debts_router.delete("/debts/{debt_id}")
def delete_debt(debt_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if not crud.delete_debt(db, debt_id, space_id):
        raise HTTPException(404, "Kredit nicht gefunden")
    return {"ok": True}


@debts_router.get("/debts/{debt_id}/payments", response_model=List[schemas.DebtPaymentOut])
def list_debt_payments(debt_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    debt = crud.get_debt(db, debt_id, space_id)
    if not debt:
        raise HTTPException(404, "Kredit nicht gefunden")
    by_id = {p.id: p for p in debt.payments}
    return [
        schemas.DebtPaymentOut(
            id=r.payment_id, date=r.date, total_amount=r.total_amount,
            interest_amount=r.interest_amount, fee_amount=r.fee_amount,
            principal_amount=r.principal_amount,
            balance_after=r.balance_after, is_extra_repayment=r.is_extra_repayment,
            interest_is_manual=r.interest_is_manual,
            transaction_id=by_id[r.payment_id].transaction_id,
            notes=by_id[r.payment_id].notes,
        )
        for r in debts.payment_breakdown(debt)
    ]


@debts_router.post("/debts/{debt_id}/payments", response_model=schemas.DebtPaymentOut)
def create_debt_payment(debt_id: int, data: schemas.DebtPaymentCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if data.transaction_id and not crud.get_transaction(db, data.transaction_id, space_id):
        raise HTTPException(400, "Die verknüpfte Buchung existiert nicht in diesem Bereich")
    payment = crud.create_debt_payment(db, debt_id, space_id, data)
    if not payment:
        raise HTTPException(404, "Kredit nicht gefunden")
    return _payment_out(db, debt_id, space_id, payment.id)


@debts_router.put("/debts/{debt_id}/payments/{payment_id}", response_model=schemas.DebtPaymentOut)
def update_debt_payment(debt_id: int, payment_id: int, data: schemas.DebtPaymentUpdate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if data.transaction_id and not crud.get_transaction(db, data.transaction_id, space_id):
        raise HTTPException(400, "Die verknüpfte Buchung existiert nicht in diesem Bereich")
    if not crud.update_debt_payment(db, payment_id, debt_id, space_id, data):
        raise HTTPException(404, "Zahlung nicht gefunden")
    return _payment_out(db, debt_id, space_id, payment_id)


@debts_router.delete("/debts/{debt_id}/payments/{payment_id}")
def delete_debt_payment(debt_id: int, payment_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if not crud.delete_debt_payment(db, payment_id, debt_id, space_id):
        raise HTTPException(404, "Zahlung nicht gefunden")
    return {"ok": True}


def _payment_out(db: Session, debt_id: int, space_id: int, payment_id: int) -> schemas.DebtPaymentOut:
    """Nach jeder Änderung wird die ganze Kette neu aufgeteilt - deshalb kommt die
    Antwort aus dem frisch gerechneten Verlauf und nicht aus dem ORM-Objekt."""
    debt = crud.get_debt(db, debt_id, space_id)
    row = next(r for r in debts.payment_breakdown(debt) if r.payment_id == payment_id)
    payment = next(p for p in debt.payments if p.id == payment_id)
    return schemas.DebtPaymentOut(
        id=row.payment_id, date=row.date, total_amount=row.total_amount,
        interest_amount=row.interest_amount, fee_amount=row.fee_amount,
        principal_amount=row.principal_amount,
        balance_after=row.balance_after, is_extra_repayment=row.is_extra_repayment,
        interest_is_manual=row.interest_is_manual,
        transaction_id=payment.transaction_id, notes=payment.notes,
    )


@debts_router.get("/debts/{debt_id}/schedule", response_model=schemas.DebtScheduleOut)
def get_debt_schedule(debt_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    debt = crud.get_debt(db, debt_id, space_id)
    if not debt:
        raise HTTPException(404, "Kredit nicht gefunden")
    rows, note = debts.projection(debt)
    return schemas.DebtScheduleOut(
        rows=[schemas.DebtScheduleRow(**r._asdict()) for r in rows],
        note=note,
        total_interest=round(sum(r.interest for r in rows), 2),
        total_fees=round(sum(r.fee for r in rows), 2),
        end_date=rows[-1].date if rows else None,
    )

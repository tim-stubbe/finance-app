"""Trips (Reisen mit Budget-Tracking) und KI-Review-Queue (Kategorisierungs-
vorschläge) - siebter Schritt der crud.py-Modularisierung (siehe
ROADMAP.md), analog zu crud_misc.py. Reine Verschiebung ohne
Verhaltensänderung: zwei kleinere, voneinander unabhängige Domänen wurden
hier zusammengefasst statt zwei Mini-Module anzulegen.

crud.py importiert alle hier definierten Namen zurück, damit jeder
bestehende `crud.get_trips(...)`-Aufrufstil in main.py/routers/
unverändert weiterfunktioniert."""

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models, schemas


# ---------- Trips ----------
def get_trips(db: Session, space_id: int):
    return db.query(models.Trip).filter(models.Trip.space_id == space_id).order_by(models.Trip.start_date.desc()).all()


def get_trip(db: Session, trip_id: int, space_id: int):
    return db.query(models.Trip).filter(models.Trip.id == trip_id, models.Trip.space_id == space_id).first()


def create_trip(db: Session, data: schemas.TripCreate, space_id: int):
    trip = models.Trip(**data.model_dump(), space_id=space_id)
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return trip


def update_trip(db: Session, trip_id: int, space_id: int, data: schemas.TripUpdate):
    trip = get_trip(db, trip_id, space_id)
    if not trip:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(trip, key, value)
    db.commit()
    db.refresh(trip)
    return trip


def delete_trip(db: Session, trip_id: int, space_id: int):
    trip = get_trip(db, trip_id, space_id)
    if trip:
        db.query(models.Transaction).filter(models.Transaction.trip_id == trip_id).update({"trip_id": None})
        db.delete(trip)
        db.commit()
    return trip


def trip_summary(db: Session, trip: models.Trip):
    total = (
        db.query(func.coalesce(func.sum(models.Transaction.amount), 0.0))
        .filter(models.Transaction.trip_id == trip.id)
        .scalar()
    )
    count = (
        db.query(func.count(models.Transaction.id))
        .filter(models.Transaction.trip_id == trip.id)
        .scalar()
    )
    return schemas.TripOut(
        id=trip.id,
        name=trip.name,
        start_date=trip.start_date,
        end_date=trip.end_date,
        budget=trip.budget,
        total_spent=round(abs(min(0.0, total or 0.0)), 2),
        transaction_count=count or 0,
    )


# ---------- KI-Review-Queue (Kategorisierungsvorschläge) ----------
def _category_suggestion_out(s: models.CategorySuggestion) -> schemas.CategorySuggestionOut:
    return schemas.CategorySuggestionOut(
        id=s.id, transaction_id=s.transaction_id,
        transaction_description=s.transaction.description, transaction_amount=s.transaction.amount,
        transaction_date=s.transaction.date,
        suggested_category_id=s.suggested_category_id, suggested_category_name=s.suggested_category.name,
        confidence=s.confidence, created_at=s.created_at,
    )


def get_pending_category_suggestions(db: Session, space_id: int, limit: int = 100) -> list[schemas.CategorySuggestionOut]:
    rows = (
        db.query(models.CategorySuggestion)
        .join(models.Transaction, models.CategorySuggestion.transaction_id == models.Transaction.id)
        .join(models.Account, models.Transaction.account_id == models.Account.id)
        .filter(
            models.CategorySuggestion.status == models.CategorySuggestionStatus.pending,
            models.Account.space_id == space_id,
            # Zwischenzeitlich anderweitig kategorisiert (z.B. manuell) -
            # dann ist der Vorschlag hinfällig, taucht aber nicht mehr in
            # dieser Abfrage auf statt aktiv aufgeräumt zu werden (kein
            # Korrektheitsproblem, nur Karteileichen in der Tabelle).
            models.Transaction.category_id.is_(None),
        )
        .order_by(models.CategorySuggestion.confidence.desc())
        .limit(limit)
        .all()
    )
    return [_category_suggestion_out(s) for s in rows]


def decide_category_suggestion(db: Session, suggestion_id: int, space_id: int, accept: bool) -> schemas.CategorySuggestionOut | None:
    suggestion = (
        db.query(models.CategorySuggestion)
        .join(models.Transaction, models.CategorySuggestion.transaction_id == models.Transaction.id)
        .join(models.Account, models.Transaction.account_id == models.Account.id)
        .filter(models.CategorySuggestion.id == suggestion_id, models.Account.space_id == space_id)
        .first()
    )
    if not suggestion:
        return None
    out = _category_suggestion_out(suggestion)
    if accept and suggestion.transaction.category_id is None:
        suggestion.transaction.category_id = suggestion.suggested_category_id
        suggestion.transaction.categorized_at = datetime.utcnow()
    suggestion.status = models.CategorySuggestionStatus.accepted if accept else models.CategorySuggestionStatus.rejected
    suggestion.decided_at = datetime.utcnow()
    db.commit()
    return out


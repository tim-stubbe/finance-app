"""Trips-Endpunkte (Urlaube/Reisekosten).

Fünfter Schritt der Code-Modularisierung (siehe ROADMAP.md), nach
investments/tax/debts/goals. Reine Verschiebung ohne Verhaltensänderung -
kleinster und einfachster Baustein bisher, keine lokalen Hilfsfunktionen,
nur direkte crud.py-Aufrufe."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas, crud, auth
from ..database import get_db

trips_router = APIRouter(prefix="/api")


@trips_router.get("/trips", response_model=List[schemas.TripOut])
def list_trips(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    trips = crud.get_trips(db, space_id)
    return [crud.trip_summary(db, t) for t in trips]


@trips_router.post("/trips", response_model=schemas.TripOut)
def create_trip(data: schemas.TripCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    trip = crud.create_trip(db, data, space_id)
    return crud.trip_summary(db, trip)


@trips_router.put("/trips/{trip_id}", response_model=schemas.TripOut)
def update_trip(trip_id: int, data: schemas.TripUpdate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    trip = crud.update_trip(db, trip_id, space_id, data)
    if not trip:
        raise HTTPException(404, "Trip nicht gefunden")
    return crud.trip_summary(db, trip)


@trips_router.delete("/trips/{trip_id}")
def delete_trip(trip_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    trip = crud.delete_trip(db, trip_id, space_id)
    if not trip:
        raise HTTPException(404, "Trip nicht gefunden")
    return {"ok": True}

"""Kategorie-Endpunkte (global, bereichsübergreifend - siehe models.Category).

Zwölfter Schritt der Code-Modularisierung (siehe ROADMAP.md). Reine
Verschiebung ohne Verhaltensänderung. /categories/trend stand an anderer
Stelle in main.py (bei den Dashboard-Trend-Endpunkten) als eigenständige,
kleine Funktion ohne lokale Abhängigkeiten - hier trotzdem mit hereingezogen,
weil sie inhaltlich zu Categories gehört."""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas, crud, auth
from ..database import get_db

categories_router = APIRouter(prefix="/api")


@categories_router.get("/categories", response_model=List[schemas.CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return crud.get_categories(db)


@categories_router.get("/categories/totals")
def get_category_totals(year: int = date.today().year, month: Optional[int] = None, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.category_totals(db, space_id, year, month)


@categories_router.get("/categories/sign-mismatches", response_model=List[schemas.CategorySignMismatch])
def get_category_sign_mismatches(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.category_sign_mismatches(db, space_id)


@categories_router.post("/categories", response_model=schemas.CategoryOut)
def create_category(category: schemas.CategoryCreate, db: Session = Depends(get_db)):
    return crud.create_category(db, category)


@categories_router.put("/categories/{category_id}", response_model=schemas.CategoryOut)
def update_category(category_id: int, data: schemas.CategoryUpdate, db: Session = Depends(get_db)):
    cat = crud.update_category(db, category_id, data)
    if not cat:
        raise HTTPException(404, "Kategorie nicht gefunden")
    return cat


@categories_router.delete("/categories/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db)):
    cat = crud.delete_category(db, category_id)
    if not cat:
        raise HTTPException(404, "Kategorie nicht gefunden")
    return {"ok": True}


@categories_router.get("/categories/trend", response_model=schemas.CategoryTrendOut)
def get_category_trend(months: int = 6, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    months = max(2, min(months, 24))
    data = crud.category_spending_trend(db, space_id, months)
    return schemas.CategoryTrendOut(
        months=data["months"],
        series=[schemas.CategoryTrendSeries(**s) for s in data["series"]],
    )

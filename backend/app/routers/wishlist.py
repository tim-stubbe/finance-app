"""Wunschlisten-Endpunkte (Deal-Wecker).

Sechster Schritt der Code-Modularisierung (siehe ROADMAP.md), nach
investments/tax/debts/goals/trips. Reine Verschiebung ohne
Verhaltensänderung. Bewusst kein `space_id`-Filter, wie im bestehenden
Verhalten (WishlistItem ist bereichsübergreifend, siehe models.WishlistItem)."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas, crud
from ..database import get_db

wishlist_router = APIRouter(prefix="/api")


@wishlist_router.get("/wishlist", response_model=List[schemas.WishlistItemOut])
def list_wishlist_items(include_inactive: bool = False, db: Session = Depends(get_db)):
    return crud.get_wishlist_items(db, include_inactive)


@wishlist_router.post("/wishlist", response_model=schemas.WishlistItemOut)
def create_wishlist_item(data: schemas.WishlistItemCreate, db: Session = Depends(get_db)):
    return crud.create_wishlist_item(db, data)


@wishlist_router.patch("/wishlist/{item_id}", response_model=schemas.WishlistItemOut)
def update_wishlist_item(item_id: int, data: schemas.WishlistItemUpdate, db: Session = Depends(get_db)):
    item = crud.get_wishlist_item(db, item_id)
    if not item:
        raise HTTPException(404, "Eintrag nicht gefunden")
    return crud.update_wishlist_item(db, item, data)


@wishlist_router.post("/wishlist/{item_id}/checked", response_model=schemas.WishlistItemOut)
def mark_wishlist_item_checked(item_id: int, db: Session = Depends(get_db)):
    item = crud.get_wishlist_item(db, item_id)
    if not item:
        raise HTTPException(404, "Eintrag nicht gefunden")
    return crud.mark_wishlist_item_checked(db, item)

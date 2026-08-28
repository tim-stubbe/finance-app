"""Essensplanung: Rezepte + Wochenplan + Einkaufsliste (Phase 7 der
Smart-Home-Ausbau-Liste, siehe ROADMAP.md). Eigenes crud_*-Modul, in
crud.py zurueckimportiert.
"""

import re
from datetime import date

from sqlalchemy.orm import Session

from . import models


# ---------------- Rezepte ----------------
def _recipe_out(r: models.Recipe) -> dict:
    return {
        "id": r.id, "name": r.name,
        "ingredients": r.ingredients or "",
        "instructions": r.instructions or "",
        "servings": r.servings, "tags": r.tags or "",
        "source": r.source or "manuell",
    }


def get_recipes(db: Session):
    return [_recipe_out(r) for r in
            db.query(models.Recipe).order_by(models.Recipe.name).all()]


def get_recipe(db: Session, recipe_id: int):
    r = db.query(models.Recipe).filter_by(id=recipe_id).first()
    return _recipe_out(r) if r else None


def create_recipe(db: Session, data: dict) -> dict:
    r = models.Recipe(
        name=(data.get("name") or "Rezept").strip(),
        ingredients=(data.get("ingredients") or "").strip() or None,
        instructions=(data.get("instructions") or "").strip() or None,
        servings=data.get("servings"),
        tags=(data.get("tags") or "").strip() or None,
        source=data.get("source") or "manuell",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return _recipe_out(r)


def update_recipe(db: Session, recipe_id: int, data: dict):
    r = db.query(models.Recipe).filter_by(id=recipe_id).first()
    if not r:
        return None
    for k in ("name", "ingredients", "instructions", "tags"):
        if k in data and data[k] is not None:
            setattr(r, k, str(data[k]).strip() or None)
    if "servings" in data:
        r.servings = data["servings"]
    db.commit()
    db.refresh(r)
    return _recipe_out(r)


def delete_recipe(db: Session, recipe_id: int) -> bool:
    r = db.query(models.Recipe).filter_by(id=recipe_id).first()
    if not r:
        return False
    db.query(models.MealPlanEntry).filter_by(recipe_id=recipe_id).update({"recipe_id": None})
    db.delete(r)
    db.commit()
    return True


# ---------------- Wochenplan ----------------
def get_meal_plan(db: Session, start: date, end: date):
    rows = (
        db.query(models.MealPlanEntry)
        .filter(models.MealPlanEntry.date >= start, models.MealPlanEntry.date <= end)
        .all()
    )
    by_recipe = {r.id: r for r in db.query(models.Recipe).all()}
    out = []
    for e in rows:
        rec = by_recipe.get(e.recipe_id)
        out.append({
            "id": e.id, "date": e.date.isoformat(), "meal": e.meal,
            "recipe_id": e.recipe_id,
            "recipe_name": rec.name if rec else None,
            "note": e.note or "",
        })
    return out


def set_meal_plan_entry(db: Session, d: date, meal: str, recipe_id=None, note=None):
    e = db.query(models.MealPlanEntry).filter_by(date=d, meal=meal).first()
    if not e:
        e = models.MealPlanEntry(date=d, meal=meal)
        db.add(e)
    e.recipe_id = recipe_id
    e.note = (note or "").strip() or None
    db.commit()
    db.refresh(e)
    return {"id": e.id, "date": d.isoformat(), "meal": meal,
            "recipe_id": recipe_id, "note": e.note or ""}


def clear_meal_plan_entry(db: Session, d: date, meal: str) -> bool:
    e = db.query(models.MealPlanEntry).filter_by(date=d, meal=meal).first()
    if not e:
        return False
    db.delete(e)
    db.commit()
    return True


# ---------------- Einkaufsliste ----------------
_QTY_RE = re.compile(r"^\s*([\d.,/]+)\s*(g|kg|ml|l|el|tl|stk|stück|dose|dosen|packung|prise|bund)?\s+(.*)$", re.I)


def shopping_list(db: Session, start: date, end: date):
    """Zutaten aller im Zeitraum verplanten Rezepte, grob zusammengefasst.
    Kein Mengen-Rechnen ueber Einheiten hinweg - gleiche Zutat wird gebuendelt,
    die einzelnen Mengenangaben bleiben als Text erhalten."""
    entries = get_meal_plan(db, start, end)
    recipe_ids = {e["recipe_id"] for e in entries if e["recipe_id"]}
    merged = {}
    for rid in recipe_ids:
        rec = db.query(models.Recipe).filter_by(id=rid).first()
        if not rec or not rec.ingredients:
            continue
        for line in rec.ingredients.splitlines():
            line = line.strip(" -•\t")
            if not line:
                continue
            m = _QTY_RE.match(line)
            key = (m.group(3) if m else line).strip().lower()
            merged.setdefault(key, {"item": (m.group(3).strip() if m else line), "parts": []})
            if m and m.group(1):
                merged[key]["parts"].append((m.group(1) + " " + (m.group(2) or "")).strip())
    out = []
    for v in merged.values():
        out.append({"item": v["item"], "amounts": ", ".join(p for p in v["parts"] if p)})
    out.sort(key=lambda x: x["item"].lower())
    return out

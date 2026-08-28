"""Essensplanung: Rezepte, Wochenplan, KI-Rezeptvorschlaege, Einkaufsliste
(-> Wunschliste / To-do). Siehe crud_meals.py.
"""

import json
import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas, auth, crud, ollama_client
from ..database import get_db

meals_router = APIRouter(prefix="/api/meals")

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

SUGGEST_SYSTEM = (
    "Du schlaegst einfache Alltagsgerichte vor. Antworte NUR mit JSON:\n"
    '{"recipes": [{"name": "...", "ingredients": ["Menge Zutat", ...], '
    '"instructions": "kurze Schritte", "servings": 2, "tags": "vegetarisch, schnell"}]}'
)


# ---------------- Rezepte ----------------
@meals_router.get("/recipes")
def list_recipes(db: Session = Depends(get_db)):
    return crud.get_recipes(db)


@meals_router.post("/recipes")
def create_recipe(data: schemas.RecipeIn, db: Session = Depends(get_db)):
    return crud.create_recipe(db, data.model_dump())


@meals_router.put("/recipes/{recipe_id}")
def update_recipe(recipe_id: int, data: schemas.RecipeIn, db: Session = Depends(get_db)):
    out = crud.update_recipe(db, recipe_id, data.model_dump())
    if not out:
        raise HTTPException(404, "Rezept nicht gefunden.")
    return out


@meals_router.delete("/recipes/{recipe_id}")
def delete_recipe(recipe_id: int, db: Session = Depends(get_db)):
    if not crud.delete_recipe(db, recipe_id):
        raise HTTPException(404, "Rezept nicht gefunden.")
    return {"ok": True}


@meals_router.post("/recipes/suggest")
def suggest_recipes(data: schemas.MealSuggestIn, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    if not s.ollama_url or not s.ollama_model:
        raise HTTPException(400, "Kein Ollama-Modell eingerichtet (Einstellungen -> KI-Assistent).")
    n = max(1, min(data.count, 8))
    user = f"Schlage {n} Gerichte vor."
    if (data.prompt or "").strip():
        user += f" Beruecksichtige: {data.prompt.strip()}"
    try:
        raw = ollama_client.chat(s.ollama_url, s.ollama_model,
                                 [{"role": "system", "content": SUGGEST_SYSTEM},
                                  {"role": "user", "content": user}], timeout=180)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"KI nicht erreichbar: {exc}")
    m = _FENCE.search(raw)
    txt = m.group(1) if m else raw
    try:
        parsed = json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
        recipes = parsed.get("recipes") or []
    except (ValueError, TypeError):
        recipes = []
    out = []
    for r in recipes[:n]:
        if not isinstance(r, dict) or not r.get("name"):
            continue
        ing = r.get("ingredients")
        out.append({
            "name": str(r["name"]).strip(),
            "ingredients": "\n".join(ing) if isinstance(ing, list) else str(ing or ""),
            "instructions": str(r.get("instructions") or "").strip(),
            "servings": r.get("servings"),
            "tags": str(r.get("tags") or "").strip(),
        })
    return out


# ---------------- Wochenplan ----------------
@meals_router.get("/plan")
def get_plan(date_from: date, date_to: date, db: Session = Depends(get_db)):
    return crud.get_meal_plan(db, date_from, date_to)


@meals_router.put("/plan")
def put_plan(data: schemas.MealPlanIn, db: Session = Depends(get_db)):
    if data.meal not in ("mittag", "abend"):
        raise HTTPException(400, "meal muss 'mittag' oder 'abend' sein.")
    return crud.set_meal_plan_entry(db, data.date, data.meal, data.recipe_id, data.note)


@meals_router.delete("/plan")
def del_plan(day: date, meal: str, db: Session = Depends(get_db)):
    crud.clear_meal_plan_entry(db, day, meal)
    return {"ok": True}


# ---------------- Einkaufsliste ----------------
@meals_router.get("/shopping-list")
def get_shopping_list(date_from: date, date_to: date, db: Session = Depends(get_db)):
    return crud.shopping_list(db, date_from, date_to)


@meals_router.post("/shopping-list/push")
def push_shopping_list(data: schemas.ShoppingPushIn, db: Session = Depends(get_db)):
    items = crud.shopping_list(db, data.date_from, data.date_to)
    if not items:
        raise HTTPException(400, "Keine verplanten Rezepte im Zeitraum.")
    added = 0
    for it in items:
        label = it["item"] + (f" ({it['amounts']})" if it["amounts"] else "")
        if data.target == "todo":
            crud.create_todo(db, f"Einkauf: {label}", None)
        else:
            crud.create_wishlist_item(db, schemas.WishlistItemCreate(name=label))
        added += 1
    return {"ok": True, "added": added, "target": data.target}

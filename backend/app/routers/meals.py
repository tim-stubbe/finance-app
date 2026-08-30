"""Essensplanung: Rezepte, Wochenplan, KI-Rezeptvorschlaege, Einkaufsliste
(-> Wunschliste / To-do). Siehe crud_meals.py.
"""

import json
import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas, auth, crud, models, ollama_client
from ..database import get_db

meals_router = APIRouter(prefix="/api/meals")

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

SUGGEST_SYSTEM = (
    "Du schlaegst einfache Alltagsgerichte vor, passend zum Ernaehrungsziel des "
    "Nutzers. Schaetze die Naehrwerte PRO PORTION grob ab. Antworte NUR mit JSON:\n"
    '{"recipes": [{"name": "...", "ingredients": ["Menge Zutat", ...], '
    '"instructions": "kurze Schritte", "servings": 2, "tags": "vegetarisch, schnell", '
    '"kcal": 650, "protein": 30, "carbs": 60, "fat": 25}]}'
)

_GOAL_HINT = {
    "zunehmen": ("Ziel: gesund ZUNEHMEN. Schlage kalorienreiche, naehrstoffdichte "
                 "Gerichte vor (gesunde Fette wie Nuesse, Oel, Avocado, Kaese; "
                 "genug Eiweiss; keine 'leichten' Salate als Hauptmahlzeit). "
                 "Richtwert 600-900 kcal pro Portion."),
    "muskelaufbau": ("Ziel: MUSKELAUFBAU. Eiweissreich (>=30 g Protein pro Portion), "
                     "moderater Kalorienueberschuss, komplexe Kohlenhydrate."),
    "abnehmen": ("Ziel: ABNEHMEN. Saettigende, eiweiss- und gemuesereiche Gerichte "
                 "mit moderaten Kalorien (350-550 kcal pro Portion), wenig Zucker."),
    "halten": ("Ziel: Gewicht HALTEN. Ausgewogene Alltagsgerichte."),
}


def _nutrition_profile_dict(db) -> dict:
    s = auth.get_or_create_settings(db)
    goal = (s.nutrition_goal or "halten")
    out = {
        "nutrition_goal": goal,
        "nutrition_prefs": s.nutrition_prefs or "",
        "nutrition_kcal_target": s.nutrition_kcal_target,
        "height_cm": s.height_cm,
        "weight_kg": None, "bmi": None, "bmi_label": None,
    }
    try:
        rows = crud.get_health_metrics(db, models.HealthMetricType.gewicht, days=120)
        if rows:
            out["weight_kg"] = round(rows[-1].value, 1)
            if s.height_cm:
                m = s.height_cm / 100.0
                bmi = rows[-1].value / (m * m)
                out["bmi"] = round(bmi, 1)
                out["bmi_label"] = ("Untergewicht" if bmi < 18.5 else
                                    "Normalgewicht" if bmi < 25 else
                                    "Übergewicht" if bmi < 30 else "Adipositas")
    except Exception:  # noqa: BLE001
        pass
    return out


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


@meals_router.get("/profile")
def get_nutrition_profile(db: Session = Depends(get_db)):
    return _nutrition_profile_dict(db)


@meals_router.put("/profile")
def put_nutrition_profile(data: schemas.NutritionProfileIn, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    if data.nutrition_goal is not None:
        goal = data.nutrition_goal.strip().lower()
        s.nutrition_goal = goal if goal in _GOAL_HINT else "halten"
    if data.nutrition_prefs is not None:
        s.nutrition_prefs = data.nutrition_prefs.strip() or None
    if data.nutrition_kcal_target is not None:
        s.nutrition_kcal_target = max(0, data.nutrition_kcal_target) or None
    if data.height_cm is not None:
        s.height_cm = max(0, data.height_cm) or None
    db.commit()
    return _nutrition_profile_dict(db)


@meals_router.post("/recipes/suggest")
def suggest_recipes(data: schemas.MealSuggestIn, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    if not s.ollama_url or not s.ollama_model:
        raise HTTPException(400, "Kein Ollama-Modell eingerichtet (Einstellungen -> KI-Assistent).")
    n = max(1, min(data.count, 8))
    prof = _nutrition_profile_dict(db)
    user = f"Schlage {n} Gerichte vor.\n" + _GOAL_HINT.get(prof["nutrition_goal"], "")
    if prof["nutrition_prefs"]:
        user += f"\nVorlieben/Unvertraeglichkeiten: {prof['nutrition_prefs']}"
    if prof["nutrition_kcal_target"]:
        user += f"\nTageskalorienziel des Nutzers: ~{prof['nutrition_kcal_target']} kcal."
    if prof.get("bmi_label"):
        user += f"\nZur Einordnung: aktueller BMI ~{prof['bmi']} ({prof['bmi_label']})."
    if (data.prompt or "").strip():
        user += f"\nAusserdem beruecksichtigen: {data.prompt.strip()}"
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
        def _n(key):
            try:
                return int(round(float(r.get(key))))
            except (TypeError, ValueError):
                return None
        out.append({
            "name": str(r["name"]).strip(),
            "ingredients": "\n".join(ing) if isinstance(ing, list) else str(ing or ""),
            "instructions": str(r.get("instructions") or "").strip(),
            "servings": r.get("servings"),
            "tags": str(r.get("tags") or "").strip(),
            "kcal": _n("kcal"), "protein_g": _n("protein"),
            "carbs_g": _n("carbs"), "fat_g": _n("fat"),
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

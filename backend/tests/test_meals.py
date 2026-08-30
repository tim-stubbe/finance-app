"""Essensplanung: Rezepte, Wochenplan, Einkaufsliste (routers/meals.py,
crud_meals.py). Ollama ist bei den KI-Vorschlaegen gemockt."""

import json

from app import ollama_client


def test_recipe_crud(auth_client):
    r = auth_client.post("/api/meals/recipes", json={
        "name": "Nudeln mit Pesto",
        "ingredients": "500 g Nudeln\n1 Glas Pesto\n50 g Parmesan",
        "instructions": "Kochen, mischen.",
        "servings": 4, "tags": "schnell, vegetarisch",
    })
    assert r.status_code == 200
    rid = r.json()["id"]
    assert any(x["name"] == "Nudeln mit Pesto" for x in auth_client.get("/api/meals/recipes").json())
    assert auth_client.delete(f"/api/meals/recipes/{rid}").status_code == 200
    assert auth_client.get("/api/meals/recipes").json() == []


def test_plan_and_shopping_list(auth_client):
    r1 = auth_client.post("/api/meals/recipes", json={
        "name": "R1", "ingredients": "500 g Nudeln\n1 Glas Pesto", "servings": 2}).json()
    r2 = auth_client.post("/api/meals/recipes", json={
        "name": "R2", "ingredients": "200 g Nudeln\n2 Tomaten", "servings": 2}).json()

    auth_client.put("/api/meals/plan", json={"date": "2026-09-01", "meal": "mittag", "recipe_id": r1["id"]})
    auth_client.put("/api/meals/plan", json={"date": "2026-09-02", "meal": "abend", "recipe_id": r2["id"]})

    plan = auth_client.get("/api/meals/plan?date_from=2026-09-01&date_to=2026-09-07").json()
    assert {p["recipe_name"] for p in plan} == {"R1", "R2"}

    items = auth_client.get("/api/meals/shopping-list?date_from=2026-09-01&date_to=2026-09-07").json()
    by = {i["item"].lower(): i for i in items}
    assert "nudeln" in by                       # aus beiden Rezepten gebuendelt
    assert "500 g" in by["nudeln"]["amounts"] and "200 g" in by["nudeln"]["amounts"]
    assert "tomaten" in by
    assert any("pesto" in k for k in by)

    # auf die Wunschliste schieben
    res = auth_client.post("/api/meals/shopping-list/push",
                           json={"date_from": "2026-09-01", "date_to": "2026-09-07", "target": "wishlist"}).json()
    assert res["added"] == len(items)
    names = [w["name"] for w in auth_client.get("/api/wishlist").json()]
    assert any("Nudeln" in n for n in names)

    # Plan-Eintrag entfernen
    assert auth_client.request("DELETE", "/api/meals/plan?day=2026-09-01&meal=mittag").status_code == 200


def test_ai_recipe_suggest(auth_client, monkeypatch):
    from app import auth
    from app.database import SessionLocal
    db = SessionLocal()
    s = auth.get_or_create_settings(db)
    s.ollama_url = "http://o"; s.ollama_model = "m"
    db.commit(); db.close()
    monkeypatch.setattr(ollama_client, "chat", lambda *a, **k: json.dumps({"recipes": [
        {"name": "Ofengemüse", "ingredients": ["1 kg Kartoffeln", "2 Paprika"],
         "instructions": "Backen.", "servings": 2, "tags": "vegetarisch"}]}))
    out = auth_client.post("/api/meals/recipes/suggest", json={"count": 3}).json()
    assert out[0]["name"] == "Ofengemüse"
    assert "Kartoffeln" in out[0]["ingredients"]


def test_ai_suggest_without_ollama_is_400(auth_client):
    assert auth_client.post("/api/meals/recipes/suggest", json={"count": 2}).status_code == 400


def test_nutrition_profile_roundtrip_and_bmi(auth_client):
    from app import auth, models
    from app.database import SessionLocal
    r = auth_client.put("/api/meals/profile", json={
        "nutrition_goal": "zunehmen", "nutrition_prefs": "vegetarisch, keine Nüsse",
        "height_cm": 180,
    })
    assert r.status_code == 200
    p = r.json()
    assert p["nutrition_goal"] == "zunehmen"
    assert p["height_cm"] == 180
    # Gewicht als Health-Metrik -> BMI-Einordnung
    db = SessionLocal()
    try:
        db.add(models.HealthMetric(metric_type=models.HealthMetricType.gewicht,
                                   date=__import__("datetime").date.today(), value=52.0))
        db.commit()
    finally:
        db.close()
    p = auth_client.get("/api/meals/profile").json()
    assert p["weight_kg"] == 52.0
    assert p["bmi"] and p["bmi"] < 18.5 and p["bmi_label"] == "Untergewicht"
    # ungültiges Ziel -> fällt auf "halten" zurück
    assert auth_client.put("/api/meals/profile", json={"nutrition_goal": "quatsch"}).json()["nutrition_goal"] == "halten"


def test_recipe_keeps_nutrition_values(auth_client):
    rid = auth_client.post("/api/meals/recipes", json={
        "name": "Erdnuss-Curry", "servings": 2,
        "kcal": 780, "protein_g": 34, "carbs_g": 70, "fat_g": 38,
    }).json()["id"]
    got = next(x for x in auth_client.get("/api/meals/recipes").json() if x["id"] == rid)
    assert got["kcal"] == 780 and got["protein_g"] == 34 and got["fat_g"] == 38


def test_ai_suggest_passes_nutrition_and_goal(auth_client, monkeypatch):
    from app import auth
    from app.database import SessionLocal
    db = SessionLocal()
    s = auth.get_or_create_settings(db)
    s.ollama_url = "http://o"; s.ollama_model = "m"; s.nutrition_goal = "zunehmen"
    db.commit(); db.close()
    seen = {}
    def fake_chat(url, model, messages, **k):
        seen["user"] = messages[-1]["content"]
        return json.dumps({"recipes": [{"name": "Sahne-Pasta", "ingredients": ["Sahne"],
            "instructions": "x", "servings": 2, "kcal": 820, "protein": 25, "carbs": 80, "fat": 40}]})
    monkeypatch.setattr(ollama_client, "chat", fake_chat)
    out = auth_client.post("/api/meals/recipes/suggest", json={"count": 1}).json()
    assert "ZUNEHMEN" in seen["user"]
    assert out[0]["kcal"] == 820 and out[0]["fat_g"] == 40

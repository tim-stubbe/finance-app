"""Steuer-Spar-Tipps (app/tax_advice.py) + /api/tax/tips /api/tax/ask.

Prüft die regelbasierten Heuristiken (kein Ollama nötig) und die
Länderweiche DE/CH.
"""
from datetime import date

from app import auth, models
from app.database import SessionLocal


def _set_country(country):
    db = SessionLocal()
    try:
        s = auth.get_or_create_settings(db)
        s.residence_country = country
        db.commit()
    finally:
        db.close()


def _loss_holding(auth_client):
    r = auth_client.post("/api/holdings", json={
        "asset_type": "aktie", "name": "Minusaktie", "symbol": "LOSS",
        "quantity": 10, "purchase_price": 100.0, "purchase_date": "2026-01-02",
    })
    hid = r.json()["id"]
    # aktuellen Kurs unter Einstand ziehen -> unrealisierter Verlust
    db = SessionLocal()
    try:
        h = db.query(models.Holding).get(hid)
        h.current_price = 40.0
        db.commit()
    finally:
        db.close()
    return hid


def test_tips_endpoint_shape_and_disclaimer(auth_client):
    _set_country("DE")
    r = auth_client.get("/api/tax/tips")
    assert r.status_code == 200
    body = r.json()
    assert body["country"] == "DE"
    assert "facts" in body and "tips" in body
    assert all({"id", "area", "severity", "title", "detail"} <= set(t) for t in body["tips"])
    # Homeoffice-Tipp ist immer dabei (DE)
    assert any(t["id"] == "homeoffice" for t in body["tips"])


def test_de_tax_loss_harvesting_tip_when_realized_gain(auth_client):
    _set_country("DE")
    _loss_holding(auth_client)
    # realisierten Gewinn erzeugen: kaufen billig, teurer verkaufen
    r = auth_client.post("/api/holdings", json={
        "asset_type": "aktie", "name": "Plusaktie", "symbol": "WIN",
        "quantity": 10, "purchase_price": 50.0, "purchase_date": "2026-01-02",
    })
    wid = r.json()["id"]
    auth_client.post(f"/api/holdings/{wid}/lots", json={
        "type": "verkauf", "quantity": 10, "price_per_unit": 90.0,
        "date": f"{date.today().year}-03-01",
    })
    tips = auth_client.get("/api/tax/tips").json()["tips"]
    assert any(t["id"] == "tax-loss-harvest" for t in tips)


def test_ch_switch_changes_tips(auth_client):
    _set_country("CH")
    body = auth_client.get("/api/tax/tips").json()
    assert body["country"] == "CH"
    ids = {t["id"] for t in body["tips"]}
    assert "ch-saeule-3a" in ids
    assert "ch-kapitalgewinne" in ids
    assert "homeoffice" not in ids  # DE-only


def test_ask_without_ollama_is_soft_error(auth_client):
    _set_country("DE")
    r = auth_client.post("/api/tax/ask", json={"question": "Wie spare ich Steuern?"})
    assert r.status_code == 200
    assert r.json()["ok"] is False

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


def test_telegram_steuer_command(auth_client, monkeypatch):
    from app import telegram_bot
    _set_country("DE")
    sent = []
    monkeypatch.setattr(telegram_bot, "_send", lambda tok, cid, msg: sent.append(msg))
    db = SessionLocal()
    try:
        s = auth.get_or_create_settings(db)
        assert telegram_bot._handle_steuer_command(db, s, "t", "c", "/steuer")
        assert not telegram_bot._handle_steuer_command(db, s, "t", "c", "/anderes")
    finally:
        db.close()
    assert sent and "Steuern sparen" in sent[0] and "keine Steuerberatung" in sent[0]


def test_tax_profile_personalizes_and_church_tax(auth_client):
    _set_country("DE")
    auth_client.put("/api/tax/profile", json={"church_tax_rate": 0.09, "marginal_tax_rate": 0.42})
    p = auth_client.get("/api/tax/profile").json()
    assert p["church_tax_rate"] == 0.09 and p["marginal_tax_rate"] == 0.42
    facts = auth_client.get("/api/tax/tips").json()["facts"]
    assert facts["kap_eff"] > 0.2637  # Abgeltung+Soli+Kirche > 26,375 %
    tips = auth_client.get("/api/tax/tips").json()["tips"]
    ho = next(t for t in tips if t["id"] == "homeoffice")
    assert "42 %" in ho["detail"]  # Grenzsteuersatz-Hinweis eingespielt


def test_tax_tip_status_dismiss_and_reset(auth_client):
    _set_country("DE")
    year = 2026
    r = auth_client.post(f"/api/tax/tips/homeoffice/status", json={"year": year, "status": "not_relevant"})
    assert r.json()["ok"] is True
    data = auth_client.get(f"/api/tax/tips?year={year}").json()
    assert all(t["id"] != "homeoffice" for t in data["tips"])
    assert any(t["id"] == "homeoffice" and t["status"] == "not_relevant" for t in data["dismissed"])
    auth_client.post(f"/api/tax/tips/homeoffice/status", json={"year": year, "status": "open"})
    assert any(t["id"] == "homeoffice" for t in auth_client.get(f"/api/tax/tips?year={year}").json()["tips"])


def test_project_investment_endpoint(auth_client):
    r = auth_client.post("/api/tax/project", json={
        "start": 10000, "monthly": 300, "annual_return_pct": 7, "years": 50,
        "church_tax_rate": 0.09,
    })
    assert r.status_code == 200
    b = r.json()
    assert b["eingezahlt"] == 190000
    # Brutto > netto nach laufender Steuer > netto nach Verkauf
    assert b["brutto"] > b["mit_kirchensteuer"]["netto_laufend"] > b["mit_kirchensteuer"]["netto_nach_verkauf"]
    # ohne Kirchensteuer bleibt mehr übrig
    assert b["ohne_kirchensteuer"]["netto_nach_verkauf"] > b["mit_kirchensteuer"]["netto_nach_verkauf"]
    assert b["kirchensteuer_kostet"] < 0  # mit Kirche weniger Endvermögen

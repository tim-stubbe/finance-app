"""Tests für Investments: Positions-Zusammenführung bei gleichem Symbol,
vor allem die Durchschnittskostenmethode (crud_investments.
recompute_holding_from_lots) - reine Finanzmathematik, ein Vorzeichen- oder
Rundungsfehler dort würde falsche Einstandspreise/Gewinne in der ganzen
Investments-Ansicht erzeugen, ohne dass es sofort auffällt."""


def _create_holding(client, quantity=10, purchase_price=100.0, symbol="TEST"):
    r = client.post("/api/holdings", json={
        "asset_type": "aktie", "name": "Testaktie", "symbol": symbol,
        "quantity": quantity, "purchase_price": purchase_price,
        "purchase_date": "2026-01-01",
    })
    assert r.status_code == 200
    return r.json()


def test_create_holding_basic(auth_client):
    h = _create_holding(auth_client, quantity=10, purchase_price=100.0)
    assert h["quantity"] == 10
    assert h["purchase_price"] == 100.0
    assert h["purchase_value"] == 1000.0


def test_second_purchase_same_symbol_merges_into_existing_position(auth_client):
    """Kein zweiter Kauf derselben Aktie darf eine zweite, getrennte Zeile
    erzeugen (siehe routers/investments.py:create_holding) - stattdessen
    Durchschnittskostenmethode über beide Käufe."""
    h1 = _create_holding(auth_client, quantity=10, purchase_price=100.0, symbol="AAPL")
    h2 = _create_holding(auth_client, quantity=10, purchase_price=200.0, symbol="AAPL")
    assert h2["id"] == h1["id"]  # dieselbe Position, kein Duplikat

    r = auth_client.get("/api/holdings")
    holdings = r.json()
    assert len(holdings) == 1
    # (10*100 + 10*200) / 20 = 150 Durchschnittskosten
    assert holdings[0]["quantity"] == 20
    assert holdings[0]["purchase_price"] == 150.0


def test_partial_sell_reduces_quantity_keeps_average_cost(auth_client):
    """Ein Teilverkauf reduziert die Stückzahl zum AKTUELLEN Durchschnitts-
    preis, der Einstandspreis pro verbleibendem Stück bleibt unverändert -
    nur der Gesamt-Einstand sinkt proportional."""
    h = _create_holding(auth_client, quantity=20, purchase_price=100.0, symbol="MSFT")
    holding_id = h["id"]

    r = auth_client.post(f"/api/holdings/{holding_id}/lots", json={
        "date": "2026-06-01", "type": "verkauf", "quantity": 8, "price_per_unit": 150.0,
    })
    assert r.status_code == 200

    r = auth_client.get("/api/holdings")
    holding = next(x for x in r.json() if x["id"] == holding_id)
    assert holding["quantity"] == 12
    # Durchschnittskosten bleiben 100 (der Verkaufspreis 150 fliesst NICHT
    # in den Einstandspreis ein, das waere ein grundlegender Rechenfehler).
    assert holding["purchase_price"] == 100.0


def test_sell_more_than_held_clamped_to_zero(auth_client):
    """Ein Verkauf über den gesamten Bestand hinaus darf die Stückzahl nicht
    negativ werden lassen (siehe recompute_holding_from_lots: sell_qty =
    min(lot.quantity, qty))."""
    h = _create_holding(auth_client, quantity=5, purchase_price=50.0, symbol="TSLA")
    holding_id = h["id"]

    auth_client.post(f"/api/holdings/{holding_id}/lots", json={
        "date": "2026-06-01", "type": "verkauf", "quantity": 100, "price_per_unit": 60.0,
    })

    r = auth_client.get("/api/holdings")
    holding = next(x for x in r.json() if x["id"] == holding_id)
    assert holding["quantity"] == 0
    assert holding["purchase_price"] == 0.0


def test_delete_holding_removes_lots(auth_client):
    h = _create_holding(auth_client)
    holding_id = h["id"]
    r = auth_client.delete(f"/api/holdings/{holding_id}")
    assert r.status_code == 200
    assert auth_client.get("/api/holdings").json() == []

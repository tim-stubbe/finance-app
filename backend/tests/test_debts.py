"""Tests für Schulden/Kredite: Restschuld-Berechnung aus dem Zahlungsverlauf
(debts.payment_breakdown/current_balance) - Sondertilgungen (is_extra_
repayment) gehen bewusst vollständig in die Tilgung (kein Zins-/Gebühren-
anteil), das macht die Rechnung hier deterministisch testbar."""


def _create_debt(client, original_amount=10000.0):
    r = client.post("/api/debts", json={
        "name": "Testkredit", "kind": "annuitaeten", "original_amount": original_amount,
        "interest_rate_percent": 0.0,
    })
    assert r.status_code == 200
    return r.json()["id"]


def test_create_debt_initial_balance_equals_original_amount(auth_client):
    debt_id = _create_debt(auth_client, original_amount=10000.0)
    r = auth_client.get(f"/api/debts/{debt_id}")
    assert r.json()["current_balance"] == 10000.0
    assert r.json()["status"] == "active"


def test_extra_repayment_reduces_balance_fully(auth_client):
    """Sondertilgung: kein Zins-/Gebührenanteil, voller Betrag mindert die
    Restschuld 1:1."""
    debt_id = _create_debt(auth_client, original_amount=10000.0)
    r = auth_client.post(f"/api/debts/{debt_id}/payments", json={
        "date": "2026-06-01", "total_amount": 2000.0, "is_extra_repayment": True,
    })
    assert r.status_code == 200
    assert r.json()["balance_after"] == 8000.0

    r = auth_client.get(f"/api/debts/{debt_id}")
    assert r.json()["current_balance"] == 8000.0


def test_debt_paid_off_when_balance_reaches_zero(auth_client):
    debt_id = _create_debt(auth_client, original_amount=1000.0)
    auth_client.post(f"/api/debts/{debt_id}/payments", json={
        "date": "2026-06-01", "total_amount": 1000.0, "is_extra_repayment": True,
    })
    r = auth_client.get(f"/api/debts/{debt_id}")
    assert r.json()["current_balance"] == 0.0
    assert r.json()["status"] == "paid_off"


def test_delete_payment_reverts_balance(auth_client):
    debt_id = _create_debt(auth_client, original_amount=10000.0)
    r = auth_client.post(f"/api/debts/{debt_id}/payments", json={
        "date": "2026-06-01", "total_amount": 2000.0, "is_extra_repayment": True,
    })
    payment_id = r.json()["id"]

    r = auth_client.delete(f"/api/debts/{debt_id}/payments/{payment_id}")
    assert r.status_code == 200

    r = auth_client.get(f"/api/debts/{debt_id}")
    assert r.json()["current_balance"] == 10000.0


def test_debt_summary_aggregates_across_debts(auth_client):
    _create_debt(auth_client, original_amount=5000.0)
    _create_debt(auth_client, original_amount=3000.0)
    r = auth_client.get("/api/debts/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["total_balance"] == 8000.0
    assert body["active_count"] == 2

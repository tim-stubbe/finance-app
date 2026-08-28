"""Tests für den finanziellen Kernpfad: Konten, Buchungen, Kontostand-
Berechnung. Der Bereich (Space) selbst muss nicht manuell angelegt werden -
siehe conftest._fresh_db, das denselben Default-"Privat"-Bereich wie die
echte Erstinstallation bereithält, auth.get_active_space_id wählt ihn
automatisch."""


def _create_account(client, initial_balance=1000.0):
    r = client.post("/api/accounts", json={
        "name": "Test-Konto", "type": "girokonto", "initial_balance": initial_balance,
    })
    assert r.status_code == 200
    return r.json()["id"]


def test_create_account_shows_initial_balance(auth_client):
    account_id = _create_account(auth_client, initial_balance=500.0)
    r = auth_client.get("/api/accounts")
    assert r.status_code == 200
    accounts = r.json()
    assert len(accounts) == 1
    assert accounts[0]["id"] == account_id
    assert accounts[0]["current_balance"] == 500.0


def test_create_transaction_updates_balance(auth_client):
    account_id = _create_account(auth_client, initial_balance=1000.0)
    r = auth_client.post("/api/transactions", json={
        "date": "2026-08-28", "amount": -50.5, "description": "Testkauf",
        "account_id": account_id,
    })
    assert r.status_code == 200
    tx_id = r.json()["id"]

    r = auth_client.get("/api/accounts")
    assert r.json()[0]["current_balance"] == 949.5

    # Zweite Buchung - Salden muessen sich korrekt aufaddieren, nicht die
    # vorherige ueberschreiben.
    auth_client.post("/api/transactions", json={
        "date": "2026-08-28", "amount": 200.0, "description": "Gehalt",
        "account_id": account_id,
    })
    r = auth_client.get("/api/accounts")
    assert r.json()[0]["current_balance"] == 1149.5

    r = auth_client.get(f"/api/transactions/{tx_id}" if False else "/api/transactions")
    assert len(r.json()) == 2


def test_update_transaction_amount_recalculates_balance(auth_client):
    account_id = _create_account(auth_client, initial_balance=1000.0)
    r = auth_client.post("/api/transactions", json={
        "date": "2026-08-28", "amount": -100.0, "description": "Testkauf",
        "account_id": account_id,
    })
    tx_id = r.json()["id"]

    r = auth_client.put(f"/api/transactions/{tx_id}", json={"amount": -300.0})
    assert r.status_code == 200

    r = auth_client.get("/api/accounts")
    assert r.json()[0]["current_balance"] == 700.0


def test_delete_transaction_reverts_balance(auth_client):
    account_id = _create_account(auth_client, initial_balance=1000.0)
    r = auth_client.post("/api/transactions", json={
        "date": "2026-08-28", "amount": -250.0, "description": "Testkauf",
        "account_id": account_id,
    })
    tx_id = r.json()["id"]
    assert auth_client.get("/api/accounts").json()[0]["current_balance"] == 750.0

    r = auth_client.delete(f"/api/transactions/{tx_id}")
    assert r.status_code == 200
    assert auth_client.get("/api/accounts").json()[0]["current_balance"] == 1000.0
    assert auth_client.get("/api/transactions").json() == []


def test_transaction_on_foreign_account_id_rejected(auth_client):
    """Space-Isolation: eine Buchung auf einer nicht existenten (oder
    fremden) account_id darf nicht klaglos durchgehen."""
    r = auth_client.post("/api/transactions", json={
        "date": "2026-08-28", "amount": -10.0, "description": "x",
        "account_id": 999999,
    })
    assert r.status_code in (400, 404, 422)


def test_transactions_require_authentication(client):
    r = client.get("/api/transactions")
    assert r.status_code == 401


def test_bulk_categorize(auth_client):
    account_id = _create_account(auth_client)
    cat = auth_client.post("/api/categories", json={"name": "Lebensmittel", "type": "ausgabe"})
    assert cat.status_code == 200
    cat_id = cat.json()["id"]

    ids = []
    for i in range(3):
        r = auth_client.post("/api/transactions", json={
            "date": "2026-08-28", "amount": -10.0 - i, "description": f"Kauf {i}",
            "account_id": account_id,
        })
        ids.append(r.json()["id"])

    r = auth_client.post("/api/transactions/bulk-categorize", json={
        "transaction_ids": ids, "category_id": cat_id,
    })
    assert r.status_code == 200

    txs = auth_client.get("/api/transactions").json()
    assert all(t["category_id"] == cat_id for t in txs)

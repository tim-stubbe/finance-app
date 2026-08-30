"""Wiederkehrende Zahlungen: der Buchungsverlauf eines erkannten Abos
(GET /api/transactions/recurring/occurrences, crud.recurring_occurrences).
"""


def _account(client):
    return client.post("/api/accounts", json={
        "name": "Giro", "type": "girokonto", "initial_balance": 1000.0,
    }).json()["id"]


def test_recurring_occurrences_lists_all_bookings_of_the_group(auth_client):
    acc = _account(auth_client)
    # 4 monatliche Netflix-Buchungen (leicht schwankende Schreibweise) + eine
    # fremde Buchung, die nicht dazugehören darf.
    for d in ("2026-05-03", "2026-06-03", "2026-07-03", "2026-08-03"):
        auth_client.post("/api/transactions", json={
            "date": d, "amount": -12.99, "description": "NETFLIX.COM", "account_id": acc,
        })
    auth_client.post("/api/transactions", json={
        "date": "2026-07-10", "amount": -40.0, "description": "REWE", "account_id": acc,
    })

    rec = auth_client.get("/api/transactions/recurring").json()
    netflix = next(r for r in rec if "netflix" in (r["description_key"] or ""))

    r = auth_client.get(
        f"/api/transactions/recurring/occurrences?account_id={acc}"
        f"&description_key={netflix['description_key']}"
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 4
    assert all(abs(row["amount"] + 12.99) < 0.001 for row in rows)
    # neueste zuerst
    assert rows[0]["date"] >= rows[-1]["date"]
    assert not any("REWE" in (row["description"] or "") for row in rows)

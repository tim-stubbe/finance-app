from app import splitwise_client


def test_balances_separate_money_owed_to_and_by_user(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {"friends": [
                {"balance": [{"currency_code": "EUR", "amount": "800.00"}]},
                {"balance": [{"currency_code": "EUR", "amount": "-75.50"}]},
            ]}
    monkeypatch.setattr(splitwise_client.requests, "get", lambda *a, **k: Response())
    assert splitwise_client.balances("secret") == {
        "EUR": {"receivable": 800.0, "payable": 75.5}
    }

"""Read-only Splitwise balances for liquidity planning."""
from __future__ import annotations

import requests

BASE_URL = "https://secure.splitwise.com/api/v3.0"


def balances(api_key: str) -> dict[str, dict[str, float]]:
    response = requests.get(
        f"{BASE_URL}/get_friends",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        timeout=15,
    )
    response.raise_for_status()
    totals: dict[str, dict[str, float]] = {}
    for friend in response.json().get("friends", []):
        for balance in friend.get("balance") or []:
            currency = (balance.get("currency_code") or "EUR").upper()
            amount = float(balance.get("amount") or 0)
            row = totals.setdefault(currency, {"receivable": 0.0, "payable": 0.0})
            if amount > 0:
                row["receivable"] += amount
            elif amount < 0:
                row["payable"] += abs(amount)
    return {currency: {key: round(value, 2) for key, value in values.items()}
            for currency, values in totals.items()}

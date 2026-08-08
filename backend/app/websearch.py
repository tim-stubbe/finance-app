"""Brave Search API Client - gibt der Assistant-Chat-KI Zugriff auf aktuelle
Informationen (Nachrichten, Rechtslage, Zinssätze, ...), die im lokalen Ollama-
Modell nicht stecken können. Braucht einen eigenen, vom Nutzer besorgten API-Key
(Ollama selbst kann nicht googeln)."""

import requests

BASE_URL = "https://api.search.brave.com/res/v1/web/search"
MAX_RESULTS = 5


def search(api_key: str, query: str) -> list[dict]:
    resp = requests.get(
        BASE_URL,
        params={"q": query, "count": MAX_RESULTS},
        headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    for item in (data.get("web", {}).get("results") or [])[:MAX_RESULTS]:
        results.append({
            "title": item.get("title"),
            "url": item.get("url"),
            "snippet": item.get("description"),
        })
    return results


def format_for_prompt(query: str, results: list[dict]) -> str:
    if not results:
        return f"Suchergebnisse für „{query}“: keine Treffer."
    lines = [f"Suchergebnisse für „{query}“:"]
    for r in results:
        lines.append(f"- {r['title']}: {r['snippet']} ({r['url']})")
    return "\n".join(lines)

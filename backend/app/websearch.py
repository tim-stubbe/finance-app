"""Web-Suche für die Assistant-Chat-KI - gibt Zugriff auf aktuelle Informationen
(Nachrichten, Rechtslage, Zinssätze, ...), die im lokalen Ollama-Modell nicht
stecken können (Ollama selbst kann nicht googeln). Zwei austauschbare Anbieter:

- Brave Search API: bezahlt/kostenlos-limitiert, braucht einen vom Nutzer
  besorgten API-Key, dafür zuverlässige Trefferqualität (kein Scraping).
- SearXNG (selbst gehostet, z.B. auf dem eigenen TrueNAS): kostenlos, kein
  Key nötig, dafür je nach Instanz/Engines etwas wackeligere Treffer, weil
  SearXNG selbst nur ein Meta-Suchmaschinen-Scraper ist. Braucht `format=json`
  in der SearXNG-`settings.yml` (dort standardmäßig deaktiviert).

Beide liefern dieselbe Ergebnisform (title/url/snippet), main.py entscheidet
anhand von Settings.websearch_provider, welche Funktion aufgerufen wird."""

import requests

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
MAX_RESULTS = 5


def search_brave(api_key: str, query: str) -> list[dict]:
    resp = requests.get(
        BRAVE_URL,
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


def search_searxng(base_url: str, query: str) -> list[dict]:
    resp = requests.get(
        base_url.rstrip("/") + "/search",
        params={"q": query, "format": "json"},
        headers={"Accept": "application/json"},
        timeout=15,
    )
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError:
        # SearXNG antwortet mit HTML statt JSON, wenn `format=json` in der
        # Instanz-Konfiguration nicht freigeschaltet ist - ein generischer
        # requests-Fehler ("Expecting value...") wäre hier wenig hilfreich.
        raise ValueError(
            "SearXNG hat kein JSON geliefert - in der settings.yml der Instanz "
            "muss 'json' unter search.formats eingetragen sein."
        )
    results = []
    for item in (data.get("results") or [])[:MAX_RESULTS]:
        results.append({
            "title": item.get("title"),
            "url": item.get("url"),
            "snippet": item.get("content"),
        })
    return results


def format_for_prompt(query: str, results: list[dict]) -> str:
    if not results:
        return f"Suchergebnisse für „{query}“: keine Treffer."
    lines = [f"Suchergebnisse für „{query}“:"]
    for r in results:
        lines.append(f"- {r['title']}: {r['snippet']} ({r['url']})")
    return "\n".join(lines)

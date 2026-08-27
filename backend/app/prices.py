import time
from datetime import datetime, timezone

import requests

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_QUOTESUMMARY_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
COINGECKO_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_HISTORY_URL = "https://api.coingecko.com/api/v3/coins/{id}/market_chart"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; finance-app/1.0)"}

# Range-Auswahl in der UI -> (Yahoo-range, Yahoo-interval, CoinGecko-days, Tage zum Zurückschneiden oder None)
RANGE_MAP = {
    "1d": ("1d", "5m", "1", None),
    "2w": ("1mo", "1d", "14", 14),
    "1m": ("1mo", "1d", "30", None),
    "1y": ("1y", "1d", "365", None),
    "5y": ("5y", "1d", "1825", None),
    "max": ("max", "1d", "max", None),
}

# Ranges, die sich häufig ändern und deshalb nie aus dem Tages-Cache bedient werden.
LIVE_RANGES = {"1d", "2w"}

# quoteSummary verlangt seit einiger Zeit einen gültigen "Crumb" (CSRF-Token) samt
# Session-Cookie - ohne das kommt nur noch ein 401 "Invalid Crumb" zurück.
_yahoo_session = requests.Session()
_yahoo_session.headers.update(HEADERS)
_yahoo_crumb: str | None = None


def _get_yahoo_crumb(force_refresh: bool = False) -> str:
    global _yahoo_crumb
    if _yahoo_crumb and not force_refresh:
        return _yahoo_crumb
    _yahoo_session.get("https://fc.yahoo.com", timeout=10)
    resp = _yahoo_session.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=10)
    resp.raise_for_status()
    _yahoo_crumb = resp.text.strip()
    return _yahoo_crumb


def fetch_stock_quote(symbol: str) -> tuple[float, str]:
    """Gibt (Kurs, Währung) für einen Yahoo-Finance-Ticker zurück."""
    resp = requests.get(YAHOO_CHART_URL.format(symbol=symbol), headers=HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    result = (data.get("chart") or {}).get("result")
    if not result:
        raise ValueError(f"Kein Kurs gefunden für Symbol '{symbol}'")
    meta = result[0]["meta"]
    price = meta.get("regularMarketPrice")
    currency = meta.get("currency", "EUR")
    if price is None:
        raise ValueError(f"Kein aktueller Kurs verfügbar für '{symbol}'")
    return float(price), currency


def fetch_fx_rate(from_ccy: str, to_ccy: str = "EUR") -> float:
    if from_ccy == to_ccy:
        return 1.0
    rate, _ = fetch_stock_quote(f"{from_ccy}{to_ccy}=X")
    return rate


# Reiner In-Memory-Cache (kein DB-Roundtrip nötig) - der Umschalter im Frontend
# ruft das potenziell oft ab, ein Wechselkurs muss aber nicht sekundenaktuell sein.
_fx_cache: dict[tuple[str, str], tuple[float, float]] = {}
FX_CACHE_TTL_SECONDS = 3600


def get_cached_fx_rate(from_ccy: str, to_ccy: str = "EUR") -> float:
    key = (from_ccy, to_ccy)
    cached = _fx_cache.get(key)
    now = time.time()
    if cached and now - cached[1] < FX_CACHE_TTL_SECONDS:
        return cached[0]
    rate = fetch_fx_rate(from_ccy, to_ccy)
    _fx_cache[key] = (rate, now)
    return rate


def fetch_crypto_price_eur(coingecko_id: str) -> float:
    resp = requests.get(
        COINGECKO_PRICE_URL,
        params={"ids": coingecko_id, "vs_currencies": "eur"},
        headers=HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if coingecko_id not in data or "eur" not in data[coingecko_id]:
        raise ValueError(f"Kein Kurs gefunden für Krypto-ID '{coingecko_id}' (CoinGecko-ID prüfen, z.B. 'bitcoin')")
    return float(data[coingecko_id]["eur"])


def fetch_crypto_prices_eur(coingecko_ids: list[str]) -> dict[str, float]:
    """Holt Kurse für MEHRERE Kryptos in einem einzigen Aufruf statt einem pro
    Position - CoinGeckos anonymes Free-Tier limitiert sehr knapp, mehrere
    Positionen kurz hintereinander einzeln abzufragen (z.B. beim Bitvavo-Sync)
    hat live zuverlässig 429 Too Many Requests ausgelöst, obwohl /simple/price
    beliebig viele kommagetrennte IDs auf einmal unterstützt."""
    if not coingecko_ids:
        return {}
    resp = requests.get(
        COINGECKO_PRICE_URL,
        params={"ids": ",".join(sorted(set(coingecko_ids))), "vs_currencies": "eur"},
        headers=HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return {cid: float(info["eur"]) for cid, info in data.items() if "eur" in info}


def fetch_price_eur(asset_type: str, symbol: str) -> float:
    """Liefert den aktuellen Kurs in EUR pro Einheit, unabhängig von der Ursprungswährung."""
    if asset_type == "krypto":
        return round(fetch_crypto_price_eur(symbol), 6)
    price, currency = fetch_stock_quote(symbol)
    if currency and currency != "EUR":
        price *= fetch_fx_rate(currency, "EUR")
    return round(price, 4)


def fetch_stock_history(symbol: str, range_key: str) -> list[tuple[str, float]]:
    """Schlusskurse als (Datums-/Zeitlabel, Kurs in EUR)-Liste. Bei intraday-Intervallen
    (range 1d) enthält das Label zusätzlich die Uhrzeit, sonst nur das Datum."""
    yahoo_range, interval, _, trim_days = RANGE_MAP.get(range_key, RANGE_MAP["1y"])
    resp = requests.get(
        YAHOO_CHART_URL.format(symbol=symbol),
        params={"range": yahoo_range, "interval": interval},
        headers=HEADERS, timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    result = (data.get("chart") or {}).get("result")
    if not result:
        raise ValueError(f"Keine Kurshistorie gefunden für Symbol '{symbol}'")
    timestamps = result[0].get("timestamp") or []
    closes = (((result[0].get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
    currency = result[0]["meta"].get("currency", "EUR")
    fx = fetch_fx_rate(currency, "EUR") if currency and currency != "EUR" else 1.0
    cutoff_ts = time.time() - trim_days * 86400 if trim_days else None
    intraday = interval not in ("1d", "1wk", "1mo")
    points = []
    for ts, close in zip(timestamps, closes):
        if close is None or (cutoff_ts and ts < cutoff_ts):
            continue
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        label = dt.strftime("%Y-%m-%d %H:%M") if intraday else dt.date().isoformat()
        points.append((label, round(close * fx, 4)))
    return points


def fetch_crypto_history(coingecko_id: str, range_key: str) -> list[tuple[str, float]]:
    """Kurse (Datums-/Zeitlabel, Kurs in EUR) über CoinGecko.

    CoinGeckos kostenlose/anonyme API liefert seit einer Richtlinienänderung
    nur noch ein rollierendes Jahr Historie ohne bezahlten API-Key - live
    beobachtet: 5J/Alles (days=1825/max aus RANGE_MAP) werden zuverlässig mit
    "401 Unauthorized" abgelehnt, nicht nur gedrosselt. Deshalb hier auf
    maximal 365 Tage gedeckelt statt den rohen RANGE_MAP-Wert durchzureichen
    - liefert für 5J/Alles wenigstens das letzte Jahr an echten Daten statt
    eines kompletten Fehlschlags (der Portfolio-Chart hat diese Positionen
    sonst für JEDE Range komplett ausgeblendet, siehe portfolio_history)."""
    _, _, days, _ = RANGE_MAP.get(range_key, RANGE_MAP["1y"])
    if days not in ("1", "14", "30"):
        days = "365"
    resp = requests.get(
        COINGECKO_HISTORY_URL.format(id=coingecko_id),
        params={"vs_currency": "eur", "days": days},
        headers=HEADERS, timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    prices_raw = data.get("prices") or []
    if not prices_raw:
        raise ValueError(f"Keine Kurshistorie gefunden für Krypto-ID '{coingecko_id}'")
    intraday = range_key == "1d"
    points = []
    seen = set()
    for ts_ms, price in prices_raw:
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        label = dt.strftime("%Y-%m-%d %H:%M") if intraday else dt.date().isoformat()
        if label in seen:
            continue
        seen.add(label)
        points.append((label, round(price, 6)))
    return points


def fetch_history(asset_type: str, symbol: str, range_key: str) -> list[tuple[str, float]]:
    if asset_type == "krypto":
        return fetch_crypto_history(symbol, range_key)
    return fetch_stock_history(symbol, range_key)


def fetch_dividends(symbol: str) -> list[tuple[str, float]]:
    """Historische Dividendenzahlungen als (ISO-Datum, Betrag pro Aktie in EUR)-Liste,
    über die letzten 10 Jahre. Leere Liste, wenn keine Dividenden gefunden werden."""
    resp = requests.get(
        YAHOO_CHART_URL.format(symbol=symbol),
        params={"range": "10y", "interval": "1d", "events": "div"},
        headers=HEADERS, timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    result = (data.get("chart") or {}).get("result")
    if not result:
        return []
    currency = result[0]["meta"].get("currency", "EUR")
    fx = fetch_fx_rate(currency, "EUR") if currency and currency != "EUR" else 1.0
    dividends = ((result[0].get("events") or {}).get("dividends")) or {}
    points = []
    for entry in dividends.values():
        day = datetime.fromtimestamp(entry["date"], tz=timezone.utc).date().isoformat()
        amount = float(entry.get("amount", 0.0)) * fx
        points.append((day, round(amount, 6)))
    points.sort(key=lambda p: p[0])
    return points


def fetch_profile(symbol: str) -> dict:
    """Best-effort Sektor/Land/Währung-Abfrage für Aktien/ETFs über Yahoo Finance in
    einem Request. Fehlende Felder bleiben None (z.B. bei ETFs ohne assetProfile)."""
    empty = {"sector": None, "country": None, "currency": None}
    for attempt in range(2):
        try:
            crumb = _get_yahoo_crumb(force_refresh=(attempt > 0))
            resp = _yahoo_session.get(
                YAHOO_QUOTESUMMARY_URL.format(symbol=symbol),
                params={"modules": "assetProfile,price", "crumb": crumb},
                timeout=10,
            )
            if resp.status_code == 401 and attempt == 0:
                continue
            resp.raise_for_status()
            result = (((resp.json().get("quoteSummary") or {}).get("result")) or [{}])[0]
            profile = result.get("assetProfile") or {}
            price_module = result.get("price") or {}
            return {
                "sector": profile.get("sector") or None,
                "country": profile.get("country") or None,
                "currency": price_module.get("currency") or None,
            }
        except Exception:
            if attempt == 1:
                return empty
    return empty

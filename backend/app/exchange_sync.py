import hashlib
import hmac
import time
from datetime import date, datetime

import requests
from sqlalchemy.orm import Session

from . import models, crud, prices, schemas

BASE_URL = "https://api.bitvavo.com/v2"

# Bekannte Symbol -> CoinGecko-ID Zuordnung für die gängigsten Bitvavo-Assets.
# Bei unbekannten Symbolen wird der Kleinbuchstaben-Symbolname als Fallback versucht;
# schlägt der Kursabruf fehl, bleibt current_price leer und taucht in "failed" auf -
# die Position wird trotzdem mit der aktuellen Stückzahl angelegt/aktualisiert.
SYMBOL_TO_COINGECKO = {
    "BTC": "bitcoin", "ETH": "ethereum", "ADA": "cardano", "XRP": "ripple",
    "SOL": "solana", "DOGE": "dogecoin", "DOT": "polkadot", "MATIC": "matic-network",
    "LTC": "litecoin", "LINK": "chainlink", "AVAX": "avalanche-2", "TRX": "tron",
    "ATOM": "cosmos", "XLM": "stellar", "ALGO": "algorand", "EOS": "eos",
    "BCH": "bitcoin-cash", "ETC": "ethereum-classic", "UNI": "uniswap",
    "USDT": "tether", "USDC": "usd-coin", "DAI": "dai", "SHIB": "shiba-inu",
    "NEAR": "near", "APT": "aptos", "ARB": "arbitrum", "OP": "optimism",
    "BNB": "binancecoin",
}


def _signature(api_secret: str, timestamp: str, method: str, url_path: str) -> str:
    message = timestamp + method + url_path
    return hmac.new(api_secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def _headers(api_key: str, api_secret: str, method: str, url_path: str) -> dict:
    timestamp = str(int(time.time() * 1000))
    return {
        "Bitvavo-Access-Key": api_key,
        "Bitvavo-Access-Signature": _signature(api_secret, timestamp, method, url_path),
        "Bitvavo-Access-Timestamp": timestamp,
        "Bitvavo-Access-Window": "10000",
    }


def fetch_balance(api_key: str, api_secret: str) -> list[dict]:
    url_path = "/v2/balance"
    resp = requests.get(BASE_URL + "/balance", headers=_headers(api_key, api_secret, "GET", url_path), timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_trades(api_key: str, api_secret: str, market: str, limit: int = 1000) -> list[dict]:
    """Echte, mit Datum versehene Käufe/Verkäufe für einen Markt (z.B. "BTC-EUR") -
    im Gegensatz zu /balance (nur der aktuelle Gesamtbestand) lässt sich damit
    tatsächlich nachvollziehen, WANN und ZU WELCHEM Kurs gehandelt wurde. Live
    beobachtet: Bitvavo hat keinen öffentlichen Endpunkt für Staking-/Lending-
    Erträge (/staking, /lending -> 404) - die Differenz zwischen dem hier
    ermittelten Handelsbestand und dem tatsächlichen /balance-Bestand wird
    deshalb in sync() als Ertrag behandelt (siehe dort)."""
    url_path = f"/v2/trades?market={market}&limit={limit}"
    resp = requests.get(f"https://api.bitvavo.com{url_path}", headers=_headers(api_key, api_secret, "GET", url_path), timeout=15)
    resp.raise_for_status()
    return resp.json()


def sync(db: Session, conn: models.BitvavoConnection, api_key: str, api_secret: str, space_id: int) -> dict:
    try:
        balances = fetch_balance(api_key, api_secret)
    except Exception as e:
        # Session nach fehlgeschlagenem Flush freigeben, sonst wirft das commit() erneut.
        db.rollback()
        conn.last_sync_status = f"Fehler: {e}"
        conn.last_sync_at = datetime.utcnow()
        db.commit()
        return {"created": 0, "updated": 0, "failed": [], "error": str(e)}

    holdings_by_symbol = {
        h.symbol.lower(): h for h in crud.get_holdings(db, space_id) if h.asset_type == models.AssetType.krypto
    }

    # Erst alle relevanten Positionen einsammeln, dann die Kurse in EINEM
    # Sammelaufruf holen (statt einem CoinGecko-Aufruf je Position) - mehrere
    # Einzelaufrufe kurz hintereinander haben live zuverlässig 429 Too Many
    # Requests auf CoinGeckos strikt limitiertem Free-Tier ausgelöst.
    relevant = []
    for entry in balances:
        symbol = (entry.get("symbol") or "").upper()
        if not symbol or symbol == "EUR":
            continue
        qty = float(entry.get("available", 0) or 0) + float(entry.get("inOrder", 0) or 0)
        if qty <= 0:
            continue
        relevant.append((symbol, qty, SYMBOL_TO_COINGECKO.get(symbol, symbol.lower())))

    try:
        price_by_id = prices.fetch_crypto_prices_eur([cid for _, _, cid in relevant])
        price_fetch_error = None
    except Exception as e:
        price_by_id = {}
        price_fetch_error = str(e)

    created, updated, failed, trade_lots_added, reward_amount_total = 0, 0, [], 0, 0.0
    for symbol, qty, coingecko_id in relevant:
        current_price = price_by_id.get(coingecko_id)
        if current_price is None:
            reason = price_fetch_error or f"kein Kurs für '{coingecko_id}' im Sammelaufruf enthalten"
            failed.append(f"{symbol}: kein Kurs für '{coingecko_id}' gefunden ({reason}) - Symbol ggf. manuell in der Position korrigieren")

        existing = holdings_by_symbol.get(coingecko_id.lower())
        if existing:
            holding = existing
            updated += 1
        else:
            # Bewusst mit quantity=0 anlegen statt wie frueher direkt mit dem
            # aktuellen Bestand - die Stueckzahl soll ausschliesslich aus echten
            # Lots (siehe unten) hervorgehen, sonst entsteht wieder ein einzelner
            # "Kauf"-Lot fuer den kompletten Bestand (crud.create_holding legt bei
            # quantity>0 automatisch genau so einen Lot an).
            holding = crud.create_holding(db, schemas.HoldingCreate(
                asset_type=models.AssetType.krypto, name=symbol, symbol=coingecko_id,
                quantity=0, purchase_price=0.0,
            ), space_id)
            holdings_by_symbol[coingecko_id.lower()] = holding
            created += 1

        # Echte Käufe/Verkäufe aus der Handelshistorie übernehmen (korrekte Daten
        # und Kurse statt "heute" zu unterstellen) - bereits importierte Trades
        # anhand (Datum, Menge, Preis) nicht doppelt anlegen.
        try:
            trades = fetch_trades(api_key, api_secret, f"{symbol}-EUR")
        except Exception:
            trades = []
        known = {
            (l.date, round(l.quantity, 8), round(l.price_per_unit, 8))
            for l in holding.lots if l.type in (models.LotType.kauf, models.LotType.verkauf)
        }
        for t in trades:
            amount = float(t.get("amount") or 0)
            price = float(t.get("price") or 0)
            ts = t.get("timestamp")
            if amount <= 0 or not ts:
                continue
            trade_date = datetime.utcfromtimestamp(ts / 1000).date()
            key = (trade_date, round(amount, 8), round(price, 8))
            if key in known:
                continue
            lot_type = models.LotType.kauf if t.get("side") == "buy" else models.LotType.verkauf
            crud.create_lot(db, holding.id, space_id, schemas.HoldingLotCreate(
                date=trade_date, type=lot_type, quantity=amount, price_per_unit=price,
            ))
            trade_lots_added += 1
        db.refresh(holding)

        # Rest zwischen dem echten Bitvavo-Gesamtbestand und dem, was die
        # Handelshistorie erklärt, sind Staking-/Lending-Erträge (Bitvavo hat dafür
        # öffentlich keine eigene Historie, siehe fetch_trades-Docstring) - als
        # eigener Lot mit Einstandspreis 0 verbucht statt als "Kauf" mitgezählt.
        reward_amount = round(qty - holding.quantity, 8)
        if reward_amount > 1e-8:
            crud.create_lot(db, holding.id, space_id, schemas.HoldingLotCreate(
                date=date.today(), type=models.LotType.staking, quantity=reward_amount, price_per_unit=0.0,
            ))
            reward_amount_total += reward_amount
            db.refresh(holding)

        if current_price is not None:
            holding.current_price = current_price
            holding.price_updated_at = datetime.utcnow()

    conn.last_sync_at = datetime.utcnow()
    conn.last_sync_status = (
        f"OK: {created} neu, {updated} aktualisiert, {trade_lots_added} Trade(s) importiert"
        + (f", Staking/Lending-Ertrag verbucht" if reward_amount_total > 0 else "")
        + (f", {len(failed)} ohne Kurs" if failed else "")
    )
    db.commit()
    return {"created": created, "updated": updated, "failed": failed, "error": None}

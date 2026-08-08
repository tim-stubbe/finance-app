import hashlib
import hmac
import time
from datetime import datetime

import requests
from sqlalchemy.orm import Session

from . import models, crud, prices

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

    created, updated, failed = 0, 0, []
    for entry in balances:
        symbol = (entry.get("symbol") or "").upper()
        if not symbol or symbol == "EUR":
            continue
        qty = float(entry.get("available", 0) or 0) + float(entry.get("inOrder", 0) or 0)
        if qty <= 0:
            continue
        coingecko_id = SYMBOL_TO_COINGECKO.get(symbol, symbol.lower())

        current_price = None
        try:
            current_price = prices.fetch_crypto_price_eur(coingecko_id)
        except Exception as e:
            failed.append(f"{symbol}: kein Kurs für '{coingecko_id}' gefunden ({e}) - Symbol ggf. manuell in der Position korrigieren")

        existing = holdings_by_symbol.get(coingecko_id.lower())
        if existing:
            existing.quantity = qty
            if current_price is not None:
                existing.current_price = current_price
                existing.price_updated_at = datetime.utcnow()
            updated += 1
        else:
            db.add(models.Holding(
                space_id=space_id,
                asset_type=models.AssetType.krypto,
                name=symbol,
                symbol=coingecko_id,
                quantity=qty,
                purchase_price=current_price if current_price is not None else 0.0,
                current_price=current_price,
                price_updated_at=datetime.utcnow() if current_price is not None else None,
            ))
            created += 1

    conn.last_sync_at = datetime.utcnow()
    conn.last_sync_status = f"OK: {created} neu, {updated} aktualisiert" + (f", {len(failed)} ohne Kurs" if failed else "")
    db.commit()
    return {"created": created, "updated": updated, "failed": failed, "error": None}

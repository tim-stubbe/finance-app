"""eBay-Anbindung - Verkäufe als vollwertiges Konto einbinden, nicht als
separater Report daneben (Vision-Entscheidung des Nutzers).

Nutzt die eBay Sell-APIs (OAuth Authorization-Code-Grant, wie ein Nutzer die
App über den eBay-Consent-Screen freischaltet) statt eigener Web-Scrapes -
dasselbe "einbinden statt nachbauen"-Prinzip wie bei Immich und PayPal.

Endpunkte laut offizieller eBay-Dokumentation (developer.ebay.com):
- Consent: https://auth.ebay.com/oauth2/authorize
- Token-Tausch/Refresh: https://api.ebay.com/identity/v1/oauth2/token
- Verkäufe: https://api.ebay.com/sell/fulfillment/v1/order (Fulfillment API)

Scope `sell.fulfillment.readonly` reicht für reines Auslesen abgeschlossener
Bestellungen - keine Schreibrechte auf das eBay-Konto nötig oder angefragt.
"""

import base64
from datetime import datetime, timedelta

import requests
from sqlalchemy.orm import Session

from . import models, crud, bank_sync, auth

AUTH_URL = "https://auth.ebay.com/oauth2/authorize"
TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
ORDERS_URL = "https://api.ebay.com/sell/fulfillment/v1/order"
SCOPE = "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly"


def build_consent_url(app_id: str, ru_name: str, state: str) -> str:
    """Baut die Adresse, zu der der Nutzer weitergeleitet wird, um der App
    Lesezugriff auf seine Bestellungen zu erlauben."""
    params = {
        "client_id": app_id,
        "redirect_uri": ru_name,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
    }
    query = "&".join(f"{k}={requests.utils.quote(v, safe='')}" for k, v in params.items())
    return f"{AUTH_URL}?{query}"


def _basic_auth(app_id: str, cert_id: str) -> str:
    return base64.b64encode(f"{app_id}:{cert_id}".encode()).decode()


def exchange_code(app_id: str, cert_id: str, ru_name: str, code: str) -> dict:
    """Tauscht den einmaligen Consent-Code gegen Access- und Refresh-Token.
    Der Code kommt URL-kodiert von eBay zurück - FastAPI dekodiert Query-
    Parameter bereits automatisch, hier also nichts weiter nötig."""
    resp = requests.post(
        TOKEN_URL,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {_basic_auth(app_id, cert_id)}",
        },
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": ru_name},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def refresh_access_token(app_id: str, cert_id: str, refresh_token: str) -> dict:
    """Access-Token ist nur ca. 2 Stunden gültig - vor jedem Sync neu geholt,
    aus dem länger gültigen (ca. 18 Monate) Refresh-Token."""
    resp = requests.post(
        TOKEN_URL,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {_basic_auth(app_id, cert_id)}",
        },
        data={"grant_type": "refresh_token", "refresh_token": refresh_token, "scope": SCOPE},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def finalize_connection(db: Session, conn: models.EbayConnection, app_id: str, cert_id: str, ru_name: str, code: str) -> None:
    """Wird im OAuth-Callback aufgerufen: tauscht den Code gegen Tokens und
    macht die Verbindung nutzbar."""
    try:
        tokens = exchange_code(app_id, cert_id, ru_name, code)
    except Exception as e:
        conn.status = "error"
        conn.last_sync_status = f"Verbindung fehlgeschlagen: {e}"
        db.commit()
        return
    _store_tokens(db, conn, tokens)
    conn.status = "connected"
    db.commit()


def _store_tokens(db: Session, conn: models.EbayConnection, tokens: dict) -> None:
    settings = auth.get_or_create_settings(db)
    refresh_token = tokens.get("refresh_token")
    if refresh_token:
        conn.refresh_token_encrypted = bank_sync.encrypt_secret(settings.secret_key, refresh_token)
        expires_in = tokens.get("refresh_token_expires_in")  # Sekunden
        if expires_in:
            conn.refresh_token_expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))


def fetch_orders(access_token: str, since: datetime) -> list[dict]:
    """Holt abgeschlossene Bestellungen seit einem Zeitpunkt, seitenweise."""
    orders = []
    offset = 0
    limit = 50
    filter_str = f"creationdate:[{since.strftime('%Y-%m-%dT%H:%M:%S.000Z')}..]"
    while True:
        resp = requests.get(
            ORDERS_URL,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            params={"filter": filter_str, "limit": limit, "offset": offset},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("orders") or []
        orders.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return orders


def _parse_order(order: dict) -> tuple[str, float, str | None, str | None, str] | None:
    order_id = order.get("orderId")
    created = order.get("creationDate")
    total = (order.get("pricingSummary") or {}).get("total") or {}
    amount = total.get("value")
    if not order_id or not created or amount is None:
        return None
    buyer = order.get("buyer") or {}
    applicant = buyer.get("username") or "eBay-Käufer"
    line_items = order.get("lineItems") or []
    purpose = ", ".join(li.get("title", "") for li in line_items if li.get("title"))[:200] or "eBay-Verkauf"
    # Verkäufe sind Einnahmen - im Gegensatz zu Bank-/PayPal-Importen, die das
    # Vorzeichen direkt aus der Quelle übernehmen, liefert eBay hier nur einen
    # Betrag ohne Vorzeichen.
    return created[:10], round(abs(float(amount)), 2), applicant, purpose, order_id


def import_orders(db: Session, account_id: int, orders: list[dict]) -> dict:
    imported, skipped = 0, 0
    for order in orders:
        parsed = _parse_order(order)
        if parsed is None:
            continue
        tx_date, amount, applicant, purpose, external_id = parsed
        if crud.import_bank_transaction(db, account_id, tx_date, amount, applicant, purpose, external_id):
            imported += 1
        else:
            skipped += 1
    return {"imported": imported, "skipped": skipped}


def sync(db: Session, conn: models.EbayConnection, app_id: str, cert_id: str) -> dict:
    try:
        settings = auth.get_or_create_settings(db)
        refresh_token = bank_sync.decrypt_secret(settings.secret_key, conn.refresh_token_encrypted)
        tokens = refresh_access_token(app_id, cert_id, refresh_token)
        access_token = tokens["access_token"]

        # Ab dem letzten Sync, mit einem Tag Überlappung - eBay bucht Status-
        # Änderungen teils verzögert, ohne Rückgriff würden solche Vorgänge
        # sonst durchs Raster fallen. Doppelte fängt die Deduplizierung über
        # die orderId ab.
        since = (conn.last_sync_at - timedelta(days=1)) if conn.last_sync_at else (datetime.utcnow() - timedelta(days=365))
        orders = fetch_orders(access_token, since)
        result = import_orders(db, conn.account_id, orders)

        conn.last_sync_at = datetime.utcnow()
        conn.last_sync_status = f"OK: {result['imported']} neu, {result['skipped']} bereits vorhanden"
        db.commit()
        return {"imported": result["imported"], "skipped": result["skipped"], "error": None}
    except Exception as e:
        db.rollback()
        conn.last_sync_status = f"Fehler: {e}"
        conn.last_sync_at = datetime.utcnow()
        db.commit()
        return {"imported": 0, "skipped": 0, "error": str(e)}

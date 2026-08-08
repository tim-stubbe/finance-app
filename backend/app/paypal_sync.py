from datetime import datetime, timedelta

import requests
from sqlalchemy.orm import Session

from . import models, crud

BASE_URL = "https://api-m.paypal.com"
MAX_WINDOW_DAYS = 31
OVERLAP = timedelta(days=1)


def get_access_token(client_id: str, client_secret: str) -> str:
    resp = requests.post(
        f"{BASE_URL}/v1/oauth2/token",
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        headers={"Accept": "application/json", "Accept-Language": "en_US"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_transactions(access_token: str, start: datetime, end: datetime) -> list[dict]:
    transactions = []
    page = 1
    while True:
        resp = requests.get(
            f"{BASE_URL}/v1/reporting/transactions",
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "start_date": start.strftime("%Y-%m-%dT%H:%M:%S-0000"),
                "end_date": end.strftime("%Y-%m-%dT%H:%M:%S-0000"),
                "fields": "transaction_info,payer_info",
                "page_size": 100,
                "page": page,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        transactions.extend(data.get("transaction_details") or [])
        if page >= data.get("total_pages", 1):
            break
        page += 1
    return transactions


# PayPal liefert zu jedem Vorgang einen Ereigniscode statt Klartext. Ohne diese
# Zuordnung landen vor allem die Deckungs-Aufladungen (T0300/T0700) völlig ohne
# Beschreibung in den Buchungen und sehen wie unerklärte Einnahmen aus.
EVENT_CODE_LABELS = {
    "T0000": "PayPal-Zahlung",
    "T0001": "Massenzahlung",
    "T0002": "Abo-Zahlung",
    "T0003": "Abbuchung (vorautorisiert)",
    "T0006": "Express-Checkout-Zahlung",
    "T0011": "Zahlung (gesendet)",
    "T0013": "Rückerstattung",
    "T0300": "PayPal-Aufladung (Deckung)",
    "T0400": "Auszahlung auf Bankkonto",
    "T0700": "Kartenzahlung (Deckung)",
    "T1104": "Bankabbuchung",
    "T1105": "Storno",
}

# Gegenbuchungen, die eine Zahlung finanzieren - keine echten Einnahmen.
FUNDING_EVENT_CODES = {"T0300", "T0700"}


def _parse_transaction(tx: dict) -> tuple[str, float, str | None, str | None, str | None] | None:
    info = tx.get("transaction_info") or {}
    tx_date = info.get("transaction_initiation_date")
    amount = (info.get("transaction_amount") or {}).get("value")
    if not tx_date or amount is None:
        return None
    payer_name = ((tx.get("payer_info") or {}).get("payer_name")) or {}
    applicant = payer_name.get("alternate_full_name") or " ".join(
        filter(None, [payer_name.get("given_name"), payer_name.get("surname")])
    ) or None
    event_code = (info.get("transaction_event_code") or "").strip()
    label = EVENT_CODE_LABELS.get(event_code)
    if not applicant:
        applicant = label
    elif event_code in FUNDING_EVENT_CODES and label:
        # Bei Aufladungen ist der Name irreführend - die Art des Vorgangs zählt.
        applicant = f"{label} – {applicant}"
    purpose = info.get("transaction_subject") or info.get("transaction_note") or info.get("transaction_id")
    return tx_date[:10], round(float(amount), 2), applicant, (purpose or None), info.get("transaction_id")


def import_transactions(db: Session, account_id: int, transactions: list[dict]) -> dict:
    imported, skipped = 0, 0
    for tx in transactions:
        parsed = _parse_transaction(tx)
        if parsed is None:
            continue
        tx_date, amount, applicant, purpose, external_id = parsed
        if crud.import_bank_transaction(db, account_id, tx_date, amount, applicant, purpose, external_id):
            imported += 1
        else:
            skipped += 1
    return {"imported": imported, "skipped": skipped}


def sync(db: Session, conn: models.PayPalConnection, client_id: str, client_secret: str) -> dict:
    try:
        access_token = get_access_token(client_id, client_secret)
        end = datetime.utcnow()
        # Ab dem letzten Sync, aber mit einem Tag Überlappung: PayPal bucht Vorgänge
        # teils verzögert ein, die würden bei einem lückenlosen Fenster fehlen.
        # Doppelte fängt die Deduplizierung über die PayPal-transaction_id ab.
        # Ohne den Rückgriff wäre das Fenster direkt nach einem Sync null Sekunden
        # lang - darauf antwortet PayPal mit 404.
        window_start = (conn.last_sync_at - OVERLAP) if conn.last_sync_at else (end - timedelta(days=365))
        total_imported, total_skipped = 0, 0
        while window_start < end:
            window_end = min(window_start + timedelta(days=MAX_WINDOW_DAYS), end)
            transactions = fetch_transactions(access_token, window_start, window_end)
            result = import_transactions(db, conn.account_id, transactions)
            total_imported += result["imported"]
            total_skipped += result["skipped"]
            window_start = window_end
        conn.last_sync_at = datetime.utcnow()
        conn.last_sync_status = f"OK: {total_imported} neu, {total_skipped} bereits vorhanden"
        db.commit()
        return {"imported": total_imported, "skipped": total_skipped, "error": None}
    except Exception as e:
        # Kam der Fehler aus einem fehlgeschlagenen Flush, ist die Session blockiert -
        # ohne rollback() würde das commit() unten erneut werfen und aus einer
        # lesbaren Fehlermeldung ein HTTP 500 machen.
        db.rollback()
        conn.last_sync_status = f"Fehler: {e}"
        conn.last_sync_at = datetime.utcnow()
        db.commit()
        return {"imported": 0, "skipped": 0, "error": str(e)}

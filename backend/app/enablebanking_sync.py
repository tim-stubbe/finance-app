import base64
import json
import time
from datetime import datetime, timedelta, timezone

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from sqlalchemy.orm import Session

from . import models, crud

BASE_URL = "https://api.enablebanking.com"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _build_jwt(app_id: str, private_key_pem: str) -> str:
    header = {"typ": "JWT", "alg": "RS256", "kid": app_id}
    now = int(time.time())
    payload = {"iss": "enablebanking.com", "aud": "api.enablebanking.com", "iat": now, "exp": now + 3600}
    signing_input = (
        f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}."
        f"{_b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    )
    private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    signature = private_key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{_b64url(signature)}"


def _headers(app_id: str, private_key_pem: str) -> dict:
    return {"Authorization": f"Bearer {_build_jwt(app_id, private_key_pem)}"}


def list_aspsps(app_id: str, private_key_pem: str, country: str) -> list[dict]:
    resp = requests.get(
        f"{BASE_URL}/aspsps", params={"country": country},
        headers=_headers(app_id, private_key_pem), timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("aspsps", data if isinstance(data, list) else [])


def start_auth(app_id: str, private_key_pem: str, aspsp_name: str, aspsp_country: str, redirect_url: str, state: str) -> str:
    valid_until = (datetime.now(timezone.utc) + timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {
        "access": {"valid_until": valid_until},
        "aspsp": {"name": aspsp_name, "country": aspsp_country},
        "state": state,
        "redirect_url": redirect_url,
        "psu_type": "personal",
    }
    resp = requests.post(f"{BASE_URL}/auth", json=body, headers=_headers(app_id, private_key_pem), timeout=15)
    resp.raise_for_status()
    return resp.json()["url"]


def create_session(app_id: str, private_key_pem: str, code: str) -> dict:
    resp = requests.post(f"{BASE_URL}/sessions", json={"code": code}, headers=_headers(app_id, private_key_pem), timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_transactions(app_id: str, private_key_pem: str, eb_account_id: str) -> list[dict]:
    resp = requests.get(
        f"{BASE_URL}/accounts/{eb_account_id}/transactions",
        headers=_headers(app_id, private_key_pem), timeout=20,
    )
    resp.raise_for_status()
    return resp.json().get("transactions", [])


def _parse_transaction(tx: dict) -> tuple[float, str | None, str | None] | None:
    amt_info = tx.get("transactionAmount") or {}
    raw_amount = amt_info.get("amount")
    if raw_amount is None:
        return None
    amount = float(raw_amount)
    if (tx.get("creditDebitIndicator") or "").upper() == "DBIT" and amount > 0:
        amount = -amount

    purpose = tx.get("remittanceInformationUnstructured")
    if not purpose:
        arr = tx.get("remittanceInformationUnstructuredArray") or []
        purpose = " ".join(arr) if arr else None

    if amount < 0:
        applicant = tx.get("creditorName") or (tx.get("creditor") or {}).get("name")
    else:
        applicant = tx.get("debtorName") or (tx.get("debtor") or {}).get("name")

    return round(amount, 2), (applicant or "").strip() or None, (purpose or "").strip() or None


def import_transactions(db: Session, account_id: int, transactions: list[dict]) -> dict:
    imported, skipped = 0, 0
    for tx in transactions:
        tx_date = tx.get("bookingDate") or tx.get("valueDate")
        if not tx_date:
            continue
        parsed = _parse_transaction(tx)
        if parsed is None:
            continue
        amount, applicant, purpose = parsed
        if crud.import_bank_transaction(db, account_id, tx_date, amount, applicant, purpose):
            imported += 1
        else:
            skipped += 1
    return {"imported": imported, "skipped": skipped}


def sync(db: Session, conn: models.EnableBankingConnection, app_id: str, private_key_pem: str) -> dict:
    try:
        transactions = get_transactions(app_id, private_key_pem, conn.eb_account_id)
        result = import_transactions(db, conn.account_id, transactions)
        conn.last_sync_at = datetime.utcnow()
        conn.last_sync_status = f"OK: {result['imported']} neu, {result['skipped']} bereits vorhanden"
        db.commit()
        return {"imported": result["imported"], "skipped": result["skipped"], "error": None}
    except Exception as e:
        # Session nach fehlgeschlagenem Flush freigeben, sonst wirft das commit() erneut.
        db.rollback()
        conn.last_sync_status = f"Fehler: {e}"
        conn.last_sync_at = datetime.utcnow()
        db.commit()
        return {"imported": 0, "skipped": 0, "error": str(e)}


def finalize_connection(db: Session, conn: models.EnableBankingConnection, app_id: str, private_key_pem: str, code: str) -> dict:
    try:
        session = create_session(app_id, private_key_pem, code)
        accounts = session.get("accounts") or []
        if not accounts:
            raise ValueError("Keine Konten von der Bank zurückgegeben")
        first = accounts[0]
        eb_account_id = first.get("uid") if isinstance(first, dict) else str(first)
        if not eb_account_id:
            raise ValueError("Konnte Konto-ID aus der Enable-Banking-Antwort nicht auslesen")
        conn.session_id = session.get("session_id")
        conn.eb_account_id = eb_account_id
        conn.status = "linked"
        db.commit()
        return sync(db, conn, app_id, private_key_pem)
    except Exception as e:
        # Session nach fehlgeschlagenem Flush freigeben, sonst wirft das commit() erneut.
        db.rollback()
        conn.status = "error"
        conn.last_sync_status = f"Fehler beim Verbinden: {e}"
        conn.last_sync_at = datetime.utcnow()
        db.commit()
        return {"imported": 0, "skipped": 0, "error": str(e)}

import base64
import hashlib
from datetime import date, datetime

from cryptography.fernet import Fernet
from fints.client import FinTS3PinTanClient, NeedTANResponse, NeedRetryResponse
from sqlalchemy.orm import Session

from . import models, crud

# Kurzlebiger, prozessinterner Zwischenspeicher für pausierte TAN-Dialoge.
# Bewusst nicht persistiert: geht bei Neustart verloren, dann muss der Sync
# einfach erneut gestartet werden - unkritisch für ein privates Tool.
_pending_tan_sessions: dict[int, dict] = {}


def _fernet(secret_key: str) -> Fernet:
    digest = hashlib.sha256(secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(secret_key: str, value: str) -> str:
    return _fernet(secret_key).encrypt(value.encode()).decode()


def decrypt_secret(secret_key: str, token: str) -> str:
    return _fernet(secret_key).decrypt(token.encode()).decode()


# Beibehalten für bestehende Aufrufer (PIN ist nur ein Anwendungsfall von encrypt_secret).
encrypt_pin = encrypt_secret
decrypt_pin = decrypt_secret


def _find_sepa_account(client: FinTS3PinTanClient, iban: str):
    iban_norm = (iban or "").replace(" ", "").upper()
    for acc in client.get_sepa_accounts():
        if (acc.iban or "").replace(" ", "").upper() == iban_norm:
            return acc
    return None


def _make_client(conn: models.BankConnection, pin: str, product_id: str, from_data: bytes = None) -> FinTS3PinTanClient:
    return FinTS3PinTanClient(
        conn.blz, conn.login, pin, conn.fints_url,
        product_id=product_id,
        from_data=from_data,
    )


def _import_transactions(db: Session, conn: models.BankConnection, transactions) -> dict:
    imported, skipped = 0, 0
    for t in transactions:
        d = t.data
        tx_date = d.get("date")
        amt = d.get("amount")
        if tx_date is None or amt is None:
            continue
        amount = round(float(amt.amount), 2)
        purpose = (d.get("purpose") or d.get("transaction_details") or "").strip() or None
        applicant = (d.get("applicant_name") or "").strip() or None
        if crud.import_bank_transaction(db, conn.account_id, tx_date, amount, applicant, purpose):
            imported += 1
        else:
            skipped += 1

    conn.last_sync_at = datetime.utcnow()
    conn.last_sync_status = f"OK: {imported} neu, {skipped} bereits vorhanden"
    db.commit()
    return {"tan_required": False, "imported": imported, "skipped": skipped}


def _handle_tan_response(conn: models.BankConnection, client: FinTS3PinTanClient, response: NeedTANResponse, pin: str, product_id: str) -> dict:
    dialog_data = client.pause_dialog()
    client_data = client.deconstruct()
    _pending_tan_sessions[conn.id] = {
        "client_data": client_data,
        "dialog_data": dialog_data,
        "challenge_data": response.get_data(),
        "pin": pin,
        "product_id": product_id,
    }
    return {
        "tan_required": True,
        "challenge": response.challenge_html or response.challenge or "TAN erforderlich",
    }


def start_sync(db: Session, conn: models.BankConnection, pin: str, product_id: str, since: date) -> dict:
    try:
        client = _make_client(conn, pin, product_id)
        with client:
            account = _find_sepa_account(client, conn.iban)
            if not account:
                raise ValueError(f"Konto mit IBAN {conn.iban} bei dieser Bank nicht gefunden")
            response = client.get_transactions(account, since, date.today())
            if isinstance(response, NeedTANResponse):
                return _handle_tan_response(conn, client, response, pin, product_id)
            return _import_transactions(db, conn, response)
    except Exception as e:
        # Session nach fehlgeschlagenem Flush freigeben, sonst wirft das commit() erneut.
        db.rollback()
        conn.last_sync_status = f"Fehler: {e}"
        db.commit()
        return {"tan_required": False, "imported": 0, "skipped": 0, "error": str(e)}


def submit_tan(db: Session, conn: models.BankConnection, tan: str) -> dict:
    pending = _pending_tan_sessions.get(conn.id)
    if not pending:
        return {"tan_required": False, "imported": 0, "skipped": 0, "error": "Keine offene TAN-Anfrage für diese Verbindung"}
    try:
        client = _make_client(conn, pending["pin"], pending["product_id"], from_data=pending["client_data"])
        challenge = NeedRetryResponse.from_data(pending["challenge_data"])
        with client.resume_dialog(pending["dialog_data"]):
            response = client.send_tan(challenge, tan)
        del _pending_tan_sessions[conn.id]
        if isinstance(response, NeedTANResponse):
            return _handle_tan_response(conn, client, response, pending["pin"], pending["product_id"])
        return _import_transactions(db, conn, response)
    except Exception as e:
        # Session nach fehlgeschlagenem Flush freigeben, sonst wirft das commit() erneut.
        db.rollback()
        _pending_tan_sessions.pop(conn.id, None)
        conn.last_sync_status = f"Fehler: {e}"
        db.commit()
        return {"tan_required": False, "imported": 0, "skipped": 0, "error": str(e)}

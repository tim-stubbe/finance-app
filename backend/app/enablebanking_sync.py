import base64
import json
import re
import time
from datetime import datetime, timedelta, timezone

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from sqlalchemy import func
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


def _supported_psu_type(app_id: str, private_key_pem: str, aspsp_name: str, aspsp_country: str) -> str:
    """Manche ASPSPs unterstützen NUR "business" (live beobachtet: Finom, das gibt
    es nur als Geschäftskonto) - das bisher fest verdrahtete "personal" ließ den
    /auth-Aufruf für solche Banken mit der irreführenden Meldung "Wrong ASPSP name
    provided" fehlschlagen (der eigentliche Fehler war der psu_type, nicht der
    Name). "personal" bevorzugt, wenn unterstützt (deckt die große Mehrheit der
    Banken ab), sonst der erste von der ASPSP selbst gemeldete Typ. Schlägt die
    Abfrage fehl, bleibt "personal" als bisheriges Verhalten erhalten."""
    try:
        for a in list_aspsps(app_id, private_key_pem, aspsp_country):
            if a.get("name") == aspsp_name:
                supported = a.get("psu_types") or ["personal"]
                return "personal" if "personal" in supported else supported[0]
    except Exception:
        pass
    return "personal"


def start_auth(app_id: str, private_key_pem: str, aspsp_name: str, aspsp_country: str, redirect_url: str, state: str) -> str:
    valid_until = (datetime.now(timezone.utc) + timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {
        "access": {"valid_until": valid_until},
        "aspsp": {"name": aspsp_name, "country": aspsp_country},
        "state": state,
        "redirect_url": redirect_url,
        "psu_type": _supported_psu_type(app_id, private_key_pem, aspsp_name, aspsp_country),
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


_MERCHANT_IN_PURPOSE_RE = re.compile(r"Ihr Einkauf bei (.+?)(?:\s+ABBUCHUNG\b|$)", re.IGNORECASE)


def _better_applicant_name(applicant: str | None, purpose: str | None) -> str | None:
    """Bei PayPal-Buchungen ist `creditor.name` oft nur "PayPal (Europe) S.a r.l.
    ..." - der eigentliche Händler (z.B. "DPD Deutschland GmbH") steht
    stattdessen im Verwendungszweck ("... Ihr Einkauf bei DPD Deutschland
    GmbH"). Live beobachtet: dadurch liefen Handler-Angaben komplett unter
    "PayPal" zusammen, obwohl der echte Empfänger bekannt war - schlecht für
    Kategorisierung und "Wo dein Geld hingeht". Nur ersetzen, wenn der
    Applicant-Name selbst nach PayPal aussieht UND der gefundene Händlername
    nicht wieder nur "PayPal" ist (dann steckt wirklich keine bessere
    Information drin, z.B. bei einer PayPal-eigenen Gebühr)."""
    if not applicant or "paypal" not in applicant.lower() or not purpose:
        return applicant
    match = _MERCHANT_IN_PURPOSE_RE.search(purpose)
    if not match:
        return applicant
    merchant = match.group(1).strip().rstrip(",")
    if not merchant or "paypal" in merchant.lower():
        return applicant
    return merchant


def _parse_transaction(tx: dict) -> tuple[float, str | None, str | None] | None:
    """Feldnamen live gegen die echte Enable-Banking-API verifiziert (snake_case,
    NICHT das ursprünglich angenommene camelCase eines typischen PSD2/NextGenPSD2-
    Schemas) - reale Antwort z.B.: {"transaction_amount": {"amount": "0.84",
    "currency": "EUR"}, "credit_debit_indicator": "DBIT", "booking_date": "...",
    "remittance_information": ["..."], "creditor": {"name": "..."}, ...}. Die
    ursprüngliche camelCase-Version hat dadurch jede einzelne Buchung stillschweigend
    übersprungen (0 importiert, 0 übersprungen) - live mit 726 echten Buchungen auf
    3 C24-Konten reproduziert und gefixt."""
    amt_info = tx.get("transaction_amount") or {}
    raw_amount = amt_info.get("amount")
    if raw_amount is None:
        return None
    amount = float(raw_amount)
    if (tx.get("credit_debit_indicator") or "").upper() == "DBIT" and amount > 0:
        amount = -amount

    remittance = tx.get("remittance_information") or []
    purpose = " ".join(remittance) if isinstance(remittance, list) else remittance

    if amount < 0:
        applicant = (tx.get("creditor") or {}).get("name")
    else:
        applicant = (tx.get("debtor") or {}).get("name")
    applicant = _better_applicant_name(applicant, purpose)

    return round(amount, 2), (applicant or "").strip() or None, (purpose or "").strip() or None


def import_transactions(db: Session, account_id: int, transactions: list[dict]) -> dict:
    imported, skipped = 0, 0
    for tx in transactions:
        # Live beobachtet: bei PayPal als Enable-Banking-Quelle sind booking_date
        # UND value_date beide null, nur transaction_date ist gesetzt - bei
        # klassischen Banken (z.B. C24) ist es umgekehrt der Fall. Alle drei
        # probieren statt bei den ersten beiden aufzugeben, sonst wird jede
        # einzelne Buchung dieser Quelle still übersprungen (0 importiert,
        # 0 übersprungen - sieht wie ein stiller Erfolg aus, ist aber keiner).
        tx_date = tx.get("booking_date") or tx.get("value_date") or tx.get("transaction_date")
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


def fetch_account_balance(app_id: str, private_key_pem: str, eb_account_id: str, currency: str = "EUR") -> float | None:
    """`name` ist bei den meisten Banken ein Freitext-Label wie "Interim available
    balance", NICHT der Waehrungscode - nur bei PayPal steht dort zufaellig "EUR".
    Deshalb muss `balance_amount.currency` verglichen werden, nicht `name` (live
    beobachtet: fuer alle Nicht-PayPal-Konten kam deshalb immer None zurueck, der
    Saldo-Abgleich in sync() lief seit Einfuehrung fuer keins dieser Konten je)."""
    url_path = f"/accounts/{eb_account_id}/balances"
    resp = requests.get(f"{BASE_URL}{url_path}", headers=_headers(app_id, private_key_pem), timeout=15)
    resp.raise_for_status()
    for b in resp.json().get("balances", []):
        amt = b.get("balance_amount") or {}
        if amt.get("currency") == currency:
            return float(amt["amount"])
    return None


def sync(db: Session, conn: models.EnableBankingConnection, app_id: str, private_key_pem: str) -> dict:
    try:
        transactions = get_transactions(app_id, private_key_pem, conn.eb_account_id)
        result = import_transactions(db, conn.account_id, transactions)

        # Echten Kontostand von der Bank abgleichen, statt ihn blind aus der Summe
        # der importierten Buchungen abzuleiten. Bei einem klassischen Bankkonto
        # stimmt "Summe aller Buchungen ab Start" mit dem Saldo überein - bei einem
        # Zahlungsdienst wie PayPal NICHT: live beobachtet 0,00 € echter Saldo
        # gegen -3.565,46 € aus reiner Buchungssumme, weil viel Geld nur
        # durchfließt, ohne dass PayPal es tatsächlich dauerhaft hält. initial_balance
        # wird deshalb bei jedem Sync so nachjustiert, dass initial_balance + Summe
        # aller Buchungen wieder exakt dem von der Bank gemeldeten Saldo entspricht.
        try:
            real_balance = fetch_account_balance(app_id, private_key_pem, conn.eb_account_id)
            if real_balance is not None:
                account = db.get(models.Account, conn.account_id)
                if account:
                    tx_sum = db.query(func.coalesce(func.sum(models.Transaction.amount), 0.0)).filter(
                        models.Transaction.account_id == account.id
                    ).scalar() or 0.0
                    account.initial_balance = round(real_balance - tx_sum, 2)
        except Exception:
            pass  # Saldo-Abgleich ist ein Bonus - darf den Sync nicht scheitern lassen

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


def _account_uid(acc) -> str | None:
    if isinstance(acc, dict):
        return acc.get("uid")
    return str(acc) if acc else None


def _account_label(index: int, acc: dict) -> str:
    """Ein PSU kann bei einer Bank mehrere Konten gleichzeitig freigeben (live
    beobachtet: 3 C24-Konten in einer Autorisierung) - jedes zusätzliche Konto
    braucht einen eigenen, unterscheidbaren Namen, da wir dafür automatisch ein
    neues Konto anlegen (siehe finalize_connection). Enable Bankings genaue
    Feldbenennung variiert je Bank, deshalb mehrere gängige Felder probieren
    statt eins fest anzunehmen."""
    name = acc.get("name") or acc.get("product") or acc.get("cash_account_type")
    account_id = acc.get("account_id")
    iban = (account_id.get("iban") if isinstance(account_id, dict) else None) or acc.get("iban")
    if name and iban:
        return f"{name} ({iban[-4:]})"
    if name:
        return str(name)
    if iban:
        return f"Konto ({iban[-4:]})"
    return f"Konto {index}"


def finalize_connection(db: Session, conn: models.EnableBankingConnection, app_id: str, private_key_pem: str, code: str) -> dict:
    """Eine Autorisierung kann MEHRERE Konten gleichzeitig freigeben (z.B. Haupt-,
    Investment- und Urlaubskonto bei C24 in einer einzigen Freigabe) - die ID des
    Nutzers, die vorab für GENAU EIN Konto in der App angelegte `conn`, deckt aber
    nur das erste ab. Für jedes weitere Konto wird automatisch ein neues Konto samt
    eigener Verbindung angelegt (gleiche Sitzung, eigene Konto-ID) statt die
    zusätzlichen Konten stillschweigend zu verwerfen - das ist live beobachtet
    tatsächlich passiert, bevor dieser Fix kam."""
    try:
        session = create_session(app_id, private_key_pem, code)
        accounts = session.get("accounts") or []
        if not accounts:
            raise ValueError("Keine Konten von der Bank zurückgegeben")

        eb_account_id = _account_uid(accounts[0])
        if not eb_account_id:
            raise ValueError("Konnte Konto-ID aus der Enable-Banking-Antwort nicht auslesen")
        conn.session_id = session.get("session_id")
        conn.eb_account_id = eb_account_id
        conn.status = "linked"
        db.commit()
        result = sync(db, conn, app_id, private_key_pem)
        total_imported, total_skipped = result["imported"], result["skipped"]

        extra_linked = 0
        for i, acc in enumerate(accounts[1:], start=2):
            extra_eb_account_id = _account_uid(acc if isinstance(acc, dict) else {})
            if not extra_eb_account_id:
                continue
            # Nutzer legen bei Banken mit mehreren Konten (z.B. Finom Handel + Management)
            # oft schon leere Platzhalterkonten passend zum ASPSP-Namen an, bevor sie die
            # Verbindung starten - die sollen hier wiederverwendet werden statt live
            # (Finom) beobachtet ein weiteres, redundantes Konto anzulegen.
            reusable = (
                db.query(models.Account)
                .filter(
                    models.Account.space_id == conn.space_id,
                    models.Account.name.ilike(f"%{conn.aspsp_name}%"),
                    ~db.query(models.EnableBankingConnection)
                    .filter(models.EnableBankingConnection.account_id == models.Account.id)
                    .exists(),
                    ~db.query(models.Transaction)
                    .filter(models.Transaction.account_id == models.Account.id)
                    .exists(),
                )
                .order_by(models.Account.id)
                .first()
            )
            if reusable:
                new_account = reusable
            else:
                new_account = models.Account(
                    name=_account_label(i, acc if isinstance(acc, dict) else {}),
                    type=models.AccountType.girokonto, initial_balance=0.0, space_id=conn.space_id,
                )
                db.add(new_account)
                db.commit()
                db.refresh(new_account)
            extra_conn = models.EnableBankingConnection(
                space_id=conn.space_id, account_id=new_account.id,
                aspsp_name=conn.aspsp_name, aspsp_country=conn.aspsp_country,
                state=f"{conn.state}:{i}", session_id=conn.session_id,
                eb_account_id=extra_eb_account_id, status="linked",
            )
            db.add(extra_conn)
            db.commit()
            db.refresh(extra_conn)
            extra_result = sync(db, extra_conn, app_id, private_key_pem)
            total_imported += extra_result["imported"]
            total_skipped += extra_result["skipped"]
            extra_linked += 1

        return {"imported": total_imported, "skipped": total_skipped, "error": None, "extra_accounts_linked": extra_linked}
    except Exception as e:
        # Session nach fehlgeschlagenem Flush freigeben, sonst wirft das commit() erneut.
        db.rollback()
        conn.status = "error"
        conn.last_sync_status = f"Fehler beim Verbinden: {e}"
        conn.last_sync_at = datetime.utcnow()
        db.commit()
        return {"imported": 0, "skipped": 0, "error": str(e)}

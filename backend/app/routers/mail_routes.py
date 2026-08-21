"""E-Mail-Belege (IMAP-Postfach abholen, Anhänge zuordnen) und
Kreditkarten-Abrechnungen (per Mail-Absender erkannt).

Sechzehnter Schritt der Code-Modularisierung (siehe ROADMAP.md), nach
investments/tax/debts/goals/trips/wishlist/personal/business_life/
budgets_alerts/deadlines/calendar_todos/categories/immich_routes/
bank_connections/enablebanking_ebay. Kreditkarten-Einstellungen/-Fälligkeit
gehören hier mit hinein, weil CreditCardBill von run_mail_sync selbst
erzeugt wird (siehe dort).

`find_receipt_matches` und `run_mail_sync` (ohne führenden Unterstrich)
werden auch außerhalb gebraucht - ersteres vom Beleg-Chat-Endpunkt
(main.beleg_chat, unabhängige Domäne, bleibt in main.py), letzteres vom
täglichen main._scheduled_mail_sync - deshalb hier exportiert und in
main.py zurückimportiert, gleiches Muster wie goal_out/immich_credentials."""

import os
import uuid
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, crud, auth, bank_sync, mail_sync, document_extract
from ..database import get_db, DATA_DIR

# Eigenständig berechnet statt aus main importiert (main.py importiert diesen
# Router beim Start VOR der Stelle, an der main.UPLOAD_DIR definiert wird -
# ein Rückimport von dort wäre ein Zirkelbezug). Identische Berechnung wie
# in main.py.
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

mail_router = APIRouter(prefix="/api")


def find_receipt_matches(db: Session, space_id: int, amount: float, tx_date: date, tolerance_days: int = 3) -> list[dict]:
    """Bestehende Buchungen ohne Beleg, die zu Betrag/Datum eines gerade hochgeladenen Belegs passen könnten."""
    candidates = crud.transactions_missing_receipt(db, space_id)
    matches = []
    for t in candidates:
        if abs(abs(t.amount) - abs(amount)) > 0.01:
            continue
        if abs((t.date - tx_date).days) > tolerance_days:
            continue
        matches.append({"id": t.id, "date": t.date.isoformat(), "amount": t.amount, "description": t.description})
    return matches


# ---------------- E-Mail-Belege ----------------
def _parse_receipt(settings, content: bytes, filename: str) -> tuple[date | None, float | None, str | None]:
    """Dünner Wrapper um document_extract.parse_receipt_fields - die gemeinsam
    mit der Datei-Sortierung genutzte Beleg-Auswertung (siehe dort)."""
    return document_extract.parse_receipt_fields(
        settings.ollama_url, settings.ollama_model, settings.beleg_chat_model, content, filename,
    )


def run_mail_sync(db: Session, space_id: int) -> dict:
    """Holt neue Anhänge, wertet sie aus und ordnet eindeutige Treffer zu."""
    s = auth.get_or_create_settings(db)
    if not (s.imap_host and s.imap_user and s.imap_password_encrypted):
        raise ValueError("Postfach ist nicht vollständig eingerichtet.")

    passwort = bank_sync.decrypt_secret(s.secret_key, s.imap_password_encrypted)
    anhaenge = mail_sync.fetch_attachments(
        s.imap_host, s.imap_port, s.imap_user, passwort, s.imap_folder, s.mail_last_sync_at
    )

    neu = uebersprungen = zugeordnet = 0
    for a in anhaenge:
        vorhanden = db.query(models.MailAttachment).filter(
            models.MailAttachment.message_id == a["message_id"],
            models.MailAttachment.filename == a["filename"],
        ).first()
        if vorhanden:
            uebersprungen += 1
            continue

        endung = os.path.splitext(a["filename"])[1]
        speichername = f"mail_{uuid.uuid4().hex}{endung}"
        with open(os.path.join(UPLOAD_DIR, speichername), "wb") as f:
            f.write(a["content"])

        # Kreditkarten-Rechnungsmails werden NICHT wie ein normaler Beleg
        # gelesen (Belegdatum+Einzelbetrag ergeben bei einer Abrechnung mit
        # vielen Buchungen keinen Sinn) - stattdessen Faelligkeitsdatum +
        # Gesamtbetrag, siehe CreditCardBill.
        creditcard_target = s.creditcard_account_id or s.creditcard_debt_id
        ist_kreditkarten_mail = bool(
            s.creditcard_mail_sender and creditcard_target
            and s.creditcard_mail_sender.lower() in (a.get("sender") or "").lower()
        )
        if ist_kreditkarten_mail:
            datum, betrag, fehler = document_extract.parse_creditcard_bill_fields(
                s.ollama_url, s.ollama_model, s.beleg_chat_model, a["content"], a["filename"],
            )
        else:
            datum, betrag, fehler = _parse_receipt(s, a["content"], a["filename"])
        eintrag = models.MailAttachment(
            message_id=a["message_id"], filename=a["filename"],
            stored_filename=speichername, content_type=a.get("content_type"),
            size_bytes=len(a["content"]), sender=a.get("sender"),
            subject=a.get("subject"), mail_date=a.get("mail_date"),
            parsed_amount=betrag, parsed_date=datum, parse_error=fehler,
        )
        db.add(eintrag)
        db.flush()
        neu += 1

        if ist_kreditkarten_mail and (datum or betrag):
            db.add(models.CreditCardBill(
                account_id=s.creditcard_account_id, debt_id=s.creditcard_debt_id,
                message_id=a["message_id"], subject=a.get("subject"), due_date=datum, amount=betrag,
                mail_attachment_id=eintrag.id,
            ))
            eintrag.status = "ignored"  # kein Beleg zum Zuordnen, taucht sonst leer im Beleg-Eingang auf
            continue

        # Nur bei GENAU EINEM passenden Kandidaten automatisch zuordnen. Bei
        # mehreren wäre es geraten - dann entscheidet der Nutzer in der Liste.
        if datum and betrag:
            treffer = find_receipt_matches(db, space_id, betrag, datum)
            if len(treffer) == 1:
                tx_id = treffer[0]["id"]
                crud.set_receipt(db, tx_id, space_id, speichername)
                eintrag.status = "attached"
                eintrag.transaction_id = tx_id
                zugeordnet += 1

    s.mail_last_sync_at = datetime.utcnow()
    db.commit()
    return {"neu": neu, "uebersprungen": uebersprungen, "zugeordnet": zugeordnet}


@mail_router.get("/settings/mail", response_model=schemas.MailSettingsOut)
def get_mail_settings(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    return schemas.MailSettingsOut(
        enabled=s.mail_enabled, host=s.imap_host, port=s.imap_port,
        user=s.imap_user, folder=s.imap_folder,
        password_set=bool(s.imap_password_encrypted),
        last_sync_at=s.mail_last_sync_at.isoformat() if s.mail_last_sync_at else None,
    )


@mail_router.put("/settings/mail", response_model=schemas.MailSettingsOut)
def update_mail_settings(data: schemas.MailSettingsUpdate, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    s.mail_enabled = data.enabled
    s.imap_host = (data.host or "").strip() or None
    s.imap_port = data.port or 993
    s.imap_user = (data.user or "").strip() or None
    s.imap_folder = (data.folder or "INBOX").strip() or "INBOX"
    if data.password:
        s.imap_password_encrypted = bank_sync.encrypt_secret(s.secret_key, data.password)
    db.commit()
    return get_mail_settings(db)


@mail_router.delete("/settings/mail", response_model=schemas.MailSettingsOut)
def remove_mail_settings(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    s.mail_enabled = False
    s.imap_host = s.imap_user = s.imap_password_encrypted = None
    db.commit()
    return get_mail_settings(db)


@mail_router.get("/settings/creditcard", response_model=schemas.CreditCardSettingsOut)
def get_creditcard_settings(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    return schemas.CreditCardSettingsOut(
        mail_sender=s.creditcard_mail_sender, account_id=s.creditcard_account_id, debt_id=s.creditcard_debt_id,
    )


@mail_router.put("/settings/creditcard", response_model=schemas.CreditCardSettingsOut)
def update_creditcard_settings(data: schemas.CreditCardSettingsUpdate, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    s.creditcard_mail_sender = (data.mail_sender or "").strip() or None
    s.creditcard_account_id = data.account_id
    s.creditcard_debt_id = data.debt_id
    db.commit()
    return get_creditcard_settings(db)


@mail_router.get("/creditcard-bills/next", response_model=Optional[schemas.CreditCardBillOut])
def get_next_creditcard_bill(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    bill = crud.next_creditcard_bill(db, space_id)
    if not bill:
        return None
    label = (bill.account.name if bill.account else None) or (bill.debt.name if bill.debt else None) or "Kreditkarte"
    return schemas.CreditCardBillOut(account_name=label, due_date=bill.due_date, amount=bill.amount)


@mail_router.post("/mail/test", response_model=schemas.MailTestResult)
def test_mail(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    if not (s.imap_host and s.imap_user and s.imap_password_encrypted):
        return schemas.MailTestResult(ok=False, error="Postfach ist nicht vollständig eingerichtet.")
    try:
        passwort = bank_sync.decrypt_secret(s.secret_key, s.imap_password_encrypted)
        info = mail_sync.check_connection(s.imap_host, s.imap_port, s.imap_user,
                                          passwort, s.imap_folder)
        return schemas.MailTestResult(ok=True, **info)
    except Exception as e:
        return schemas.MailTestResult(ok=False, error=str(e))


@mail_router.post("/mail/sync", response_model=schemas.MailSyncResult)
def sync_mail(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    try:
        r = run_mail_sync(db, space_id)
    except Exception as e:
        db.rollback()
        raise HTTPException(502, f"Abholen fehlgeschlagen: {e}")
    return schemas.MailSyncResult(
        new_attachments=r["neu"], skipped=r["uebersprungen"], auto_attached=r["zugeordnet"]
    )


@mail_router.get("/mail/attachments", response_model=List[schemas.MailAttachmentOut])
def list_mail_attachments(status: str = "pending", db: Session = Depends(get_db),
                          space_id: int = Depends(auth.get_active_space_id)):
    q = db.query(models.MailAttachment)
    if status != "alle":
        q = q.filter(models.MailAttachment.status == status)
    eintraege = q.order_by(models.MailAttachment.mail_date.desc().nullslast()).limit(200).all()

    out = []
    for a in eintraege:
        # Passende Buchungen erst hier ermitteln, nicht speichern: die
        # Buchungslage ändert sich (neue Umsätze kommen nach), eine gespeicherte
        # Vorschlagsliste wäre nach dem nächsten Bank-Sync veraltet.
        vorschlaege = []
        if a.status == "pending" and a.parsed_amount and a.parsed_date:
            vorschlaege = find_receipt_matches(db, space_id, a.parsed_amount, a.parsed_date)
        out.append(schemas.MailAttachmentOut(
            id=a.id, filename=a.filename, stored_filename=a.stored_filename,
            sender=a.sender, subject=a.subject,
            mail_date=a.mail_date.isoformat() if a.mail_date else None,
            size_bytes=a.size_bytes, status=a.status,
            parsed_amount=a.parsed_amount,
            parsed_date=a.parsed_date.isoformat() if a.parsed_date else None,
            parse_error=a.parse_error, transaction_id=a.transaction_id,
            suggestions=vorschlaege,
        ))
    return out


@mail_router.post("/mail/attachments/{attachment_id}/attach")
def attach_mail_attachment(attachment_id: int, data: schemas.MailAttachRequest,
                           db: Session = Depends(get_db),
                           space_id: int = Depends(auth.get_active_space_id)):
    a = db.query(models.MailAttachment).filter(models.MailAttachment.id == attachment_id).first()
    if not a:
        raise HTTPException(404, "Anhang nicht gefunden")
    if not crud.get_transaction(db, data.transaction_id, space_id):
        raise HTTPException(404, "Buchung nicht gefunden")
    crud.set_receipt(db, data.transaction_id, space_id, a.stored_filename)
    a.status = "attached"
    a.transaction_id = data.transaction_id
    db.commit()
    return {"ok": True}


@mail_router.post("/mail/attachments/{attachment_id}/create-transaction", response_model=schemas.TransactionOut)
def create_transaction_from_mail(attachment_id: int, data: schemas.MailCreateTransactionRequest,
                                 db: Session = Depends(get_db),
                                 space_id: int = Depends(auth.get_active_space_id)):
    """Für den Fall, dass zum Beleg noch gar keine Buchung existiert - z.B.
    weil der Kontoumsatz noch nicht importiert wurde. Legt eine neue Buchung
    an und hängt den Beleg direkt mit an, in einem Schritt.

    Wie beim Beleg-Chat gilt: die KI liefert nur die Vorlage (Datum/Betrag),
    angelegt wird erst nach ausdrücklicher Bestätigung durch den Nutzer -
    hier durch den expliziten Aufruf dieses Endpunkts mit den (ggf. vom
    Nutzer korrigierten) Werten, nicht automatisch beim Abholen.
    """
    a = db.query(models.MailAttachment).filter(models.MailAttachment.id == attachment_id).first()
    if not a:
        raise HTTPException(404, "Anhang nicht gefunden")
    if a.status != "pending":
        raise HTTPException(400, "Dieser Beleg ist bereits bearbeitet.")
    konto = db.query(models.Account).filter(models.Account.id == data.account_id).first()
    if not konto:
        raise HTTPException(404, "Konto nicht gefunden")

    tx = crud.create_transaction(db, schemas.TransactionCreate(
        date=data.date, amount=data.amount,
        description=data.description or a.subject or a.filename,
        account_id=data.account_id, category_id=data.category_id,
    ))
    crud.set_receipt(db, tx.id, space_id, a.stored_filename)
    a.status = "attached"
    a.transaction_id = tx.id
    db.commit()
    db.refresh(tx)
    return tx


@mail_router.post("/mail/attachments/{attachment_id}/ignore")
def ignore_mail_attachment(attachment_id: int, db: Session = Depends(get_db)):
    a = db.query(models.MailAttachment).filter(models.MailAttachment.id == attachment_id).first()
    if not a:
        raise HTTPException(404, "Anhang nicht gefunden")
    a.status = "ignored"
    db.commit()
    return {"ok": True}

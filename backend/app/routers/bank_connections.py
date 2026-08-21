"""Bank-Verbindungen (FinTS/HBCI), Bitvavo (Krypto-Börse) und PayPal.

Vierzehnter Schritt der Code-Modularisierung (siehe ROADMAP.md), nach
investments/tax/debts/goals/trips/wishlist/personal/business_life/
budgets_alerts/deadlines/calendar_todos/categories/immich_routes. Drei
verwandte Anbindungs-Domänen (jeweils Verbindung anlegen/löschen/syncen),
standen im selben main.py-Abschnitt. Reine Verschiebung ohne
Verhaltensänderung.

`_sync_all_connections` (main.py) bleibt dort - synct alle Verbindungstypen
inkl. Enable Banking/eBay gemeinsam für Scheduler und Digest, ruft dafür
crud.*/bank_sync.*/exchange_sync.*/paypal_sync.* direkt auf statt der hier
verschobenen main.py-Endpunkt-Funktionen (keine Abhängigkeit hierher)."""

from datetime import date, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas, crud, auth, bank_sync, exchange_sync, paypal_sync
from ..database import get_db

bank_connections_router = APIRouter(prefix="/api")


# ---------------- FinTS/HBCI-Bankverbindungen ----------------
@bank_connections_router.get("/bank-connections", response_model=List[schemas.BankConnectionOut])
def list_bank_connections(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.get_bank_connections(db, space_id)


@bank_connections_router.post("/bank-connections", response_model=schemas.BankConnectionOut)
def create_bank_connection(data: schemas.BankConnectionCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if not crud.get_account(db, data.account_id, space_id):
        raise HTTPException(400, "Ziel-Konto existiert nicht in diesem Bereich")
    settings = auth.get_or_create_settings(db)
    pin_encrypted = bank_sync.encrypt_pin(settings.secret_key, data.pin)
    return crud.create_bank_connection(
        db, space_id, data.name, data.blz, data.fints_url, data.login, pin_encrypted, data.account_id, data.iban,
    )


@bank_connections_router.delete("/bank-connections/{connection_id}")
def remove_bank_connection(connection_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.delete_bank_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "Bank-Verbindung nicht gefunden")
    return {"ok": True}


@bank_connections_router.post("/bank-connections/{connection_id}/sync", response_model=schemas.SyncResult)
def sync_bank_connection(connection_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.get_bank_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "Bank-Verbindung nicht gefunden")
    settings = auth.get_or_create_settings(db)
    if not settings.fints_product_id:
        raise HTTPException(400, "Bitte zuerst eine FinTS-Produkt-ID in den Einstellungen hinterlegen")
    pin = bank_sync.decrypt_pin(settings.secret_key, conn.pin_encrypted)
    since = conn.last_sync_at.date() if conn.last_sync_at else date.today() - timedelta(days=90)
    result = bank_sync.start_sync(db, conn, pin, settings.fints_product_id, since)
    return schemas.SyncResult(**result)


@bank_connections_router.post("/bank-connections/{connection_id}/submit-tan", response_model=schemas.SyncResult)
def submit_tan(connection_id: int, data: schemas.TanSubmit, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.get_bank_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "Bank-Verbindung nicht gefunden")
    result = bank_sync.submit_tan(db, conn, data.tan)
    return schemas.SyncResult(**result)


# ---------------- Bitvavo (Krypto-Börse) ----------------
@bank_connections_router.get("/bitvavo-connections", response_model=List[schemas.BitvavoConnectionOut])
def list_bitvavo_connections(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.get_bitvavo_connections(db, space_id)


@bank_connections_router.post("/bitvavo-connections", response_model=schemas.BitvavoConnectionOut)
def create_bitvavo_connection(data: schemas.BitvavoConnectionCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    settings = auth.get_or_create_settings(db)
    api_key_enc = bank_sync.encrypt_secret(settings.secret_key, data.api_key)
    api_secret_enc = bank_sync.encrypt_secret(settings.secret_key, data.api_secret)
    return crud.create_bitvavo_connection(db, space_id, data.name, api_key_enc, api_secret_enc)


@bank_connections_router.delete("/bitvavo-connections/{connection_id}")
def remove_bitvavo_connection(connection_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.delete_bitvavo_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "Bitvavo-Verbindung nicht gefunden")
    return {"ok": True}


@bank_connections_router.post("/bitvavo-connections/{connection_id}/sync", response_model=schemas.BitvavoSyncResult)
def sync_bitvavo_connection(connection_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.get_bitvavo_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "Bitvavo-Verbindung nicht gefunden")
    settings = auth.get_or_create_settings(db)
    api_key = bank_sync.decrypt_secret(settings.secret_key, conn.api_key_encrypted)
    api_secret = bank_sync.decrypt_secret(settings.secret_key, conn.api_secret_encrypted)
    result = exchange_sync.sync(db, conn, api_key, api_secret, space_id)
    return schemas.BitvavoSyncResult(**result)


# ---------------- PayPal ----------------
@bank_connections_router.get("/paypal-connections", response_model=List[schemas.PayPalConnectionOut])
def list_paypal_connections(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.get_paypal_connections(db, space_id)


@bank_connections_router.post("/paypal-connections", response_model=schemas.PayPalConnectionOut)
def create_paypal_connection(data: schemas.PayPalConnectionCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    settings = auth.get_or_create_settings(db)
    client_id_enc = bank_sync.encrypt_secret(settings.secret_key, data.client_id)
    client_secret_enc = bank_sync.encrypt_secret(settings.secret_key, data.client_secret)
    return crud.create_paypal_connection(db, space_id, data.account_id, data.name, client_id_enc, client_secret_enc)


@bank_connections_router.delete("/paypal-connections/{connection_id}")
def remove_paypal_connection(connection_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.delete_paypal_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "PayPal-Verbindung nicht gefunden")
    return {"ok": True}


@bank_connections_router.post("/paypal-connections/{connection_id}/sync", response_model=schemas.PayPalSyncResult)
def sync_paypal_connection(connection_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.get_paypal_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "PayPal-Verbindung nicht gefunden")
    settings = auth.get_or_create_settings(db)
    client_id = bank_sync.decrypt_secret(settings.secret_key, conn.client_id_encrypted)
    client_secret = bank_sync.decrypt_secret(settings.secret_key, conn.client_secret_encrypted)
    result = paypal_sync.sync(db, conn, client_id, client_secret)
    return schemas.PayPalSyncResult(**result)

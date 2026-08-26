"""Externe Konten-Verbindungen (FinTS-Banken, Bitvavo, PayPal, Enable Banking,
eBay) - dritter Schritt der crud.py-Modularisierung (siehe ROADMAP.md),
analog zu crud_investments.py/crud_todos.py. Reine Verschiebung ohne
Verhaltensänderung: schlichtes CRUD für die jeweiligen Connection-Modelle,
ohne Abhängigkeiten zu anderen crud.py-Domänen.

crud.py importiert alle hier definierten Namen zurück, damit jeder
bestehende `crud.get_bitvavo_connections(...)`-Aufrufstil in main.py/
routers/ unverändert weiterfunktioniert."""

from sqlalchemy.orm import Session

from . import models


# ---------- Bank-Verbindungen (FinTS) ----------
def get_bank_connections(db: Session, space_id: int):
    return db.query(models.BankConnection).filter(models.BankConnection.space_id == space_id).all()


def get_bank_connection(db: Session, connection_id: int, space_id: int):
    return (
        db.query(models.BankConnection)
        .filter(models.BankConnection.id == connection_id, models.BankConnection.space_id == space_id)
        .first()
    )


def get_all_bank_connections(db: Session):
    return db.query(models.BankConnection).all()


def create_bank_connection(db: Session, space_id: int, name: str, blz: str, fints_url: str, login: str, pin_encrypted: str, account_id: int, iban: str):
    conn = models.BankConnection(
        space_id=space_id, name=name, blz=blz, fints_url=fints_url, login=login,
        pin_encrypted=pin_encrypted, account_id=account_id, iban=iban,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def delete_bank_connection(db: Session, connection_id: int, space_id: int):
    conn = get_bank_connection(db, connection_id, space_id)
    if conn:
        db.delete(conn)
        db.commit()
    return conn


# ---------- Bitvavo-Verbindungen ----------
def get_bitvavo_connections(db: Session, space_id: int):
    return db.query(models.BitvavoConnection).filter(models.BitvavoConnection.space_id == space_id).all()


def get_bitvavo_connection(db: Session, connection_id: int, space_id: int):
    return (
        db.query(models.BitvavoConnection)
        .filter(models.BitvavoConnection.id == connection_id, models.BitvavoConnection.space_id == space_id)
        .first()
    )


def get_all_bitvavo_connections(db: Session):
    return db.query(models.BitvavoConnection).all()


def create_bitvavo_connection(db: Session, space_id: int, name: str, api_key_encrypted: str, api_secret_encrypted: str):
    conn = models.BitvavoConnection(
        space_id=space_id, name=name,
        api_key_encrypted=api_key_encrypted, api_secret_encrypted=api_secret_encrypted,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def delete_bitvavo_connection(db: Session, connection_id: int, space_id: int):
    conn = get_bitvavo_connection(db, connection_id, space_id)
    if conn:
        db.delete(conn)
        db.commit()
    return conn


# ---------- PayPal-Verbindungen ----------
def get_paypal_connections(db: Session, space_id: int):
    return db.query(models.PayPalConnection).filter(models.PayPalConnection.space_id == space_id).all()


def get_paypal_connection(db: Session, connection_id: int, space_id: int):
    return (
        db.query(models.PayPalConnection)
        .filter(models.PayPalConnection.id == connection_id, models.PayPalConnection.space_id == space_id)
        .first()
    )


def get_all_paypal_connections(db: Session):
    return db.query(models.PayPalConnection).all()


def create_paypal_connection(db: Session, space_id: int, account_id: int, name: str, client_id_encrypted: str, client_secret_encrypted: str):
    conn = models.PayPalConnection(
        space_id=space_id, account_id=account_id, name=name,
        client_id_encrypted=client_id_encrypted, client_secret_encrypted=client_secret_encrypted,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def delete_paypal_connection(db: Session, connection_id: int, space_id: int):
    conn = get_paypal_connection(db, connection_id, space_id)
    if conn:
        db.delete(conn)
        db.commit()
    return conn


# ---------- Enable-Banking-Verbindungen ----------
def get_enablebanking_connections(db: Session, space_id: int):
    return db.query(models.EnableBankingConnection).filter(models.EnableBankingConnection.space_id == space_id).all()


def get_enablebanking_connection(db: Session, connection_id: int, space_id: int):
    return (
        db.query(models.EnableBankingConnection)
        .filter(models.EnableBankingConnection.id == connection_id, models.EnableBankingConnection.space_id == space_id)
        .first()
    )


def get_enablebanking_connection_by_state(db: Session, state: str):
    return db.query(models.EnableBankingConnection).filter(models.EnableBankingConnection.state == state).first()


def get_all_enablebanking_connections(db: Session):
    return db.query(models.EnableBankingConnection).all()


def create_enablebanking_connection(db: Session, space_id: int, account_id: int, aspsp_name: str, aspsp_country: str, state: str):
    conn = models.EnableBankingConnection(
        space_id=space_id, account_id=account_id,
        aspsp_name=aspsp_name, aspsp_country=aspsp_country, state=state,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def delete_enablebanking_connection(db: Session, connection_id: int, space_id: int):
    conn = get_enablebanking_connection(db, connection_id, space_id)
    if conn:
        db.delete(conn)
        db.commit()
    return conn


# ---------- eBay-Verbindungen ----------
def get_ebay_connections(db: Session, space_id: int):
    return db.query(models.EbayConnection).filter(models.EbayConnection.space_id == space_id).all()


def get_ebay_connection(db: Session, connection_id: int, space_id: int):
    return (
        db.query(models.EbayConnection)
        .filter(models.EbayConnection.id == connection_id, models.EbayConnection.space_id == space_id)
        .first()
    )


def get_ebay_connection_by_state(db: Session, state: str):
    return db.query(models.EbayConnection).filter(models.EbayConnection.state == state).first()


def get_all_ebay_connections(db: Session):
    return db.query(models.EbayConnection).all()


def create_ebay_connection(db: Session, space_id: int, account_id: int, state: str):
    conn = models.EbayConnection(space_id=space_id, account_id=account_id, state=state)
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def delete_ebay_connection(db: Session, connection_id: int, space_id: int):
    conn = get_ebay_connection(db, connection_id, space_id)
    if conn:
        db.delete(conn)
        db.commit()
    return conn


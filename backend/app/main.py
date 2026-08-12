import base64
import requests
import csv
import io
import json
import os
import random
import re
import shutil
import uuid
import zipfile
from datetime import date, datetime, timedelta
from typing import Optional, List

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, FastAPI, Depends, Form, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse, Response
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

import threading

from . import models, schemas, crud, auth, prices, bank_sync, exchange_sync, enablebanking_sync, paypal_sync, ebay_sync, radicale_sync, ollama_client, tax, document_extract, goals, debts, ai_auto, websearch, notifications, telegram_bot, calls, benchmark, immich, mail_sync, travel_time
from .database import engine, get_db, SessionLocal, DATA_DIR, ensure_columns

models.Base.metadata.create_all(bind=engine)
ensure_columns("settings", {
    "enablebanking_app_id": "VARCHAR",
    "enablebanking_private_key_encrypted": "TEXT",
})
ensure_columns("settings", {
    "enablebanking_redirect_base_url": "VARCHAR",
})
ensure_columns("holdings", {
    "sector": "VARCHAR",
    "country": "VARCHAR",
    "currency": "VARCHAR",
})
ensure_columns("holdings", {
    "next_dividend_notified_for": "DATE",
})
ensure_columns("settings", {
    "ollama_url": "VARCHAR",
    "ollama_model": "VARCHAR",
})
ensure_columns("settings", {
    "sync_hour": "INTEGER DEFAULT 3",
})
ensure_columns("settings", {
    "auto_backup_enabled": "BOOLEAN DEFAULT 1",
    "backup_hour": "INTEGER DEFAULT 2",
    "backup_retention": "INTEGER DEFAULT 14",
    "sparerpauschbetrag": "FLOAT DEFAULT 1000.0",
})
ensure_columns("settings", {
    "beleg_chat_model": "VARCHAR",
})
# goal_triggers gab es schon vor dem Schulden-Modul - neue Spalte nachziehen.
ensure_columns("goal_triggers", {
    "scope_debt_id": "INTEGER",
})
# Zinsbindung, Bereitstellungszinsen und Nebenkosten kamen nach den Kredit-Tabellen dazu.
ensure_columns("debts", {
    "interest_fixed_until": "DATE",
    "follow_up_interest_rate_percent": "FLOAT",
    "commitment_rate_percent": "FLOAT",
    "commitment_free_months": "INTEGER",
    "undisbursed_amount": "FLOAT",
    "upfront_fees": "FLOAT",
    "monthly_fee": "FLOAT",
    "monthly_insurance": "FLOAT",
})
ensure_columns("debt_payments", {
    "fee_amount": "FLOAT",
})
ensure_columns("transactions", {
    "is_transfer": "BOOLEAN DEFAULT 0",
})
ensure_columns("transactions", {
    "categorized_at": "DATETIME",
})
ensure_columns("settings", {
    "last_digest_sent_at": "DATETIME",
    "transfers_marked_since_digest": "INTEGER DEFAULT 0",
})
ensure_columns("settings", {
    "auto_categorize_enabled": "BOOLEAN DEFAULT 1",
})
ensure_columns("accounts", {
    "is_business": "BOOLEAN DEFAULT 0",
})
ensure_columns("accounts", {
    "dispo_alert_sent": "BOOLEAN DEFAULT 0",
})
ensure_columns("settings", {
    "brave_search_api_key_encrypted": "VARCHAR",
})
ensure_columns("settings", {
    "display_currency": "VARCHAR DEFAULT 'EUR'",
})
ensure_columns("settings", {
    "notifications_enabled": "BOOLEAN DEFAULT 1",
    "telegram_bot_token_encrypted": "VARCHAR",
    "telegram_chat_id": "VARCHAR",
    "last_cashflow_alert_date": "DATE",
    "last_budget_alert_month": "VARCHAR",
})
ensure_columns("settings", {
    "telegram_last_update_id": "INTEGER",
})
ensure_columns("settings", {
    "calls_enabled": "BOOLEAN DEFAULT 0",
    "twilio_account_sid": "VARCHAR",
    "twilio_auth_token_encrypted": "VARCHAR",
    "twilio_from_number": "VARCHAR",
    "twilio_to_number": "VARCHAR",
})
ensure_columns("settings", {
    # Nur das Jahr, kein volles Geburtsdatum - für die Zuordnung zu einer
    # Altersgruppe reicht das, und weniger personenbezogene Daten sind besser.
    "birth_year": "INTEGER",
})
ensure_columns("settings", {
    "immich_url": "VARCHAR",
    "immich_api_key_encrypted": "VARCHAR",
})
ensure_columns("settings", {
    "immich_skip_confirm": "BOOLEAN DEFAULT 0",
})
ensure_columns("settings", {
    "immich_quality_scan_page": "INTEGER DEFAULT 1",
})
ensure_columns("settings", {
    "ebay_app_id": "VARCHAR",
    "ebay_cert_id_encrypted": "VARCHAR",
    "ebay_ru_name": "VARCHAR",
})
ensure_columns("settings", {
    "radicale_url": "VARCHAR",
    "radicale_username": "VARCHAR",
    "radicale_password_encrypted": "VARCHAR",
    "radicale_calendar_url": "VARCHAR",
})
ensure_columns("settings", {
    "home_address": "VARCHAR",
    "home_lat": "FLOAT",
    "home_lon": "FLOAT",
    "openroute_api_key_encrypted": "VARCHAR",
})
ensure_columns("calendar_events", {
    "lat": "FLOAT",
    "lon": "FLOAT",
})
ensure_columns("todos", {
    "completed_at": "DATETIME",
})
ensure_columns("settings", {
    "mail_enabled": "BOOLEAN DEFAULT 0",
    "imap_host": "VARCHAR",
    "imap_port": "INTEGER DEFAULT 993",
    "imap_user": "VARCHAR",
    "imap_password_encrypted": "VARCHAR",
    "imap_folder": "VARCHAR DEFAULT 'INBOX'",
    "mail_last_sync_at": "DATETIME",
    "creditcard_mail_sender": "VARCHAR",
    "creditcard_account_id": "INTEGER",
    "creditcard_debt_id": "INTEGER",
})
ensure_columns("trips", {
    "budget": "FLOAT",
})
ensure_columns("creditcard_bills", {
    "debt_id": "INTEGER",
})
ensure_columns("account_balance_log", {
    "debt_id": "INTEGER",
})

_bootstrap_db = SessionLocal()
_settings = auth.get_or_create_settings(_bootstrap_db)
SECRET_KEY = _settings.secret_key
INITIAL_SYNC_HOUR = _settings.sync_hour
INITIAL_BACKUP_HOUR = _settings.backup_hour
if not _bootstrap_db.query(models.Space).first():
    _bootstrap_db.add(models.Space(name="Privat", icon="🏠"))
    _bootstrap_db.commit()

# Basiszins-Werte (BMF-Veröffentlichung) für die Vorabpauschale-Berechnung - einmalig
# mit den bekannten Werten vorbelegt, über die Steuer-Ansicht jedes Jahr erweiterbar.
for _year, _rate in ((2025, 2.53), (2026, 3.20)):
    if not _bootstrap_db.query(models.BasiszinsRate).filter_by(year=_year).first():
        _bootstrap_db.add(models.BasiszinsRate(year=_year, rate_percent=_rate))
_bootstrap_db.commit()

# Bestehende Positionen aus der Zeit vor dem Lot-Ledger bekommen rückwirkend ein
# einzelnes Kauf-Lot, das ihre bisherigen quantity/purchase_price/purchase_date
# widerspiegelt - damit sie in der Kaufhistorie/den Charts auftauchen.
for _h in _bootstrap_db.query(models.Holding).all():
    if not _h.lots and _h.quantity:
        _bootstrap_db.add(models.HoldingLot(
            holding_id=_h.id,
            date=_h.purchase_date or date.today(),
            type=models.LotType.kauf,
            quantity=_h.quantity,
            price_per_unit=_h.purchase_price,
        ))
_bootstrap_db.commit()
_bootstrap_db.close()

app = FastAPI(title="Kies", version="1.0.0")

UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

if os.environ.get("DEV_NO_CACHE"):
    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


# style.css/app.js bekommen ohne eigenes Cache-Control nur Starlettes
# heuristisches Browser-Caching (ueber Last-Modified) - gerade bei der als PWA
# installierten App (eigener Service Worker, siehe sw.js) hat das live dazu
# gefuehrt, dass ein Geraet nach einem Deploy tagelang eine veraltete CSS-
# Fassung ausgeliefert bekam (fehlende Icon-Styles wirkten wie ein Bug, waren
# aber nur ein Cache-Stand von vor dem Fix). "no-cache" (nicht "no-store")
# erlaubt Caching weiterhin, erzwingt aber immer eine ETag-Revalidierung beim
# Server - im Regelfall ein guenstiges 304, aber garantiert nie unbemerkt
# veraltet.
@app.middleware("http")
async def no_cache_static_shell(request, call_next):
    response = await call_next(request)
    if request.url.path in ("/style.css", "/app.js", "/sw.js"):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="finance_session",
    same_site="lax",
    max_age=60 * 60 * 24 * 30,
)

api_router = APIRouter(prefix="/api")


# ---------------- Profil ----------------
@api_router.get("/auth/profile", response_model=schemas.ProfileOut)
def get_profile(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.ProfileOut(display_name=settings.display_name)


@api_router.put("/auth/profile", response_model=schemas.ProfileOut)
def update_profile(data: schemas.ProfileUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.display_name = data.display_name
    db.commit()
    return schemas.ProfileOut(display_name=settings.display_name)


# ---------------- Spaces (Bereiche) ----------------
@api_router.get("/spaces", response_model=List[schemas.SpaceOut])
def list_spaces(db: Session = Depends(get_db)):
    return crud.get_spaces(db)


@api_router.post("/spaces", response_model=schemas.SpaceOut)
def create_space(data: schemas.SpaceCreate, db: Session = Depends(get_db)):
    return crud.create_space(db, data)


@api_router.delete("/spaces/{space_id}")
def remove_space(space_id: int, request: Request, db: Session = Depends(get_db)):
    space = crud.delete_space(db, space_id)
    if not space:
        raise HTTPException(404, "Bereich nicht gefunden")
    if request.session.get("space_id") == space_id:
        request.session.pop("space_id", None)
    return {"ok": True}


@api_router.post("/spaces/{space_id}/select", response_model=schemas.SpaceOut)
def select_space(space_id: int, request: Request, db: Session = Depends(get_db)):
    space = crud.get_space(db, space_id)
    if not space:
        raise HTTPException(404, "Bereich nicht gefunden")
    request.session["space_id"] = space_id
    return space


@api_router.get("/spaces/current")
def current_space(request: Request, db: Session = Depends(get_db)):
    space_id = request.session.get("space_id")
    if not space_id:
        # Gibt es nur einen Bereich, automatisch übernehmen - siehe
        # auth.get_active_space_id für die Begründung. Ohne das würde die
        # Bereichsauswahl beim ersten Laden trotzdem kurz aufblitzen.
        spaces = crud.get_spaces(db)
        if len(spaces) == 1:
            space_id = spaces[0].id
            request.session["space_id"] = space_id
        else:
            return None
    space = crud.get_space(db, space_id)
    if not space:
        request.session.pop("space_id", None)
        return None
    return schemas.SpaceOut.model_validate(space)


# ---------------- Accounts ----------------
@api_router.get("/accounts", response_model=List[schemas.AccountOut])
def list_accounts(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    accounts = crud.get_accounts(db, space_id)
    result = []
    for acc in accounts:
        bal = crud.account_balance(db, acc)
        result.append(
            schemas.AccountOut(
                id=acc.id, name=acc.name, type=acc.type,
                initial_balance=acc.initial_balance, is_business=acc.is_business,
                created_at=acc.created_at, current_balance=bal,
            )
        )
    return result


@api_router.post("/accounts", response_model=schemas.AccountOut)
def create_account(account: schemas.AccountCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    acc = crud.create_account(db, account, space_id)
    return schemas.AccountOut(
        id=acc.id, name=acc.name, type=acc.type,
        initial_balance=acc.initial_balance, is_business=acc.is_business,
        created_at=acc.created_at, current_balance=acc.initial_balance,
    )


@api_router.put("/accounts/{account_id}", response_model=schemas.AccountOut)
def update_account(account_id: int, data: schemas.AccountUpdate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    acc = crud.update_account(db, account_id, space_id, data)
    if not acc:
        raise HTTPException(404, "Konto nicht gefunden")
    bal = crud.account_balance(db, acc)
    return schemas.AccountOut(
        id=acc.id, name=acc.name, type=acc.type,
        initial_balance=acc.initial_balance, is_business=acc.is_business,
        created_at=acc.created_at, current_balance=bal,
    )


@api_router.delete("/accounts/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    acc = crud.delete_account(db, account_id, space_id)
    if not acc:
        raise HTTPException(404, "Konto nicht gefunden")
    return {"ok": True}


@api_router.get("/accounts/balance-log", response_model=List[schemas.AccountBalanceLogOut])
def get_balance_log(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.recent_balance_changes(db, space_id)


# ---------------- Categories (global) ----------------
@api_router.get("/categories", response_model=List[schemas.CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return crud.get_categories(db)


@api_router.get("/categories/totals")
def get_category_totals(year: int = date.today().year, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.category_totals(db, space_id, year)


@api_router.post("/categories", response_model=schemas.CategoryOut)
def create_category(category: schemas.CategoryCreate, db: Session = Depends(get_db)):
    return crud.create_category(db, category)


@api_router.put("/categories/{category_id}", response_model=schemas.CategoryOut)
def update_category(category_id: int, data: schemas.CategoryUpdate, db: Session = Depends(get_db)):
    cat = crud.update_category(db, category_id, data)
    if not cat:
        raise HTTPException(404, "Kategorie nicht gefunden")
    return cat


@api_router.delete("/categories/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db)):
    cat = crud.delete_category(db, category_id)
    if not cat:
        raise HTTPException(404, "Kategorie nicht gefunden")
    return {"ok": True}


# ---------------- Trips (Urlaube) ----------------
@api_router.get("/trips", response_model=List[schemas.TripOut])
def list_trips(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    trips = crud.get_trips(db, space_id)
    return [crud.trip_summary(db, t) for t in trips]


@api_router.post("/trips", response_model=schemas.TripOut)
def create_trip(data: schemas.TripCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    trip = crud.create_trip(db, data, space_id)
    return crud.trip_summary(db, trip)


@api_router.put("/trips/{trip_id}", response_model=schemas.TripOut)
def update_trip(trip_id: int, data: schemas.TripUpdate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    trip = crud.update_trip(db, trip_id, space_id, data)
    if not trip:
        raise HTTPException(404, "Trip nicht gefunden")
    return crud.trip_summary(db, trip)


@api_router.delete("/trips/{trip_id}")
def delete_trip(trip_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    trip = crud.delete_trip(db, trip_id, space_id)
    if not trip:
        raise HTTPException(404, "Trip nicht gefunden")
    return {"ok": True}


# ---------------- Budgets ----------------
@api_router.get("/budgets", response_model=List[schemas.BudgetOut])
def list_budgets(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    budgets = crud.get_budgets(db, space_id)
    return [
        schemas.BudgetOut(
            id=b.id, category_id=b.category_id,
            category_name=b.category.name if b.category else "Unbekannt",
            monthly_limit=b.monthly_limit,
        )
        for b in budgets
    ]


@api_router.get("/budgets/suggestions", response_model=List[schemas.BudgetSuggestionOut])
def get_budget_suggestions(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.suggest_budgets(db, space_id)


@api_router.post("/budgets", response_model=schemas.BudgetOut)
def save_budget(data: schemas.BudgetCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if not crud.get_category(db, data.category_id):
        raise HTTPException(400, "Kategorie existiert nicht")
    b = crud.upsert_budget(db, space_id, data)
    return schemas.BudgetOut(
        id=b.id, category_id=b.category_id,
        category_name=b.category.name if b.category else "Unbekannt",
        monthly_limit=b.monthly_limit,
    )


@api_router.delete("/budgets/{category_id}")
def remove_budget(category_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    b = crud.delete_budget(db, space_id, category_id)
    if not b:
        raise HTTPException(404, "Budget nicht gefunden")
    return {"ok": True}


# ---------------- Transactions ----------------
@api_router.get("/transactions", response_model=List[schemas.TransactionOut])
def list_transactions(
    account_id: Optional[int] = None,
    category_id: Optional[int] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    search: Optional[str] = None,
    trip_id: Optional[int] = None,
    hide_transfers: bool = False,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    return crud.get_transactions(db, space_id, account_id, category_id, year, month, search, trip_id, hide_transfers)


@api_router.get("/transactions/recurring", response_model=List[schemas.RecurringPaymentOut])
def get_recurring_transactions(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.detect_recurring_transactions(db, space_id)


@api_router.get("/transactions/price-increases", response_model=List[schemas.PriceIncreaseOut])
def get_price_increases(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.detect_price_increases(db, space_id)


@api_router.get("/transactions/spending-anomalies", response_model=List[schemas.SpendingAnomalyOut])
def get_spending_anomalies(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.detect_spending_anomalies(db, space_id)


@api_router.get("/transactions/overlapping-contracts", response_model=List[schemas.OverlappingContractGroupOut])
def get_overlapping_contracts(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.detect_overlapping_contracts(db, space_id)


@api_router.get("/transactions/duplicates", response_model=List[schemas.DuplicateTransactionGroup])
def get_duplicate_transactions(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.find_duplicate_transactions(db, space_id)


@api_router.get("/contract-reminders", response_model=List[schemas.ContractReminderOut])
def list_contract_reminders(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.get_contract_reminders(db, space_id)


@api_router.post("/contract-reminders", response_model=schemas.ContractReminderOut)
def add_contract_reminder(
    data: schemas.ContractReminderCreate,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    try:
        return crud.create_contract_reminder(db, space_id, data)
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Für dieses Abo ist schon eine Kündigungsfrist hinterlegt.")


@api_router.put("/contract-reminders/{reminder_id}", response_model=schemas.ContractReminderOut)
def edit_contract_reminder(
    reminder_id: int,
    data: schemas.ContractReminderUpdate,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    result = crud.update_contract_reminder(db, reminder_id, space_id, data)
    if not result:
        raise HTTPException(404, "Erinnerung nicht gefunden.")
    return result


@api_router.delete("/contract-reminders/{reminder_id}")
def remove_contract_reminder(
    reminder_id: int,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    if not crud.delete_contract_reminder(db, reminder_id, space_id):
        raise HTTPException(404, "Erinnerung nicht gefunden.")
    return {"ok": True}


@api_router.get("/return-deadlines", response_model=List[schemas.ReturnDeadlineOut])
def list_return_deadlines(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.get_return_deadlines(db, space_id)


@api_router.post("/return-deadlines", response_model=schemas.ReturnDeadlineOut)
def add_return_deadline(
    data: schemas.ReturnDeadlineCreate,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    try:
        result = crud.create_return_deadline(db, space_id, data)
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Für diese Buchung ist schon eine Rückgabefrist hinterlegt.")
    if not result:
        raise HTTPException(404, "Buchung nicht gefunden.")
    return result


@api_router.put("/return-deadlines/{deadline_id}", response_model=schemas.ReturnDeadlineOut)
def edit_return_deadline(
    deadline_id: int,
    data: schemas.ReturnDeadlineUpdate,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    result = crud.update_return_deadline(db, deadline_id, space_id, data)
    if not result:
        raise HTTPException(404, "Rückgabefrist nicht gefunden.")
    return result


@api_router.delete("/return-deadlines/{deadline_id}")
def remove_return_deadline(
    deadline_id: int,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    if not crud.delete_return_deadline(db, deadline_id, space_id):
        raise HTTPException(404, "Rückgabefrist nicht gefunden.")
    return {"ok": True}


@api_router.get("/forecast/cashflow", response_model=schemas.CashflowForecastOut)
def get_cashflow_forecast(days: int = 90, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    days = max(7, min(days, 365))
    return crud.cashflow_forecast(db, space_id, days)


@api_router.post("/transactions", response_model=schemas.TransactionOut)
def create_transaction(transaction: schemas.TransactionCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if not crud.get_account(db, transaction.account_id, space_id):
        raise HTTPException(400, "Konto existiert nicht")
    return crud.create_transaction(db, transaction)


@api_router.put("/transactions/{transaction_id}", response_model=schemas.TransactionOut)
def update_transaction(transaction_id: int, data: schemas.TransactionUpdate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    tx = crud.update_transaction(db, transaction_id, space_id, data)
    if not tx:
        raise HTTPException(404, "Buchung nicht gefunden")
    return tx


@api_router.delete("/transactions/{transaction_id}")
def delete_transaction(transaction_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    tx = crud.delete_transaction(db, transaction_id, space_id)
    if not tx:
        raise HTTPException(404, "Buchung nicht gefunden")
    if tx.receipt_filename:
        path = os.path.join(UPLOAD_DIR, tx.receipt_filename)
        if os.path.exists(path):
            os.remove(path)
    return {"ok": True}


@api_router.post("/transactions/bulk-categorize")
def bulk_categorize_transactions(data: schemas.BulkCategorizeRequest, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if not data.transaction_ids:
        raise HTTPException(400, "Keine Buchungen ausgewählt.")
    count = crud.bulk_set_category(db, space_id, data.transaction_ids, data.category_id)
    return {"updated": count}


# Erlaubte Beleg-Endungen. Der Original-Dateiname kommt ungeprüft vom Client -
# ohne diese Schranke könnte eine präparierte Endung (z.B. mit enthaltenen
# "/") beim Zusammensetzen des Pfads aus UPLOAD_DIR herausführen
# (GitHub-Code-Scanning: py/path-injection).
RECEIPT_ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"}


@api_router.post("/transactions/{transaction_id}/receipt", response_model=schemas.TransactionOut)
def upload_receipt(transaction_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    tx = crud.get_transaction(db, transaction_id, space_id)
    if not tx:
        raise HTTPException(404, "Buchung nicht gefunden")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in RECEIPT_ALLOWED_EXTENSIONS:
        raise HTTPException(400, "Nicht unterstütztes Dateiformat. Erlaubt: PDF, JPG, PNG, HEIC, WEBP, GIF.")
    # Der Dateiname besteht komplett aus selbst erzeugten Teilen (ID, Zufalls-
    # hex, geprüfte Endung) - der ungeprüfte Original-Dateiname fließt nirgends
    # mehr roh in den Pfad ein.
    safe_name = f"{transaction_id}_{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(UPLOAD_DIR, safe_name)

    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # alten Beleg löschen, falls vorhanden
    if tx.receipt_filename:
        old_path = os.path.join(UPLOAD_DIR, tx.receipt_filename)
        if os.path.exists(old_path):
            os.remove(old_path)

    return crud.set_receipt(db, transaction_id, space_id, safe_name)


@api_router.get("/receipts/{filename}")
def get_receipt(filename: str):
    # os.path.basename() entfernt jeden Verzeichnisanteil (z.B. "../../etc/x")
    # - ohne das ließe sich über den Pfad aus UPLOAD_DIR herauslesen
    # (GitHub-Code-Scanning: py/path-injection). Zusätzlich wird der
    # aufgelöste Pfad auf Zugehörigkeit zu UPLOAD_DIR geprüft, als zweite,
    # von der ersten unabhängige Absicherung.
    safe_name = os.path.basename(filename)
    path = os.path.realpath(os.path.join(UPLOAD_DIR, safe_name))
    if not path.startswith(os.path.realpath(UPLOAD_DIR) + os.sep):
        raise HTTPException(404, "Beleg nicht gefunden")
    if not os.path.exists(path):
        raise HTTPException(404, "Beleg nicht gefunden")
    return FileResponse(path)


@api_router.delete("/transactions/{transaction_id}/receipt")
def delete_receipt(transaction_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    tx = crud.get_transaction(db, transaction_id, space_id)
    if not tx:
        raise HTTPException(404, "Buchung nicht gefunden")
    if tx.receipt_filename:
        path = os.path.join(UPLOAD_DIR, tx.receipt_filename)
        if os.path.exists(path):
            os.remove(path)
        crud.set_receipt(db, transaction_id, space_id, None)
    return {"ok": True}


# ---------------- Holdings (Investments) ----------------
@api_router.get("/holdings", response_model=List[schemas.HoldingOut])
def list_holdings(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return [crud.holding_out(h) for h in crud.get_holdings(db, space_id)]


@api_router.post("/holdings", response_model=schemas.HoldingOut)
def create_holding(data: schemas.HoldingCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    h = crud.create_holding(db, data, space_id)
    if h.asset_type in (models.AssetType.aktie, models.AssetType.etf):
        try:
            profile = prices.fetch_profile(h.symbol)
            h.sector = h.sector or profile["sector"]
            h.country = profile["country"]
            h.currency = profile["currency"]
            db.commit()
            db.refresh(h)
        except Exception:
            pass
    return crud.holding_out(h)


@api_router.put("/holdings/{holding_id}", response_model=schemas.HoldingOut)
def update_holding(holding_id: int, data: schemas.HoldingUpdate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    h = crud.update_holding(db, holding_id, space_id, data)
    if not h:
        raise HTTPException(404, "Position nicht gefunden")
    return crud.holding_out(h)


@api_router.delete("/holdings/{holding_id}")
def delete_holding(holding_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    h = crud.delete_holding(db, holding_id, space_id)
    if not h:
        raise HTTPException(404, "Position nicht gefunden")
    return {"ok": True}


@api_router.post("/holdings/refresh-prices", response_model=schemas.PriceRefreshResult)
def refresh_prices(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    holdings = crud.get_holdings(db, space_id)
    updated = 0
    failed: list[str] = []
    for h in holdings:
        try:
            h.current_price = prices.fetch_price_eur(h.asset_type.value, h.symbol)
            h.price_updated_at = datetime.utcnow()
            updated += 1
        except Exception as e:
            failed.append(f"{h.name} ({h.symbol}): {e}")
    db.commit()
    return schemas.PriceRefreshResult(
        updated=updated,
        failed=failed,
        holdings=[crud.holding_out(h) for h in crud.get_holdings(db, space_id)],
    )


@api_router.get("/net-worth", response_model=schemas.NetWorthOut)
def get_net_worth(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.net_worth(db, space_id)


@api_router.get("/net-worth/history", response_model=schemas.NetWorthHistoryOut)
def get_net_worth_history(days: int = 365, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    """Echte Vermoegens-Historie aus taeglichen Snapshots (siehe
    _scheduled_net_worth_snapshot) - waechst erst ab dem Tag, an dem dieser
    Job zum ersten Mal lief, keine rueckwirkende Rekonstruktion."""
    days = max(1, min(days, 1825))
    snapshots = crud.net_worth_history(db, space_id, days)
    return schemas.NetWorthHistoryOut(points=[
        schemas.NetWorthHistoryPoint(
            date=s.date, accounts_total=s.accounts_total, investments_total=s.investments_total,
            debts_total=s.debts_total, total=s.total,
        ) for s in snapshots
    ])


@api_router.put("/settings/birth-year", response_model=schemas.BirthYearUpdate)
def update_birth_year(data: schemas.BirthYearUpdate, db: Session = Depends(get_db)):
    if data.birth_year is not None:
        heute = date.today().year
        # Grob plausibel halten - ein Tippfehler wie 19985 wuerde sonst zu einer
        # unsinnigen Altersgruppe fuehren.
        if not (heute - 120 <= data.birth_year <= heute):
            raise HTTPException(400, "Bitte ein Geburtsjahr zwischen 1906 und heute angeben.")
    s = auth.get_or_create_settings(db)
    s.birth_year = data.birth_year
    db.commit()
    return schemas.BirthYearUpdate(birth_year=s.birth_year)


@api_router.get("/benchmark", response_model=schemas.BenchmarkOut)
def get_benchmark(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    """Ordnet das eigene Nettovermögen in die eigene Altersgruppe ein."""
    s = auth.get_or_create_settings(db)
    nw = crud.net_worth(db, space_id)
    total = nw["total"] if isinstance(nw, dict) else nw.total

    own = benchmark.bracket_for_age(
        benchmark.age_from_birth_year(s.birth_year)) if s.birth_year else None

    def to_schema(b, is_own):
        return schemas.BenchmarkBracket(
            key=b.key, label=b.label, p10=b.p10, p50=b.p50, p90=b.p90, is_own=is_own,
        )

    out = schemas.BenchmarkOut(
        configured=bool(s.birth_year),
        birth_year=s.birth_year,
        net_worth=total,
        brackets=[to_schema(b, own is not None and b.key == own.key)
                  for b in benchmark.BRACKETS],
        overall=to_schema(benchmark.GESAMT, False),
        source=benchmark.QUELLE,
        source_url=benchmark.QUELLE_URL,
        data_year=benchmark.DATENJAHR,
    )
    if own:
        pct, exact = benchmark.estimate_percentile(total, own)
        out.age = benchmark.age_from_birth_year(s.birth_year)
        out.own_bracket = own.key
        out.percentile = round(pct, 1)
        out.percentile_exact = exact
        out.verdict = benchmark.verdict(total, own)
    return out


# ---------------- Schulden ----------------
def _debt_out(db: Session, debt: models.Debt, with_projection: bool = False) -> schemas.DebtOut:
    out = schemas.DebtOut.model_validate(debt)
    out.account_name = debt.account.name if debt.account else None
    out.payment_count = len(debt.payments)
    out.total_interest_paid = debts.total_interest_paid(debt)
    out.total_fees_paid = debts.total_fees_paid(debt)
    out.monthly_total_burden = round((debt.monthly_payment or 0.0) + debts.monthly_side_costs(debt), 2)
    out.monthly_commitment_interest = debts.monthly_commitment_interest(debt)
    paid_off = round(debt.original_amount - max(0.0, debt.current_balance), 2)
    out.paid_off_amount = paid_off
    out.paid_off_percent = round(paid_off / debt.original_amount * 100, 1) if debt.original_amount else 0.0
    if with_projection:
        rows, note = debts.projection(debt)
        out.projection_note = note
        out.balance_at_fixed_interest_end = debts.balance_at_fixed_interest_end(debt)
        if rows:
            out.projected_end_date = rows[-1].date
            out.projected_remaining_interest = round(sum(r.interest for r in rows), 2)
            out.projected_remaining_fees = round(sum(r.fee for r in rows), 2)
    return out


@api_router.get("/debts", response_model=List[schemas.DebtOut])
def list_debts(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return [_debt_out(db, d) for d in crud.get_debts(db, space_id)]


@api_router.get("/debts/summary", response_model=schemas.DebtSummaryOut)
def get_debt_summary(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.debt_summary(db, space_id)


@api_router.get("/debts/{debt_id}", response_model=schemas.DebtOut)
def get_debt(debt_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    debt = crud.get_debt(db, debt_id, space_id)
    if not debt:
        raise HTTPException(404, "Kredit nicht gefunden")
    return _debt_out(db, debt, with_projection=True)


@api_router.post("/debts", response_model=schemas.DebtOut)
def create_debt(data: schemas.DebtCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if data.original_amount <= 0:
        raise HTTPException(400, "Der Kreditbetrag muss größer als 0 sein")
    if data.account_id and not crud.get_account(db, data.account_id, space_id):
        raise HTTPException(400, "Das gewählte Konto existiert nicht in diesem Bereich")
    return _debt_out(db, crud.create_debt(db, data, space_id))


@api_router.put("/debts/{debt_id}", response_model=schemas.DebtOut)
def update_debt(debt_id: int, data: schemas.DebtUpdate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if data.account_id and not crud.get_account(db, data.account_id, space_id):
        raise HTTPException(400, "Das gewählte Konto existiert nicht in diesem Bereich")
    debt = crud.update_debt(db, debt_id, space_id, data)
    if not debt:
        raise HTTPException(404, "Kredit nicht gefunden")
    return _debt_out(db, debt, with_projection=True)


@api_router.delete("/debts/{debt_id}")
def delete_debt(debt_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if not crud.delete_debt(db, debt_id, space_id):
        raise HTTPException(404, "Kredit nicht gefunden")
    return {"ok": True}


@api_router.get("/debts/{debt_id}/payments", response_model=List[schemas.DebtPaymentOut])
def list_debt_payments(debt_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    debt = crud.get_debt(db, debt_id, space_id)
    if not debt:
        raise HTTPException(404, "Kredit nicht gefunden")
    by_id = {p.id: p for p in debt.payments}
    return [
        schemas.DebtPaymentOut(
            id=r.payment_id, date=r.date, total_amount=r.total_amount,
            interest_amount=r.interest_amount, fee_amount=r.fee_amount,
            principal_amount=r.principal_amount,
            balance_after=r.balance_after, is_extra_repayment=r.is_extra_repayment,
            interest_is_manual=r.interest_is_manual,
            transaction_id=by_id[r.payment_id].transaction_id,
            notes=by_id[r.payment_id].notes,
        )
        for r in debts.payment_breakdown(debt)
    ]


@api_router.post("/debts/{debt_id}/payments", response_model=schemas.DebtPaymentOut)
def create_debt_payment(debt_id: int, data: schemas.DebtPaymentCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if data.transaction_id and not crud.get_transaction(db, data.transaction_id, space_id):
        raise HTTPException(400, "Die verknüpfte Buchung existiert nicht in diesem Bereich")
    payment = crud.create_debt_payment(db, debt_id, space_id, data)
    if not payment:
        raise HTTPException(404, "Kredit nicht gefunden")
    return _payment_out(db, debt_id, space_id, payment.id)


@api_router.put("/debts/{debt_id}/payments/{payment_id}", response_model=schemas.DebtPaymentOut)
def update_debt_payment(debt_id: int, payment_id: int, data: schemas.DebtPaymentUpdate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if data.transaction_id and not crud.get_transaction(db, data.transaction_id, space_id):
        raise HTTPException(400, "Die verknüpfte Buchung existiert nicht in diesem Bereich")
    if not crud.update_debt_payment(db, payment_id, debt_id, space_id, data):
        raise HTTPException(404, "Zahlung nicht gefunden")
    return _payment_out(db, debt_id, space_id, payment_id)


@api_router.delete("/debts/{debt_id}/payments/{payment_id}")
def delete_debt_payment(debt_id: int, payment_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if not crud.delete_debt_payment(db, payment_id, debt_id, space_id):
        raise HTTPException(404, "Zahlung nicht gefunden")
    return {"ok": True}


def _payment_out(db: Session, debt_id: int, space_id: int, payment_id: int) -> schemas.DebtPaymentOut:
    """Nach jeder Änderung wird die ganze Kette neu aufgeteilt - deshalb kommt die
    Antwort aus dem frisch gerechneten Verlauf und nicht aus dem ORM-Objekt."""
    debt = crud.get_debt(db, debt_id, space_id)
    row = next(r for r in debts.payment_breakdown(debt) if r.payment_id == payment_id)
    payment = next(p for p in debt.payments if p.id == payment_id)
    return schemas.DebtPaymentOut(
        id=row.payment_id, date=row.date, total_amount=row.total_amount,
        interest_amount=row.interest_amount, fee_amount=row.fee_amount,
        principal_amount=row.principal_amount,
        balance_after=row.balance_after, is_extra_repayment=row.is_extra_repayment,
        interest_is_manual=row.interest_is_manual,
        transaction_id=payment.transaction_id, notes=payment.notes,
    )


@api_router.get("/debts/{debt_id}/schedule", response_model=schemas.DebtScheduleOut)
def get_debt_schedule(debt_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    debt = crud.get_debt(db, debt_id, space_id)
    if not debt:
        raise HTTPException(404, "Kredit nicht gefunden")
    rows, note = debts.projection(debt)
    return schemas.DebtScheduleOut(
        rows=[schemas.DebtScheduleRow(**r._asdict()) for r in rows],
        note=note,
        total_interest=round(sum(r.interest for r in rows), 2),
        total_fees=round(sum(r.fee for r in rows), 2),
        end_date=rows[-1].date if rows else None,
    )


# ---------------- Ziele ----------------
def _goal_out(db: Session, goal: models.Goal, evaluate: bool = True) -> schemas.GoalOut:
    """Baut die Ausgabe eines Ziels und rechnet bei auto_financial den Stand live
    (analog net_worth/budget_progress) - so ist der Fortschritt sofort aktuell und
    nicht erst nach dem nächtlichen Job."""
    out = schemas.GoalOut.model_validate(goal)
    out.predecessor_title = goal.predecessor.title if goal.predecessor else None
    if goal.goal_type != models.GoalType.auto_financial or not goal.trigger:
        return out

    result = goals.evaluate_goal(db, goal) if evaluate else goals.evaluate_metric(db, goal)
    out.status = goal.status
    out.completed_at = goal.completed_at
    out.completion_seen = goal.completion_seen
    out.metric_label = result.label
    out.value_unit = result.unit
    out.target_value = result.threshold
    out.evaluation_error = result.error
    if result.value is not None:
        out.current_value = result.value
        out.progress_percent = goals.progress_percent(result.value, result.threshold, result.comparison)
    return out


@api_router.get("/goals", response_model=List[schemas.GoalOut])
def list_goals(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    result = [_goal_out(db, g) for g in crud.get_goals(db, space_id)]
    db.commit()  # evtl. automatisch erreichte Ziele festschreiben
    return result


@api_router.post("/goals", response_model=schemas.GoalOut)
def create_goal(data: schemas.GoalCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if data.goal_type == models.GoalType.auto_financial and data.trigger is None:
        raise HTTPException(400, "Für ein automatisch messbares Ziel wird eine Auswertungsregel benötigt")
    if data.predecessor_goal_id and not crud.get_goal(db, data.predecessor_goal_id, space_id):
        raise HTTPException(400, "Das gewählte Vorgänger-Ziel existiert nicht")
    goal = crud.create_goal(db, data, space_id)
    out = _goal_out(db, goal)
    db.commit()
    return out


@api_router.put("/goals/{goal_id}", response_model=schemas.GoalOut)
def update_goal(goal_id: int, data: schemas.GoalUpdate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if data.predecessor_goal_id:
        if data.predecessor_goal_id == goal_id:
            raise HTTPException(400, "Ein Ziel kann nicht sein eigener Vorgänger sein")
        if not crud.get_goal(db, data.predecessor_goal_id, space_id):
            raise HTTPException(400, "Das gewählte Vorgänger-Ziel existiert nicht")
    goal = crud.update_goal(db, goal_id, space_id, data)
    if not goal:
        raise HTTPException(404, "Ziel nicht gefunden")
    out = _goal_out(db, goal)
    db.commit()
    return out


@api_router.delete("/goals/{goal_id}")
def delete_goal(goal_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if not crud.delete_goal(db, goal_id, space_id):
        raise HTTPException(404, "Ziel nicht gefunden")
    return {"ok": True}


@api_router.post("/goals/{goal_id}/complete", response_model=schemas.GoalCompleteResult)
def complete_goal(goal_id: int, completed: bool = True, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    goal = crud.get_goal(db, goal_id, space_id)
    if not goal:
        raise HTTPException(404, "Ziel nicht gefunden")
    if goal.goal_type == models.GoalType.auto_financial:
        raise HTTPException(400, "Automatisch messbare Ziele werden nicht von Hand abgehakt")
    crud.set_goal_completed(db, goal, completed)
    return schemas.GoalCompleteResult(
        ok=True,
        goal=_goal_out(db, goal, evaluate=False),
        message="Ziel abgehakt." if completed else "Ziel wieder geöffnet.",
    )


@api_router.post("/goals/mark-seen")
def mark_goals_seen(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return {"ok": True, "marked": crud.mark_goals_seen(db, space_id)}


@api_router.get("/goals/{goal_id}/progress", response_model=List[schemas.GoalProgressPoint])
def goal_progress(goal_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if not crud.get_goal(db, goal_id, space_id):
        raise HTTPException(404, "Ziel nicht gefunden")
    return crud.get_goal_progress_points(db, goal_id)


# ---------------- Holding-Lots (einzelne Käufe/Verkäufe) ----------------
@api_router.get("/holdings/{holding_id}/lots", response_model=List[schemas.HoldingLotOut])
def list_lots(holding_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    lots = crud.get_lots(db, holding_id, space_id)
    if lots is None:
        raise HTTPException(404, "Position nicht gefunden")
    return lots


@api_router.post("/holdings/{holding_id}/lots", response_model=schemas.HoldingLotOut)
def create_lot(holding_id: int, data: schemas.HoldingLotCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    lot = crud.create_lot(db, holding_id, space_id, data)
    if not lot:
        raise HTTPException(404, "Position nicht gefunden")
    return lot


@api_router.put("/holdings/{holding_id}/lots/{lot_id}", response_model=schemas.HoldingLotOut)
def update_lot(holding_id: int, lot_id: int, data: schemas.HoldingLotUpdate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    lot = crud.update_lot(db, lot_id, holding_id, space_id, data)
    if not lot:
        raise HTTPException(404, "Kauf/Verkauf nicht gefunden")
    return lot


@api_router.delete("/holdings/{holding_id}/lots/{lot_id}")
def delete_lot(holding_id: int, lot_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    lot = crud.delete_lot(db, lot_id, holding_id, space_id)
    if not lot:
        raise HTTPException(404, "Kauf/Verkauf nicht gefunden")
    return {"ok": True}


# ---------------- Kurshistorie & Portfolio-Verlauf ----------------
@api_router.get("/holdings/{holding_id}/history", response_model=schemas.HoldingHistoryOut)
def get_holding_history(holding_id: int, range: str = "1y", db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    try:
        result = crud.holding_history(db, holding_id, space_id, range)
    except Exception as e:
        raise HTTPException(400, f"Kurshistorie konnte nicht geladen werden: {e}")
    if result is None:
        raise HTTPException(404, "Position nicht gefunden")
    return result


@api_router.get("/portfolio/history", response_model=schemas.PortfolioHistoryOut)
def get_portfolio_history(range: str = "1y", db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.portfolio_history(db, space_id, range)


@api_router.get("/portfolio/diversification", response_model=schemas.DiversificationOut)
def get_portfolio_diversification(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.portfolio_diversification(db, space_id)


@api_router.get("/portfolio/volatility", response_model=schemas.VolatilityOut)
def get_portfolio_volatility(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.portfolio_volatility(db, space_id)


@api_router.get("/portfolio/dividends", response_model=schemas.PortfolioDividendsOut)
def get_portfolio_dividends(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.portfolio_dividends(db, space_id)


@api_router.get("/portfolio/dividends/upcoming", response_model=List[schemas.UpcomingDividendOut])
def get_upcoming_dividends(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.estimate_next_dividends(db, space_id)


# ---------------- Steuer (Vorabpauschale / realisierte Gewinne) ----------------
# Näherungsweise Berechnung zur Orientierung, keine Steuerberatung - siehe tax.py.
@api_router.get("/tax/basiszins", response_model=List[schemas.BasiszinsRateOut])
def list_basiszins(db: Session = Depends(get_db)):
    return db.query(models.BasiszinsRate).order_by(models.BasiszinsRate.year).all()


@api_router.put("/tax/basiszins", response_model=schemas.BasiszinsRateOut)
def upsert_basiszins(data: schemas.BasiszinsRateUpdate, db: Session = Depends(get_db)):
    row = db.query(models.BasiszinsRate).filter(models.BasiszinsRate.year == data.year).first()
    if row:
        row.rate_percent = data.rate_percent
    else:
        row = models.BasiszinsRate(year=data.year, rate_percent=data.rate_percent)
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


@api_router.get("/tax/sparerpauschbetrag")
def get_sparerpauschbetrag(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    return {"amount": s.sparerpauschbetrag}


@api_router.put("/tax/sparerpauschbetrag")
def update_sparerpauschbetrag(data: schemas.SparerpauschbetragUpdate, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    s.sparerpauschbetrag = data.amount
    db.commit()
    return {"amount": s.sparerpauschbetrag}


@api_router.get("/tax/vorabpauschale", response_model=schemas.PortfolioVorabpauschaleOut)
def get_vorabpauschale(year: Optional[int] = None, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return tax.portfolio_vorabpauschale(db, space_id, year or date.today().year)


@api_router.get("/tax/realized-gains", response_model=schemas.RealizedGainsOut)
def get_realized_gains(year: Optional[int] = None, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return tax.compute_realized_gains(db, space_id, year or date.today().year)


@api_router.get("/tax/summary", response_model=schemas.TaxSummaryOut)
def get_tax_summary(year: Optional[int] = None, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    y = year or date.today().year
    vp = tax.portfolio_vorabpauschale(db, space_id, y)
    rg = tax.compute_realized_gains(db, space_id, y)
    settings = auth.get_or_create_settings(db)
    taxable = max(0.0, vp.total_steuerpflichtig + max(rg.total_gain, 0.0) - settings.sparerpauschbetrag)
    return schemas.TaxSummaryOut(
        year=y, vorabpauschale_total=vp.total_steuerpflichtig, realized_gain_total=rg.total_gain,
        sparerpauschbetrag=settings.sparerpauschbetrag, taxable_after_allowance=round(taxable, 2),
    )


# ---------------- KI-Assistent (Ollama) ----------------
@api_router.get("/settings/ollama", response_model=schemas.OllamaSettingsOut)
def get_ollama_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.OllamaSettingsOut(url=settings.ollama_url, model=settings.ollama_model, beleg_chat_model=settings.beleg_chat_model)


@api_router.put("/settings/ollama", response_model=schemas.OllamaSettingsOut)
def update_ollama_settings(data: schemas.OllamaSettingsUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.ollama_url = data.url
    settings.ollama_model = data.model
    settings.beleg_chat_model = data.beleg_chat_model
    db.commit()
    return schemas.OllamaSettingsOut(url=settings.ollama_url, model=settings.ollama_model, beleg_chat_model=settings.beleg_chat_model)


@api_router.get("/ollama/models", response_model=schemas.OllamaModelsOut)
def get_ollama_models(url: Optional[str] = None, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    target = url or settings.ollama_url
    if not target:
        raise HTTPException(400, "Bitte zuerst eine Ollama-Server-URL angeben")
    try:
        return schemas.OllamaModelsOut(models=ollama_client.list_models(target))
    except Exception as e:
        raise HTTPException(400, f"Ollama nicht erreichbar: {e}")


@api_router.post("/ollama/pull", response_model=schemas.OllamaPullResult)
def pull_ollama_model(data: schemas.OllamaPullRequest, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    target = data.url or settings.ollama_url
    if not target:
        raise HTTPException(400, "Bitte zuerst eine Ollama-Server-URL angeben")
    model = data.model.strip()
    if not model:
        raise HTTPException(400, "Bitte einen Modellnamen angeben (z.B. llama3.2:1b)")
    try:
        status = ollama_client.pull_model(target, model)
        return schemas.OllamaPullResult(ok=True, status=status)
    except Exception as e:
        raise HTTPException(400, f"Herunterladen fehlgeschlagen: {e}")


def _build_portfolio_insight_prompt(db: Session, space_id: int) -> str:
    net_worth = crud.net_worth(db, space_id)
    holdings = [crud.holding_out(h) for h in crud.get_holdings(db, space_id)]
    diversification = crud.portfolio_diversification(db, space_id)

    lines = [
        "Du bist ein nüchterner, hilfreicher Finanzassistent für Kies, ein privates Finanztool.",
        "Gib eine kurze Einschätzung auf Deutsch (max. 180 Wörter, Fließtext oder kurze Stichpunkte).",
        "Keine Anlageberatung, keine Kauf-/Verkaufsempfehlungen - nur Beobachtungen zu Struktur, Konzentration und Entwicklung.",
        "",
        f"Gesamtvermögen: {net_worth.total:.2f} EUR (Konten: {net_worth.accounts_total:.2f} EUR, Investments: {net_worth.investments_total:.2f} EUR)",
        "",
        "Positionen:",
    ]
    for h in holdings:
        asset_type_label = h.asset_type.value if hasattr(h.asset_type, "value") else h.asset_type
        lines.append(
            f"- {h.name} ({asset_type_label}, Sektor: {h.sector or 'unbekannt'}): "
            f"Wert {h.current_value:.2f} EUR, Gewinn/Verlust {h.gain_pct:.1f}%, Risiko {h.risk_level}"
        )
    lines.append("")
    lines.append("Verteilung nach Anlageklasse: " + ", ".join(f"{s.label} {s.percent:.0f}%" for s in diversification.by_asset_type))
    lines.append("Verteilung nach Sektor: " + ", ".join(f"{s.label} {s.percent:.0f}%" for s in diversification.by_sector))
    if diversification.risk_flags:
        lines.append("Bereits erkannte Risikohinweise: " + "; ".join(f.message for f in diversification.risk_flags))
    return "\n".join(lines)


@api_router.post("/ai/portfolio-insight", response_model=schemas.AiTextResult)
def portfolio_insight(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    settings = auth.get_or_create_settings(db)
    if not settings.ollama_url or not settings.ollama_model:
        raise HTTPException(400, "Bitte zuerst Ollama-Server-URL und Modell in den Einstellungen hinterlegen")
    prompt = _build_portfolio_insight_prompt(db, space_id)
    try:
        text = ollama_client.generate(settings.ollama_url, settings.ollama_model, prompt)
    except Exception as e:
        return schemas.AiTextResult(text=None, error=str(e))
    return schemas.AiTextResult(text=text, error=None)


@api_router.get("/ai/missing-receipts", response_model=schemas.MissingReceiptsOut)
def missing_receipts(min_amount: float = 20.0, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    transactions = crud.transactions_missing_receipt(db, space_id, min_amount)
    total = round(sum(abs(t.amount) for t in transactions), 2)

    summary = None
    settings = auth.get_or_create_settings(db)
    if settings.ollama_url and settings.ollama_model and transactions:
        lines = [
            "Du bist ein freundlicher Finanzassistent für Kies, ein privates Finanztool.",
            f"Der Nutzer hat {len(transactions)} Ausgabe(n) ohne hinterlegten Beleg im Gesamtwert von {total:.2f} EUR.",
            "Hier die Liste (Datum, Betrag, Beschreibung):",
        ]
        for t in transactions[:30]:
            lines.append(f"- {t.date}: {abs(t.amount):.2f} EUR, {t.description or 'ohne Beschreibung'}")
        lines.append("")
        lines.append(
            "Schreib einen kurzen, freundlichen Hinweis auf Deutsch (2-4 Sätze), der auffällige Muster nennt "
            "(z.B. Kategorie/Zeitraum falls erkennbar) und motiviert, die Belege nachzutragen."
        )
        try:
            summary = ollama_client.generate(settings.ollama_url, settings.ollama_model, "\n".join(lines))
        except Exception:
            summary = None

    return schemas.MissingReceiptsOut(transactions=transactions, total_amount=total, summary=summary)


# ---------------- Beleg-Chat (Bild/PDF/Text -> Buchung oder Investment-Position) ----------------
BELEG_CHAT_SYSTEM_PROMPT = """Du bist ein Assistent in Kies, einem privaten Finanztool, der Belege, Kassenbons, \
Wertpapier-Abrechnungen und Kontoauszüge ausliest, die der Nutzer als Bild, PDF oder Text schickt. \
Antworte immer kurz und freundlich auf Deutsch.

Wenn du EINDEUTIG eine Buchung (Ausgabe/Einnahme auf einem Konto) oder einen \
Wertpapier-/Krypto-Kauf, -Verkauf, Staking-Ertrag oder eine Dividende erkennst, gib am ENDE deiner \
Antwort zusätzlich für JEDEN erkannten Vorgang einen eigenen JSON-Block in dreifachen Backticks mit "json" aus. \
Enthält das Dokument z.B. mehrere Zeilen eines Kontoauszugs oder mehrere Positionen einer Abrechnung, \
gib entsprechend MEHRERE JSON-Blöcke hintereinander aus (einen pro Vorgang), nicht nur einen.

Für eine Kontobuchung:
```json
{"type": "transaction", "date": "YYYY-MM-DD", "amount": -12.34, "description": "Rewe", "category": "Lebensmittel", "notes": null}
```
(amount negativ = Ausgabe, positiv = Einnahme; category ist dein bester Vorschlag für eine Kategorie, z.B. "Lebensmittel", "Miete", "Gehalt")

Für einen Investment-Vorgang:
```json
{"type": "holding_lot", "asset_type": "aktie", "name": "Apple Inc", "symbol": "AAPL", "lot_type": "kauf", "date": "YYYY-MM-DD", "quantity": 1.5, "price_per_unit": 150.20}
```
(asset_type: aktie/etf/anleihe/krypto/sonstiges, lot_type: kauf/verkauf/staking/dividende)

Bist du dir NICHT sicher oder fehlen wichtige Angaben (z.B. Betrag oder Datum), gib für diesen Vorgang KEINEN JSON-Block aus, \
sondern frag im Text konkret nach den fehlenden Angaben. Erkennst du keine Buchung/keinen Investment-Vorgang, \
gib ebenfalls keinen JSON-Block aus - antworte dann nur im Fließtext."""

_JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_beleg_proposals(reply: str, allowed_types=("transaction", "holding_lot")) -> list[dict]:
    proposals = []
    for match in _JSON_BLOCK_RE.findall(reply):
        try:
            data = json.loads(match)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("type") in allowed_types:
            proposals.append(data)
    return proposals


def _resolve_described_transaction(db: Session, space_id: int, payload: dict) -> tuple[Optional[dict], Optional[str]]:
    """Löst eine von der KI nur beschriebene Buchung (Datum/Betrag/Beschreibung) auf
    eine konkrete Buchung in der Datenbank auf - die KI kennt keine internen IDs.
    Genau ein Treffer wird akzeptiert, sonst wird die Aktion nicht angeboten."""
    try:
        tx_date = date.fromisoformat(str(payload.get("date")))
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        return None, "Datum oder Betrag der gemeinten Buchung ist unklar."
    matches = _find_duplicate_matches(db, space_id, amount, tx_date, tolerance_days=3)
    if not matches:
        return None, "Keine passende Buchung gefunden (Datum/Betrag prüfen)."
    if len(matches) > 1:
        return None, f"{len(matches)} Buchungen passen auf Datum und Betrag - bitte genauer beschreiben."
    return matches[0], None


def _find_receipt_matches(db: Session, space_id: int, amount: float, tx_date: date, tolerance_days: int = 3) -> list[dict]:
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


def _find_duplicate_matches(db: Session, space_id: int, amount: float, tx_date: date, tolerance_days: int = 1) -> list[dict]:
    """Bereits existierende Buchungen, die zu einem neuen Vorschlag verdächtig ähnlich sind (möglicher Doppel-Eintrag)."""
    matches = []
    for t in crud.get_transactions(db, space_id):
        if abs(t.amount - amount) > 0.01:
            continue
        if abs((t.date - tx_date).days) > tolerance_days:
            continue
        matches.append({"id": t.id, "date": t.date.isoformat(), "amount": t.amount, "description": t.description})
    return matches


@api_router.post("/ai/beleg-chat", response_model=schemas.BelegChatResult)
def beleg_chat(
    message: str = Form(""),
    history: str = Form("[]"),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    settings = auth.get_or_create_settings(db)
    chat_model = settings.beleg_chat_model or settings.ollama_model
    if not settings.ollama_url or not chat_model:
        raise HTTPException(400, "Bitte zuerst Ollama-Server-URL und Modell in den Einstellungen hinterlegen")

    try:
        hist = json.loads(history)
        if not isinstance(hist, list):
            hist = []
    except json.JSONDecodeError:
        hist = []

    messages = [{"role": "system", "content": BELEG_CHAT_SYSTEM_PROMPT}]
    for m in hist:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": str(m["content"])})

    attachment_filename = None
    attachment_b64 = None
    user_content = message or "(kein Text, siehe Anhang)"
    images: list[str] = []

    if file is not None:
        raw = file.file.read()
        attachment_filename = file.filename
        attachment_b64 = base64.b64encode(raw).decode()
        content_type = file.content_type or ""
        is_pdf = content_type == "application/pdf" or (file.filename or "").lower().endswith(".pdf")
        if is_pdf:
            try:
                text, pdf_images = document_extract.extract_pdf(raw)
            except Exception as e:
                return schemas.BelegChatResult(reply="", error=f"PDF konnte nicht gelesen werden: {e}")
            if text:
                user_content += f"\n\n[Inhalt des angehängten PDF]\n{text}"
            else:
                images.extend(pdf_images)
        elif content_type.startswith("image/"):
            images.append(base64.b64encode(raw).decode())

    user_msg = {"role": "user", "content": user_content}
    if images:
        user_msg["images"] = images
    messages.append(user_msg)

    try:
        reply_raw = ollama_client.chat(settings.ollama_url, chat_model, messages)
    except Exception as e:
        return schemas.BelegChatResult(reply="", error=str(e))

    proposals = _extract_beleg_proposals(reply_raw)
    for p in proposals:
        if p.get("type") != "transaction":
            continue
        try:
            p_date = date.fromisoformat(str(p.get("date")))
            p_amount = float(p.get("amount"))
        except (TypeError, ValueError):
            continue
        if file is not None:
            receipt_matches = _find_receipt_matches(db, space_id, p_amount, p_date)
            if receipt_matches:
                p["receipt_matches"] = receipt_matches
        duplicate_matches = _find_duplicate_matches(db, space_id, p_amount, p_date)
        if duplicate_matches:
            p["duplicate_matches"] = duplicate_matches

    reply_clean = _JSON_BLOCK_RE.sub("", reply_raw).strip()
    if not reply_clean:
        reply_clean = (
            f"Ich habe {len(proposals)} Vorschlag/Vorschläge erkannt - bitte prüfen:" if proposals else reply_raw
        )

    return schemas.BelegChatResult(
        reply=reply_clean,
        proposals=proposals,
        attachment_filename=attachment_filename,
        attachment_base64=attachment_b64,
    )


def _beleg_field_as_str(value) -> Optional[str]:
    """Macht Freitext-Felder robust gegen KI-Ausgaben, die z.B. eine Liste statt
    eines einzelnen Strings liefern (empirisch bei kleinen Modellen beobachtet)."""
    if value is None:
        return None
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or None
    text = str(value).strip()
    return text or None


@api_router.post("/ai/beleg-chat/apply", response_model=schemas.BelegChatApplyResult)
def beleg_chat_apply(data: schemas.BelegChatApply, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    payload = data.data

    def _save_attachment(target_id: int) -> Optional[str]:
        if not (data.attachment_base64 and data.attachment_filename):
            return None
        ext = os.path.splitext(data.attachment_filename)[1]
        safe_name = f"{target_id}_{uuid.uuid4().hex}{ext}"
        try:
            raw = base64.b64decode(data.attachment_base64)
        except Exception:
            return None
        with open(os.path.join(UPLOAD_DIR, safe_name), "wb") as f:
            f.write(raw)
        return safe_name

    if data.type == "transaction":
        if not data.account_id or not crud.get_account(db, data.account_id, space_id):
            raise HTTPException(400, "Bitte ein gültiges Konto auswählen")
        try:
            tx_date = date.fromisoformat(str(payload.get("date")))
        except (ValueError, TypeError):
            raise HTTPException(400, "Ungültiges Datum")
        try:
            amount = float(payload.get("amount"))
        except (TypeError, ValueError):
            raise HTTPException(400, "Ungültiger Betrag")

        category_id = None
        category_name = _beleg_field_as_str(payload.get("category"))
        if category_name:
            match = next((c for c in crud.get_categories(db) if c.name.lower() == category_name.lower()), None)
            if match:
                category_id = match.id

        tx = crud.create_transaction(db, schemas.TransactionCreate(
            date=tx_date, amount=amount,
            description=_beleg_field_as_str(payload.get("description")),
            notes=_beleg_field_as_str(payload.get("notes")),
            account_id=data.account_id,
            category_id=category_id,
        ))
        receipt_name = _save_attachment(tx.id)
        if receipt_name:
            crud.set_receipt(db, tx.id, space_id, receipt_name)
        return schemas.BelegChatApplyResult(ok=True, transaction_id=tx.id, message="Buchung angelegt.")

    if data.type == "holding_lot":
        asset_type = HOLDING_ASSET_TYPE_ALIASES.get((payload.get("asset_type") or "").strip().lower())
        if not asset_type:
            raise HTTPException(400, "Unbekannte oder fehlende Anlageklasse (aktie/etf/anleihe/krypto/sonstiges)")
        symbol = (_beleg_field_as_str(payload.get("symbol")) or "").strip()
        name = (_beleg_field_as_str(payload.get("name")) or "").strip() or symbol
        if not symbol:
            raise HTTPException(400, "Symbol fehlt")
        try:
            lot_date = date.fromisoformat(str(payload.get("date")))
        except (ValueError, TypeError):
            raise HTTPException(400, "Ungültiges Datum")
        try:
            quantity = float(payload.get("quantity"))
            price_per_unit = float(payload.get("price_per_unit"))
        except (TypeError, ValueError):
            raise HTTPException(400, "Ungültige Stückzahl oder ungültiger Preis")
        try:
            lot_type = models.LotType(payload.get("lot_type") or "kauf")
        except ValueError:
            raise HTTPException(400, "Unbekannter Transaktionstyp (kauf/verkauf/staking/dividende)")

        existing = next(
            (h for h in crud.get_holdings(db, space_id) if h.asset_type == asset_type and h.symbol.lower() == symbol.lower()),
            None,
        )
        if existing:
            crud.create_lot(db, existing.id, space_id, schemas.HoldingLotCreate(
                date=lot_date, type=lot_type, quantity=quantity, price_per_unit=price_per_unit,
            ))
            holding_id = existing.id
            msg = f"Als weiterer Vorgang zu bestehender Position '{name}' hinzugefügt."
        else:
            h = crud.create_holding(db, schemas.HoldingCreate(
                asset_type=asset_type, name=name, symbol=symbol,
                quantity=quantity, purchase_price=price_per_unit, purchase_date=lot_date,
            ), space_id)
            holding_id = h.id
            msg = f"Neue Position '{name}' angelegt."
        return schemas.BelegChatApplyResult(ok=True, holding_id=holding_id, message=msg)

    if data.type == "attach_receipt":
        tx_id = payload.get("transaction_id")
        tx = crud.get_transaction(db, tx_id, space_id) if tx_id else None
        if not tx:
            raise HTTPException(400, "Buchung nicht gefunden")
        receipt_name = _save_attachment(tx.id)
        if not receipt_name:
            raise HTTPException(400, "Kein Anhang zum Speichern vorhanden")
        crud.set_receipt(db, tx.id, space_id, receipt_name)
        return schemas.BelegChatApplyResult(ok=True, transaction_id=tx.id, message="Beleg an bestehende Buchung angehängt.")

    if data.type == "update_category":
        tx_id = payload.get("transaction_id")
        tx = crud.get_transaction(db, tx_id, space_id) if tx_id else None
        if not tx:
            raise HTTPException(400, "Buchung nicht gefunden")
        category_name = _beleg_field_as_str(payload.get("category")) or ""
        match = next((c for c in crud.get_categories(db) if c.name.lower() == category_name.lower()), None)
        if not match:
            raise HTTPException(400, "Unbekannte Kategorie")
        tx.category_id = match.id
        db.commit()
        return schemas.BelegChatApplyResult(ok=True, transaction_id=tx.id, message=f"Kategorie auf „{match.name}“ gesetzt.")

    if data.type == "create_debt":
        try:
            original_amount = float(payload.get("original_amount"))
        except (TypeError, ValueError):
            raise HTTPException(400, "Ungültiger oder fehlender finanzierter Betrag")
        name = (_beleg_field_as_str(payload.get("name")) or "").strip()
        if not name:
            raise HTTPException(400, "Name fehlt")

        def _opt_date(key: str) -> Optional[date]:
            val = payload.get(key)
            try:
                return date.fromisoformat(str(val)) if val else None
            except ValueError:
                return None

        def _opt_float(key: str) -> Optional[float]:
            val = payload.get(key)
            try:
                return float(val) if val is not None and val != "" else None
            except (TypeError, ValueError):
                return None

        debt = crud.create_debt(db, schemas.DebtCreate(
            name=name,
            lender=_beleg_field_as_str(payload.get("lender")),
            original_amount=original_amount,
            interest_rate_percent=_opt_float("interest_rate_percent") or 0.0,
            monthly_payment=_opt_float("monthly_payment"),
            start_date=_opt_date("start_date"),
            planned_end_date=_opt_date("planned_end_date"),
            account_id=payload.get("resolved_account_id"),
            notes=_beleg_field_as_str(payload.get("notes")),
        ), space_id)

        payments_created = 0
        for pay in payload.get("payments") or []:
            if not isinstance(pay, dict):
                continue
            try:
                pay_date = date.fromisoformat(str(pay.get("date")))
                pay_amount = float(pay.get("total_amount"))
            except (TypeError, ValueError):
                continue
            interest_val = pay.get("interest_amount")
            try:
                interest_amount = float(interest_val) if interest_val is not None and interest_val != "" else None
            except (TypeError, ValueError):
                interest_amount = None
            crud.create_debt_payment(db, debt.id, space_id, schemas.DebtPaymentCreate(
                date=pay_date,
                total_amount=pay_amount,
                interest_amount=interest_amount,
                transaction_id=pay.get("resolved_transaction_id"),
                notes=_beleg_field_as_str(pay.get("notes")),
            ))
            payments_created += 1

        db.refresh(debt)
        return schemas.BelegChatApplyResult(
            ok=True, debt_id=debt.id,
            message=f"Schuld „{debt.name}“ angelegt ({payments_created} Zahlung(en) verknüpft, Restschuld {debt.current_balance:.2f} EUR).",
        )

    if data.type == "mark_transfer":
        tx_id = payload.get("transaction_id")
        tx = crud.get_transaction(db, tx_id, space_id) if tx_id else None
        if not tx:
            raise HTTPException(400, "Buchung nicht gefunden")
        tx.is_transfer = True
        tx.category_id = None
        db.commit()
        return schemas.BelegChatApplyResult(ok=True, transaction_id=tx.id, message="Als Umbuchung markiert - zählt nicht mehr als Einnahme/Ausgabe.")

    raise HTTPException(400, "Unbekannter Vorschlagstyp")


# ---------------- Assistant-Chat (schwebender KI-Button, allgemeine Anweisungen) ----------------
ASSISTANT_CHAT_SYSTEM_PROMPT = """Du bist der KI-Assistent von Kies, einem privaten Finanztool, erreichbar per Chat-Button \
auf jeder Seite der App. Der Nutzer gibt dir Anweisungen oder Fragen in normaler Sprache. Antworte immer kurz \
und freundlich auf Deutsch.

Du kannst VIER Arten von Vorschlägen machen, wenn eindeutig danach gefragt wird - dafür gibst du am Ende \
deiner Antwort einen JSON-Block in dreifachen Backticks mit "json" aus:

1. Neue Buchung anlegen:
```json
{"type": "transaction", "date": "YYYY-MM-DD", "amount": -12.34, "description": "Rewe", "category": "Lebensmittel", "notes": null}
```
(amount negativ = Ausgabe, positiv = Einnahme)

2. Eine bestehende Buchung, die der Nutzer beschreibt, einer Kategorie zuordnen (du kennst keine internen IDs, \
beschreibe die gemeinte Buchung daher so genau wie möglich anhand des Kontexts unten):
```json
{"type": "update_category", "date": "YYYY-MM-DD", "amount": -12.34, "description": "Rewe", "category": "Lebensmittel"}
```

3. Eine bestehende Buchung als Umbuchung zwischen zwei eigenen Konten markieren (zählt dann nicht mehr als \
Einnahme/Ausgabe):
```json
{"type": "mark_transfer", "date": "YYYY-MM-DD", "amount": -500.00, "description": "Überweisung"}
```

4. Eine Schuld/Ratenkauf anlegen (z.B. "PayPal Später bezahlen", Ratenkredit, Kleinkredit) - typischerweise, \
wenn der Nutzer einen Einkauf beschreibt, den er in festen Raten abbezahlt. Die eigentliche Kaufbuchung (der \
volle Betrag) ist meist schon als normale Buchung importiert - lass die unangetastet, hier geht es NUR um die \
Ratenzahlungsvereinbarung und die bereits geleisteten Raten:
```json
{"type": "create_debt", "name": "PayPal Später bezahlen – <Händler>", "lender": "PayPal",
 "account_description": "<Kontoname, über das die Raten laufen>", "original_amount": 604.98,
 "interest_rate_percent": 11.8, "monthly_payment": 28.42, "start_date": "2026-06-25",
 "planned_end_date": "2028-06-25", "notes": "24 Raten à 28,42€, gesamt 682,10€.",
 "payments": [
   {"date": "2026-07-09", "total_amount": 0.18, "notes": "Manuelle Zahlung"},
   {"date": "2026-07-25", "total_amount": 28.42, "interest_amount": 5.95, "notes": "Automatischer Einzug"}
 ]}
```
Regeln dafür: "original_amount" ist der tatsächliche Kaufpreis/finanzierte Betrag OHNE künftige Zinsen (nicht \
die Summe aller Raten). "interest_rate_percent" ist der effektive Jahreszins, falls genannt; ist nur der \
Zinsanteil EINER Zahlung bekannt (nicht der Jahreszins selbst), rechne ihn hoch (Zinsanteil × 12 ÷ original_amount \
× 100) und weise im Fließtext darauf hin, dass das eine Schätzung ist. Ist gar nichts zur Verzinsung bekannt, lass \
"interest_rate_percent" weg. "payments" enthält nur bereits tatsächlich geleistete Zahlungen (kann eine leere \
Liste sein) - "interest_amount" pro Zahlung nur setzen, wenn der Nutzer den Zinsanteil dieser konkreten Zahlung \
explizit genannt hat, sonst weglassen. Erfinde keine Zahlen, die nicht genannt wurden oder sich nicht eindeutig \
herleiten lassen - frag im Zweifel nach.

Für Fragen zum aktuellen Stand (Kontostand, Vermögen, Ausgaben) nutze NUR die unten mitgelieferten Fakten und \
antworte im Fließtext OHNE JSON-Block - erfinde keine Zahlen. Bist du dir bei einer Aktion nicht sicher oder \
fehlen wichtige Angaben, gib KEINEN JSON-Block aus und frag nach.

Du darfst außerdem im Internet suchen, wenn du für eine Frage aktuelle, recherchierbare Informationen brauchst \
(z.B. aktuelle Steuersätze/Freibeträge, Rechtslage, Zinssätze, aktuelle Nachrichten) - dein eigenes Wissen kann \
veraltet sein. Brauchst du das, antworte NUR mit einem Suchblock, sonst NICHTS (kein Fließtext davor/danach):
```search
<eine kurze, gezielte Suchanfrage>
```
Du bekommst danach Suchergebnisse und antwortest DANN im Fließtext basierend darauf. Nutze das gezielt, nicht bei \
jeder Frage - Fragen zu Beträgen/Kategorien/Buchungen etc. beantwortest du direkt.

Für Steuerfragen (z.B. "Leasing gewerblich oder privat absetzen"): gib eine fundierte Einschätzung inkl. der \
wichtigsten Rechenlogik, aber das ist KEINE verbindliche Steuerberatung - weise IMMER kurz darauf hin, dass der \
Nutzer das bei komplexen/hohen Beträgen mit einem Steuerberater absichern sollte."""


def _assistant_context(db: Session, space_id: int) -> str:
    """Fakten-Block, der dem System-Prompt angehängt wird, damit Fragen zum
    aktuellen Stand nicht halluziniert werden müssen."""
    accounts = crud.get_accounts(db, space_id)
    nw = crud.net_worth(db, space_id)
    lines = ["Aktueller Stand:"]
    for a in accounts:
        lines.append(f"- Konto „{a.name}“: {crud.account_balance(db, a):.2f} EUR")
    lines.append(f"- Investments gesamt: {nw.investments_total:.2f} EUR")
    if nw.debts_total:
        lines.append(f"- Offene Schulden: {nw.debts_total:.2f} EUR")
    lines.append(f"- Nettovermögen: {nw.total:.2f} EUR")
    debts = crud.get_debts(db, space_id)
    if debts:
        lines.append("Vorhandene Schulden/Ratenkäufe: " + ", ".join(
            f"„{d.name}“ ({d.current_balance:.2f} EUR offen)" for d in debts if d.status == models.DebtStatus.active
        ))
    categories = crud.get_categories(db)
    if categories:
        lines.append("Vorhandene Kategorien: " + ", ".join(c.name for c in categories))
    return "\n".join(lines)


ASSISTANT_PROPOSAL_TYPES = ("transaction", "update_category", "mark_transfer", "create_debt")


def _resolve_debt_proposal(db: Session, space_id: int, p: dict) -> None:
    """Löst account_description auf ein echtes Konto auf und versucht, jede
    genannte Zahlung einer bereits importierten Buchung zuzuordnen (die KI kennt
    keine internen Konto-/Buchungs-IDs). Buchungen ohne eindeutigen Treffer werden
    trotzdem angelegt, nur ohne Verknüpfung."""
    account_desc = (p.get("account_description") or "").strip().lower()
    account = None
    if account_desc:
        account = next(
            (a for a in crud.get_accounts(db, space_id) if account_desc in a.name.lower() or a.name.lower() in account_desc),
            None,
        )
    p["resolved_account_id"] = account.id if account else None
    p["resolved_account_name"] = account.name if account else None

    for payment in p.get("payments") or []:
        if not isinstance(payment, dict):
            continue
        try:
            pay_date = date.fromisoformat(str(payment.get("date")))
            amount = float(payment.get("total_amount"))
        except (TypeError, ValueError):
            continue
        candidates = [
            t for t in crud.get_transactions(db, space_id)
            if (not account or t.account_id == account.id)
            and abs(abs(t.amount) - abs(amount)) < 0.01
            and abs((t.date - pay_date).days) <= 3
        ]
        if len(candidates) == 1:
            t = candidates[0]
            payment["resolved_transaction_id"] = t.id
            payment["resolved_transaction_label"] = f"{t.date.isoformat()} · {t.amount:.2f} EUR · {t.description or 'ohne Beschreibung'}"
_SEARCH_BLOCK_RE = re.compile(r"```search\s*(.*?)\s*```", re.DOTALL)


@api_router.post("/ai/assistant-chat", response_model=schemas.AssistantChatResult)
def assistant_chat(
    message: str = Form(...),
    history: str = Form("[]"),
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    settings = auth.get_or_create_settings(db)
    chat_model = settings.ollama_model or settings.beleg_chat_model
    if not settings.ollama_url or not chat_model:
        raise HTTPException(400, "Bitte zuerst Ollama-Server-URL und Modell in den Einstellungen hinterlegen")

    try:
        hist = json.loads(history)
        if not isinstance(hist, list):
            hist = []
    except json.JSONDecodeError:
        hist = []

    system_content = ASSISTANT_CHAT_SYSTEM_PROMPT + "\n\n" + _assistant_context(db, space_id)
    messages = [{"role": "system", "content": system_content}]
    for m in hist:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": str(m["content"])})
    messages.append({"role": "user", "content": message})

    try:
        reply_raw = ollama_client.chat(settings.ollama_url, chat_model, messages)
    except Exception as e:
        return schemas.AssistantChatResult(reply="", error=str(e))

    web_searches: list[str] = []
    search_match = _SEARCH_BLOCK_RE.search(reply_raw)
    if search_match:
        query = search_match.group(1).strip()
        if not settings.brave_search_api_key_encrypted:
            return schemas.AssistantChatResult(
                reply=f"Ich würde dafür gern im Internet suchen („{query}“), habe aber noch keinen "
                      "Brave-Search-API-Key hinterlegt. Trag ihn in den Einstellungen unter "
                      "„Web-Suche für KI-Chat“ ein, dann kann ich das."
            )
        try:
            api_key = bank_sync.decrypt_secret(settings.secret_key, settings.brave_search_api_key_encrypted)
            results = websearch.search(api_key, query)
        except Exception as e:
            return schemas.AssistantChatResult(reply="", error=f"Web-Suche fehlgeschlagen: {e}")
        web_searches.append(query)
        # Zweite Runde: die Suchergebnisse als weitere Nutzer-Nachricht anhängen und
        # eine finale, auf den Fakten basierende Antwort einholen - nur ein
        # Suchdurchgang pro Chatnachricht, damit keine Endlosschleife entstehen kann.
        messages.append({"role": "assistant", "content": reply_raw})
        messages.append({"role": "user", "content": websearch.format_for_prompt(query, results)
                         + "\n\nBeantworte jetzt meine ursprüngliche Frage auf Basis dieser Suchergebnisse."})
        try:
            reply_raw = ollama_client.chat(settings.ollama_url, chat_model, messages)
        except Exception as e:
            return schemas.AssistantChatResult(reply="", error=str(e), web_searches=web_searches)

    proposals = _extract_beleg_proposals(reply_raw, allowed_types=ASSISTANT_PROPOSAL_TYPES)
    for p in proposals:
        if p.get("type") in ("update_category", "mark_transfer"):
            resolved, err = _resolve_described_transaction(db, space_id, p)
            if resolved:
                p["resolved_transaction"] = resolved
            else:
                p["resolution_error"] = err
        elif p.get("type") == "transaction":
            try:
                p_date = date.fromisoformat(str(p.get("date")))
                p_amount = float(p.get("amount"))
            except (TypeError, ValueError):
                continue
            duplicate_matches = _find_duplicate_matches(db, space_id, p_amount, p_date)
            if duplicate_matches:
                p["duplicate_matches"] = duplicate_matches
        elif p.get("type") == "create_debt":
            _resolve_debt_proposal(db, space_id, p)

    reply_clean = _SEARCH_BLOCK_RE.sub("", _JSON_BLOCK_RE.sub("", reply_raw)).strip()
    if not reply_clean:
        reply_clean = f"Ich habe {len(proposals)} Vorschlag/Vorschläge erkannt - bitte prüfen:" if proposals else reply_raw

    return schemas.AssistantChatResult(reply=reply_clean, proposals=proposals, web_searches=web_searches)


# ---------------- FinTS Bank-Sync ----------------
@api_router.get("/settings/fints")
def get_fints_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return {"fints_product_id": settings.fints_product_id}


@api_router.put("/settings/fints")
def update_fints_settings(data: schemas.FintsSettingsUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.fints_product_id = data.fints_product_id
    db.commit()
    return {"fints_product_id": settings.fints_product_id}


@api_router.get("/bank-connections", response_model=List[schemas.BankConnectionOut])
def list_bank_connections(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.get_bank_connections(db, space_id)


@api_router.post("/bank-connections", response_model=schemas.BankConnectionOut)
def create_bank_connection(data: schemas.BankConnectionCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if not crud.get_account(db, data.account_id, space_id):
        raise HTTPException(400, "Ziel-Konto existiert nicht in diesem Bereich")
    settings = auth.get_or_create_settings(db)
    pin_encrypted = bank_sync.encrypt_pin(settings.secret_key, data.pin)
    return crud.create_bank_connection(
        db, space_id, data.name, data.blz, data.fints_url, data.login, pin_encrypted, data.account_id, data.iban,
    )


@api_router.delete("/bank-connections/{connection_id}")
def remove_bank_connection(connection_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.delete_bank_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "Bank-Verbindung nicht gefunden")
    return {"ok": True}


@api_router.post("/bank-connections/{connection_id}/sync", response_model=schemas.SyncResult)
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


@api_router.post("/bank-connections/{connection_id}/submit-tan", response_model=schemas.SyncResult)
def submit_tan(connection_id: int, data: schemas.TanSubmit, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.get_bank_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "Bank-Verbindung nicht gefunden")
    result = bank_sync.submit_tan(db, conn, data.tan)
    return schemas.SyncResult(**result)


# ---------------- Bitvavo (Krypto-Börse) ----------------
@api_router.get("/bitvavo-connections", response_model=List[schemas.BitvavoConnectionOut])
def list_bitvavo_connections(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.get_bitvavo_connections(db, space_id)


@api_router.post("/bitvavo-connections", response_model=schemas.BitvavoConnectionOut)
def create_bitvavo_connection(data: schemas.BitvavoConnectionCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    settings = auth.get_or_create_settings(db)
    api_key_enc = bank_sync.encrypt_secret(settings.secret_key, data.api_key)
    api_secret_enc = bank_sync.encrypt_secret(settings.secret_key, data.api_secret)
    return crud.create_bitvavo_connection(db, space_id, data.name, api_key_enc, api_secret_enc)


@api_router.delete("/bitvavo-connections/{connection_id}")
def remove_bitvavo_connection(connection_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.delete_bitvavo_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "Bitvavo-Verbindung nicht gefunden")
    return {"ok": True}


@api_router.post("/bitvavo-connections/{connection_id}/sync", response_model=schemas.BitvavoSyncResult)
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
@api_router.get("/paypal-connections", response_model=List[schemas.PayPalConnectionOut])
def list_paypal_connections(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.get_paypal_connections(db, space_id)


@api_router.post("/paypal-connections", response_model=schemas.PayPalConnectionOut)
def create_paypal_connection(data: schemas.PayPalConnectionCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    settings = auth.get_or_create_settings(db)
    client_id_enc = bank_sync.encrypt_secret(settings.secret_key, data.client_id)
    client_secret_enc = bank_sync.encrypt_secret(settings.secret_key, data.client_secret)
    return crud.create_paypal_connection(db, space_id, data.account_id, data.name, client_id_enc, client_secret_enc)


@api_router.delete("/paypal-connections/{connection_id}")
def remove_paypal_connection(connection_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.delete_paypal_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "PayPal-Verbindung nicht gefunden")
    return {"ok": True}


@api_router.post("/paypal-connections/{connection_id}/sync", response_model=schemas.PayPalSyncResult)
def sync_paypal_connection(connection_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.get_paypal_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "PayPal-Verbindung nicht gefunden")
    settings = auth.get_or_create_settings(db)
    client_id = bank_sync.decrypt_secret(settings.secret_key, conn.client_id_encrypted)
    client_secret = bank_sync.decrypt_secret(settings.secret_key, conn.client_secret_encrypted)
    result = paypal_sync.sync(db, conn, client_id, client_secret)
    return schemas.PayPalSyncResult(**result)


# ---------------- Automatischer Sync (Zeitplan) ----------------
@api_router.get("/settings/sync-schedule", response_model=schemas.SyncScheduleOut)
def get_sync_schedule(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.SyncScheduleOut(hour=settings.sync_hour)


@api_router.put("/settings/sync-schedule", response_model=schemas.SyncScheduleOut)
def update_sync_schedule(data: schemas.SyncScheduleUpdate, db: Session = Depends(get_db)):
    if not 0 <= data.hour <= 23:
        raise HTTPException(400, "Stunde muss zwischen 0 und 23 liegen")
    settings = auth.get_or_create_settings(db)
    settings.sync_hour = data.hour
    db.commit()
    scheduler.reschedule_job("bank_sync", trigger=CronTrigger(hour=data.hour, minute=0))
    return schemas.SyncScheduleOut(hour=settings.sync_hour)


# ---------------- Automatisierung (Umbuchungen + Auto-Kategorisierung) ----------------
@api_router.get("/settings/auto-categorize", response_model=schemas.AutoCategorizeSettingsOut)
def get_auto_categorize_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.AutoCategorizeSettingsOut(enabled=settings.auto_categorize_enabled)


@api_router.put("/settings/auto-categorize", response_model=schemas.AutoCategorizeSettingsOut)
def update_auto_categorize_settings(data: schemas.AutoCategorizeSettingsUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.auto_categorize_enabled = data.enabled
    db.commit()
    return schemas.AutoCategorizeSettingsOut(enabled=settings.auto_categorize_enabled)


@api_router.post("/ai/auto-categorize/run-now", response_model=schemas.AutoCategorizeRunResult)
def run_auto_categorize_now(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    settings = auth.get_or_create_settings(db)
    return _run_ai_maintenance_for_space(db, space_id, settings)


@api_router.get("/settings/websearch", response_model=schemas.WebSearchSettingsOut)
def get_websearch_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.WebSearchSettingsOut(api_key_set=bool(settings.brave_search_api_key_encrypted))


@api_router.put("/settings/websearch", response_model=schemas.WebSearchSettingsOut)
def update_websearch_settings(data: schemas.WebSearchSettingsUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.brave_search_api_key_encrypted = bank_sync.encrypt_secret(settings.secret_key, data.api_key)
    db.commit()
    return schemas.WebSearchSettingsOut(api_key_set=True)


@api_router.delete("/settings/websearch", response_model=schemas.WebSearchSettingsOut)
def remove_websearch_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.brave_search_api_key_encrypted = None
    db.commit()
    return schemas.WebSearchSettingsOut(api_key_set=False)


# ---------------- Anzeige-Währung (rein Frontend-Umrechnung, gespeichert bleibt EUR) ----------------
@api_router.get("/settings/currency", response_model=schemas.CurrencySettingsOut)
def get_currency_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.CurrencySettingsOut(currency=settings.display_currency)


@api_router.put("/settings/currency", response_model=schemas.CurrencySettingsOut)
def update_currency_settings(data: schemas.CurrencySettingsUpdate, db: Session = Depends(get_db)):
    currency = data.currency.upper().strip()
    if currency not in ("EUR", "CHF"):
        raise HTTPException(400, "Nur EUR oder CHF werden unterstützt")
    settings = auth.get_or_create_settings(db)
    settings.display_currency = currency
    db.commit()
    return schemas.CurrencySettingsOut(currency=settings.display_currency)


@api_router.get("/fx/rate", response_model=schemas.FxRateOut)
def get_fx_rate(to: str = "CHF"):
    to = to.upper().strip()
    try:
        rate = prices.get_cached_fx_rate("EUR", to)
    except Exception as e:
        raise HTTPException(502, f"Wechselkurs EUR/{to} gerade nicht verfügbar: {e}")
    return schemas.FxRateOut(from_currency="EUR", to_currency=to, rate=rate)


# ---------------- E-Mail-Belege ----------------
def _parse_receipt(settings, content: bytes, filename: str) -> tuple[date | None, float | None, str | None]:
    """Dünner Wrapper um document_extract.parse_receipt_fields - die gemeinsam
    mit der Datei-Sortierung genutzte Beleg-Auswertung (siehe dort)."""
    return document_extract.parse_receipt_fields(
        settings.ollama_url, settings.ollama_model, settings.beleg_chat_model, content, filename,
    )


def _run_mail_sync(db: Session, space_id: int) -> dict:
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
            treffer = _find_receipt_matches(db, space_id, betrag, datum)
            if len(treffer) == 1:
                tx_id = treffer[0]["id"]
                crud.set_receipt(db, tx_id, space_id, speichername)
                eintrag.status = "attached"
                eintrag.transaction_id = tx_id
                zugeordnet += 1

    s.mail_last_sync_at = datetime.utcnow()
    db.commit()
    return {"neu": neu, "uebersprungen": uebersprungen, "zugeordnet": zugeordnet}


@api_router.get("/settings/mail", response_model=schemas.MailSettingsOut)
def get_mail_settings(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    return schemas.MailSettingsOut(
        enabled=s.mail_enabled, host=s.imap_host, port=s.imap_port,
        user=s.imap_user, folder=s.imap_folder,
        password_set=bool(s.imap_password_encrypted),
        last_sync_at=s.mail_last_sync_at.isoformat() if s.mail_last_sync_at else None,
    )


@api_router.put("/settings/mail", response_model=schemas.MailSettingsOut)
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


@api_router.delete("/settings/mail", response_model=schemas.MailSettingsOut)
def remove_mail_settings(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    s.mail_enabled = False
    s.imap_host = s.imap_user = s.imap_password_encrypted = None
    db.commit()
    return get_mail_settings(db)


@api_router.get("/settings/creditcard", response_model=schemas.CreditCardSettingsOut)
def get_creditcard_settings(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    return schemas.CreditCardSettingsOut(
        mail_sender=s.creditcard_mail_sender, account_id=s.creditcard_account_id, debt_id=s.creditcard_debt_id,
    )


@api_router.put("/settings/creditcard", response_model=schemas.CreditCardSettingsOut)
def update_creditcard_settings(data: schemas.CreditCardSettingsUpdate, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    s.creditcard_mail_sender = (data.mail_sender or "").strip() or None
    s.creditcard_account_id = data.account_id
    s.creditcard_debt_id = data.debt_id
    db.commit()
    return get_creditcard_settings(db)


@api_router.get("/creditcard-bills/next", response_model=Optional[schemas.CreditCardBillOut])
def get_next_creditcard_bill(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    bill = crud.next_creditcard_bill(db, space_id)
    if not bill:
        return None
    label = (bill.account.name if bill.account else None) or (bill.debt.name if bill.debt else None) or "Kreditkarte"
    return schemas.CreditCardBillOut(account_name=label, due_date=bill.due_date, amount=bill.amount)


@api_router.post("/mail/test", response_model=schemas.MailTestResult)
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


@api_router.post("/mail/sync", response_model=schemas.MailSyncResult)
def sync_mail(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    try:
        r = _run_mail_sync(db, space_id)
    except Exception as e:
        db.rollback()
        raise HTTPException(502, f"Abholen fehlgeschlagen: {e}")
    return schemas.MailSyncResult(
        new_attachments=r["neu"], skipped=r["uebersprungen"], auto_attached=r["zugeordnet"]
    )


@api_router.get("/mail/attachments", response_model=List[schemas.MailAttachmentOut])
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
            vorschlaege = _find_receipt_matches(db, space_id, a.parsed_amount, a.parsed_date)
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


@api_router.post("/mail/attachments/{attachment_id}/attach")
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


@api_router.post("/mail/attachments/{attachment_id}/create-transaction", response_model=schemas.TransactionOut)
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


@api_router.post("/mail/attachments/{attachment_id}/ignore")
def ignore_mail_attachment(attachment_id: int, db: Session = Depends(get_db)):
    a = db.query(models.MailAttachment).filter(models.MailAttachment.id == attachment_id).first()
    if not a:
        raise HTTPException(404, "Anhang nicht gefunden")
    a.status = "ignored"
    db.commit()
    return {"ok": True}


# ---------------- Immich (Fotobibliothek) ----------------
def _immich_credentials(db: Session) -> tuple[str, str]:
    """Holt URL und entschlüsselten Schlüssel oder wirft einen sprechenden
    Fehler, wenn noch nichts eingerichtet ist."""
    s = auth.get_or_create_settings(db)
    if not s.immich_url or not s.immich_api_key_encrypted:
        raise HTTPException(
            400,
            "Immich ist noch nicht eingerichtet. Trage unter Einstellungen die "
            "Server-Adresse und einen API-Schlüssel ein.",
        )
    return s.immich_url, bank_sync.decrypt_secret(s.secret_key, s.immich_api_key_encrypted)


@api_router.get("/settings/immich", response_model=schemas.ImmichSettingsOut)
def get_immich_settings(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    return schemas.ImmichSettingsOut(
        url=s.immich_url, api_key_set=bool(s.immich_api_key_encrypted),
        skip_confirm=s.immich_skip_confirm,
    )


@api_router.put("/settings/immich", response_model=schemas.ImmichSettingsOut)
def update_immich_settings(data: schemas.ImmichSettingsUpdate, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    s.immich_url = data.url.strip()
    # Leeres Feld = Schlüssel unverändert lassen. Sonst müsste man ihn bei jeder
    # kleinen Adressänderung erneut aus Immich heraussuchen.
    if data.api_key:
        s.immich_api_key_encrypted = bank_sync.encrypt_secret(s.secret_key, data.api_key)
    s.immich_skip_confirm = data.skip_confirm
    db.commit()
    return schemas.ImmichSettingsOut(
        url=s.immich_url, api_key_set=bool(s.immich_api_key_encrypted),
        skip_confirm=s.immich_skip_confirm,
    )


@api_router.delete("/settings/immich", response_model=schemas.ImmichSettingsOut)
def remove_immich_settings(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    s.immich_url = None
    s.immich_api_key_encrypted = None
    db.commit()
    return schemas.ImmichSettingsOut(url=None, api_key_set=False)


@api_router.post("/immich/test", response_model=schemas.ImmichTestResult)
def test_immich(db: Session = Depends(get_db)):
    """Zeigt Fehler bewusst im Klartext an statt sie zu schlucken - eine
    falsche Adresse oder ein abgelehnter Schlüssel liesse sich sonst nicht
    debuggen (gleiches Muster wie beim Telegram-/Twilio-Test)."""
    s = auth.get_or_create_settings(db)
    if not s.immich_url:
        return schemas.ImmichTestResult(ok=False, error="Keine Server-Adresse hinterlegt.")
    if not s.immich_api_key_encrypted:
        return schemas.ImmichTestResult(ok=False, error="Kein API-Schlüssel hinterlegt.")
    try:
        key = bank_sync.decrypt_secret(s.secret_key, s.immich_api_key_encrypted)
        info = immich.check_connection(s.immich_url, key)
        return schemas.ImmichTestResult(ok=True, **info)
    except Exception as e:
        return schemas.ImmichTestResult(ok=False, error=str(e))


# Eine echte Bibliothek liefert schnell mehrere tausend Gruppen (hier real:
# 5.501 Gruppen / 24.143 Aufnahmen, ~6 MB JSON). Alles auf einmal auszuliefern
# und zu rendern legt den Browser lahm, deshalb seitenweise.
DUPLICATES_PAGE_SIZE = 20
# Einzelne Gruppen sind real bis zu 841 Aufnahmen gross - das sind dann keine
# echten Duplikate mehr, sondern eine Serienaufnahme o.ae. Fuer die Anzeige
# gekuerzt; die Gesamtzahl steht weiterhin in `asset_count`.
MAX_ASSETS_PER_GROUP = 24


@api_router.get("/immich/stats", response_model=schemas.ImmichStatsOut)
def immich_stats(db: Session = Depends(get_db)):
    """Kurzer Überblick über die ganze Bibliothek oben im Fotos-Tab. Braucht
    Admin-Rechte auf Immich-Seite - fehlen die, wird das nicht als Fehler
    behandelt, sondern die Kennzahlen bleiben einfach ausgeblendet."""
    url, key = _immich_credentials(db)
    try:
        stats = immich.server_statistics(url, key)
    except Exception:
        return schemas.ImmichStatsOut(available=False)
    return schemas.ImmichStatsOut(**stats, available=True)


_IMMICH_AI_MAX_IMAGES = 4


@api_router.post("/immich/ai-suggestion", response_model=schemas.ImmichAiSuggestionResult)
def immich_ai_suggestion(data: schemas.ImmichAiSuggestionRequest, db: Session = Depends(get_db)):
    """Lässt das Vision-Modell kurz einschätzen, warum ein Foto zum Aufräumen
    taugt bzw. (bei mehreren Bildern) welches einer Duplikat-Gruppe am besten
    ist. Bewusst rein auf Anfrage (Klick), nie automatisch für ganze Listen -
    ein Vision-Modell pro Bild ist auf bescheidener Hardware langsam, und
    niemand braucht eine KI-Begründung für jedes der hunderten Fotos."""
    settings = auth.get_or_create_settings(db)
    model = settings.beleg_chat_model or settings.ollama_model
    if not settings.ollama_url or not model:
        return schemas.ImmichAiSuggestionResult(error="Bitte zuerst Ollama-Server-URL und Modell in den Einstellungen hinterlegen")
    asset_ids = data.asset_ids[:_IMMICH_AI_MAX_IMAGES]
    if not asset_ids:
        return schemas.ImmichAiSuggestionResult(error="Keine Aufnahme ausgewählt")

    url, key = _immich_credentials(db)
    images = []
    for asset_id in asset_ids:
        try:
            content, _ = immich.fetch_thumbnail(url, key, asset_id, size="preview")
        except Exception as e:
            return schemas.ImmichAiSuggestionResult(error=f"Vorschaubild konnte nicht geladen werden: {e}")
        images.append(base64.b64encode(content).decode())

    if len(images) == 1:
        prompt = (
            "Das ist ein Foto aus einer privaten Fotobibliothek, das als möglicher "
            "Aufräum-Kandidat markiert wurde (z.B. unscharf, wirkt wie Bildschirmfoto "
            "oder Beleg statt Erinnerungsfoto, oder leer/uninteressant). Schätze in "
            "maximal 2 kurzen Sätzen auf Deutsch ein, ob das Foto wirklich zum Löschen "
            "taugt und warum (oder warum nicht, falls es doch ein Erinnerungswert-Foto ist)."
        )
    else:
        labels = ", ".join(f"Bild {i + 1}" for i in range(len(images)))
        prompt = (
            f"Das sind {len(images)} sehr ähnliche Fotos ({labels}) aus einer Duplikat-Gruppe "
            "einer privaten Fotobibliothek. Schätze in maximal 2 kurzen Sätzen auf Deutsch ein, "
            "welches davon (nach Bildnummer) am besten ist (Schärfe, Bildausschnitt, Belichtung) "
            "und damit behalten werden sollte."
        )
    try:
        reply = ollama_client.chat(
            settings.ollama_url, model,
            [{"role": "user", "content": prompt, "images": images}],
            timeout=900,
        )
    except Exception as e:
        return schemas.ImmichAiSuggestionResult(error=str(e))
    return schemas.ImmichAiSuggestionResult(reason=reply[:600])


@api_router.get("/immich/duplicates", response_model=schemas.ImmichDuplicatesOut)
def immich_duplicates(
    offset: int = 0,
    limit: int = DUPLICATES_PAGE_SIZE,
    db: Session = Depends(get_db),
):
    url, key = _immich_credentials(db)
    try:
        raw = immich.list_duplicates(url, key)
    except Exception as e:
        raise HTTPException(502, f"Immich nicht erreichbar oder Schlüssel abgelehnt: {e}")

    # Byte-identische Gruppen (checksum-Duplikate, "100% Übereinstimmung") zuerst,
    # der Rest in Immichs eigener Reihenfolge dahinter - stabil sortiert, damit
    # Gruppen ohne exaktes Duplikat ihre relative Reihenfolge behalten. Das
    # passiert VOR der Seiten-Aufteilung, damit die Sortierung über die ganze
    # Bibliothek gilt und nicht nur innerhalb der gerade geladenen Seite.
    raw.sort(key=lambda g: not immich.has_exact_duplicate(g.get("assets") or []))

    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    total_assets = sum(len(g.get("assets") or []) for g in raw)
    page = raw[offset:offset + limit]

    groups = []
    for g in page:
        all_assets = g.get("assets") or []
        shown = [immich.asset_summary(a) for a in all_assets[:MAX_ASSETS_PER_GROUP]]
        groups.append(schemas.ImmichDuplicateGroupOut(
            duplicate_id=g.get("duplicateId"),
            assets=[schemas.ImmichAssetOut(**a) for a in shown],
            suggested_keep_ids=g.get("suggestedKeepAssetIds") or [],
            asset_count=len(all_assets),
        ))
    # Fehlschlag hier darf die Anzeige nicht blockieren - die Sperre beim
    # tatsächlichen Anwenden greift ohnehin unabhängig davon.
    try:
        trash = immich.trash_config(url, key)
    except Exception:
        trash = {"enabled": True, "days": None}

    return schemas.ImmichDuplicatesOut(
        groups=groups, total_groups=len(raw), total_assets=total_assets,
        trash_enabled=trash["enabled"], trash_days=trash["days"],
        offset=offset, limit=limit, has_more=offset + limit < len(raw),
    )


@api_router.get("/immich/thumbnail/{asset_id}")
def immich_thumbnail(asset_id: str, size: str = "thumbnail", db: Session = Depends(get_db)):
    """Reicht ein Vorschaubild durch, damit der API-Schlüssel den Server nie
    verlässt. Der Browser sieht nur diese eigene Adresse.

    `size=preview` wird von der Lupen-Ansicht genutzt (siehe fetch_thumbnail);
    hier auf die von Immich unterstuetzten Werte eingeschraenkt, weil der
    Parameter direkt vom Browser kommt.
    """
    if size not in ("thumbnail", "preview"):
        raise HTTPException(400, "Ungültige Bildgröße")
    url, key = _immich_credentials(db)
    try:
        content, content_type = immich.fetch_thumbnail(url, key, asset_id, size=size)
    except Exception as e:
        raise HTTPException(502, f"Vorschaubild nicht ladbar: {e}")
    # Kurzer Cache: beim Blättern durch viele Gruppen werden dieselben Bilder
    # sonst mehrfach über den Umweg Server neu geholt.
    return Response(content=content, media_type=content_type,
                    headers={"Cache-Control": "private, max-age=300"})


@api_router.post("/immich/duplicates/resolve", response_model=schemas.ImmichResolveResult)
def immich_resolve(data: schemas.ImmichResolveRequest, db: Session = Depends(get_db)):
    """Wendet die vom Nutzer bestätigte Auswahl an. Bilder wandern in Immichs
    Papierkorb und sind dort wiederherstellbar - endgültiges Löschen passiert
    hier bewusst nie."""
    url, key = _immich_credentials(db)

    # Zuerst prüfen, ob Immichs Papierkorb überhaupt aktiv ist. Immich
    # entscheidet anhand dieser Server-Einstellung, ob aussortierte Bilder
    # wiederherstellbar bleiben oder sofort unwiderruflich weg sind - der
    # Aufruf von hier sieht in beiden Fällen identisch aus. Ohne diese Prüfung
    # würde ein Umlegen des Schalters in Immich diese Funktion still von
    # "aufräumen" zu "endgültig vernichten" machen.
    try:
        trash = immich.trash_config(url, key)
    except Exception as e:
        raise HTTPException(502, f"Papierkorb-Einstellung nicht prüfbar, abgebrochen: {e}")
    if not trash["enabled"]:
        raise HTTPException(
            400,
            "Abgebrochen: In Immich ist der Papierkorb abgeschaltet. Aussortierte "
            "Bilder wären sofort unwiderruflich gelöscht statt wiederherstellbar. "
            "Aktiviere den Papierkorb in Immich (Administration → Einstellungen → "
            "Papierkorb), dann klappt es. Es wurde nichts geändert.",
        )

    payload = []
    for g in data.groups:
        # Schutz gegen einen Bedienfehler oder einen Fehler im Frontend: eine
        # Gruppe, in der ALLES weggeworfen wird, ist immer ein Versehen - der
        # Sinn ist, genau ein Bild zu behalten.
        # Kein Zwang mehr zu "mindestens ein Bild bleibt" - der Nutzer soll
        # bewusst auch eine ganze Gruppe leeren koennen, wenn keine der
        # Aufnahmen etwas taugt. Immichs eigene Pruefung verlangt nur, dass
        # jedes Bild in GENAU einer der beiden Listen steht (siehe Overlap-
        # Pruefung gleich darunter) - eine leere keep_ids-Liste ist dafuer
        # bereits gueltig.
        overlap = set(g.keep_ids) & set(g.trash_ids)
        if overlap:
            raise HTTPException(
                400,
                "Ein Bild wurde gleichzeitig zum Behalten und zum Wegwerfen markiert. "
                "Abgebrochen, es wurde nichts geändert.",
            )
        payload.append({
            "duplicateId": g.duplicate_id,
            "keepAssetIds": g.keep_ids,
            "trashAssetIds": g.trash_ids,
        })

    try:
        immich.resolve_duplicates(url, key, payload)
    except Exception as e:
        raise HTTPException(502, f"Immich hat die Änderung abgelehnt: {e}")

    return schemas.ImmichResolveResult(
        resolved_groups=len(payload),
        trashed_assets=sum(len(g.trash_ids) for g in data.groups),
    )


# Ähnlichkeit nur für überschaubare Gruppen rechnen: jedes Bild muss dafür
# einmal geladen werden. Bei den real vorkommenden Riesengruppen (bis 841
# Aufnahmen) wären das hunderte Abrufe für eine Zahl, die dort ohnehin nichts
# aussagt - solche Gruppen sind keine echten Duplikate.
MAX_ASSETS_FOR_SIMILARITY = 12


@api_router.get("/immich/duplicates/{duplicate_id}/similarity",
                response_model=schemas.ImmichSimilarityOut)
def immich_similarity(duplicate_id: str, asset_ids: str, db: Session = Depends(get_db)):
    """Rechnet aus, wie stark sich die Bilder einer Gruppe gleichen.

    `asset_ids` (kommagetrennt) kommt vom Frontend mit, das die Liste aus der
    ohnehin schon geladenen Gruppe kennt. Frueher wurde hier stattdessen bei
    JEDER Anfrage Immichs komplette Duplikat-Liste neu abgerufen, nur um darin
    die eine gesuchte Gruppe wiederzufinden - bei einer grossen Bibliothek
    (real: 5.500 Gruppen, mehrere MB) macht das 20 Anfragen pro Seite 20 volle
    Neuabrufe. Das legte den Server bei jedem Seitenaufruf spuerbar lahm und
    liess Anfragen haengen bleiben - im Browser sichtbar als voellig
    unzusammenhaengend wirkender Fehler ("access control checks" in Safari
    fuer eine schlicht zu langsam gewordene Verbindung)."""
    ids = [i for i in asset_ids.split(",") if i]
    if not ids:
        raise HTTPException(400, "Keine Bild-IDs übergeben.")
    url, key = _immich_credentials(db)
    if len(ids) > MAX_ASSETS_FOR_SIMILARITY:
        return schemas.ImmichSimilarityOut(
            duplicate_id=duplicate_id, pairs={},
            error=f"Zu viele Aufnahmen ({len(ids)}) für einen sinnvollen Vergleich.",
        )

    hashes = {}
    fehler = []
    for asset_id in ids:
        try:
            hashes[asset_id] = immich.asset_hash(url, key, asset_id)
        except Exception as e:
            # Ein einzelnes nicht ladbares Bild darf die Gruppe nicht
            # unbrauchbar machen - aber der Grund muss sichtbar bleiben.
            # Vorher wurde hier stillschweigend weitergemacht, wodurch ein
            # nicht lesbares Bildformat als "leeres Ergebnis ohne Fehler"
            # ankam und wie ein Anzeigefehler aussah.
            fehler.append(f"{type(e).__name__}: {e}")

    pairs = {
        a: {b: immich.similarity_percent(hashes[a], hashes[b])
            for b in hashes if b != a}
        for a in hashes
    }
    err = None
    if fehler:
        err = f"{len(fehler)} von {len(ids)} Bildern nicht vergleichbar ({fehler[0][:80]})"
    return schemas.ImmichSimilarityOut(duplicate_id=duplicate_id, pairs=pairs, error=err)


SCREENSHOT_PAGE_SIZE = 60


@api_router.get("/immich/screenshots", response_model=schemas.ImmichScreenshotsOut)
def immich_screenshots(
    older_than_months: int = 0,
    offset: int = 0,
    limit: int = SCREENSHOT_PAGE_SIZE,
    db: Session = Depends(get_db),
):
    """Listet Bildschirmfotos, optional nur solche ab einem gewissen Alter."""
    url, key = _immich_credentials(db)
    try:
        raw = immich.find_screenshots(url, key)
    except Exception as e:
        raise HTTPException(502, f"Immich nicht erreichbar oder Schlüssel abgelehnt: {e}")

    def taken(a: dict) -> str:
        return a.get("fileCreatedAt") or ""

    # Altersverteilung immer über den kompletten Bestand rechnen, nicht über
    # die gefilterte Auswahl - sonst zeigt die Übersicht nur sich selbst.
    heute = date.today()
    by_age = {"6m": 0, "1j": 0, "2j": 0, "alle": len(raw)}
    for a in raw:
        d = taken(a)[:10]
        if not d:
            continue
        try:
            alter_tage = (heute - date.fromisoformat(d)).days
        except ValueError:
            continue
        if alter_tage >= 180:
            by_age["6m"] += 1
        if alter_tage >= 365:
            by_age["1j"] += 1
        if alter_tage >= 730:
            by_age["2j"] += 1

    gefiltert = raw
    if older_than_months > 0:
        grenze = heute - timedelta(days=int(older_than_months * 30.44))
        gefiltert = [a for a in raw
                     if taken(a)[:10] and taken(a)[:10] < grenze.isoformat()]

    # Älteste zuerst - die sind am ehesten entbehrlich.
    gefiltert.sort(key=taken)

    total_size = sum((a.get("exifInfo") or {}).get("fileSizeInByte") or 0 for a in gefiltert)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    page = gefiltert[offset:offset + limit]

    try:
        trash = immich.trash_config(url, key)
    except Exception:
        trash = {"enabled": True, "days": None}

    return schemas.ImmichScreenshotsOut(
        assets=[schemas.ImmichAssetOut(**immich.asset_summary(a)) for a in page],
        total=len(gefiltert),
        total_size_bytes=total_size,
        by_age=by_age,
        offset=offset, limit=limit, has_more=offset + limit < len(gefiltert),
        trash_enabled=trash["enabled"], trash_days=trash["days"],
    )


@api_router.post("/immich/screenshots/trash", response_model=schemas.ImmichTrashResult)
def immich_trash_screenshots(data: schemas.ImmichTrashRequest, db: Session = Depends(get_db)):
    """Verschiebt ausgewählte Bildschirmfotos in Immichs Papierkorb."""
    url, key = _immich_credentials(db)
    if not data.asset_ids:
        raise HTTPException(400, "Es wurde nichts ausgewählt.")

    # Gleiche Sperre wie beim Auflösen von Duplikaten. Hier zusätzlich
    # abgesichert dadurch, dass `trash_assets` `force=False` fest setzt - aber
    # ein abgeschalteter Papierkorb hiesse, dass Immich das Weggeworfene sofort
    # endgültig entsorgt, und dann soll dieser Weg gar nicht erst offenstehen.
    try:
        trash = immich.trash_config(url, key)
    except Exception as e:
        raise HTTPException(502, f"Papierkorb-Einstellung nicht prüfbar, abgebrochen: {e}")
    if not trash["enabled"]:
        raise HTTPException(
            400,
            "Abgebrochen: In Immich ist der Papierkorb abgeschaltet. Aussortierte "
            "Bilder wären sofort unwiderruflich gelöscht. Es wurde nichts geändert.",
        )

    # Nur echte Bildschirmfotos annehmen. Ohne diese Prüfung könnte über diesen
    # Endpunkt jedes beliebige Bild der Bibliothek weggeworfen werden - die IDs
    # kommen schliesslich aus dem Browser.
    try:
        erlaubt = {a["id"]: a for a in immich.find_screenshots(url, key)}
    except Exception as e:
        raise HTTPException(502, f"Abgleich mit Immich fehlgeschlagen: {e}")
    unbekannt = [i for i in data.asset_ids if i not in erlaubt]
    if unbekannt:
        raise HTTPException(
            400,
            f"{len(unbekannt)} der ausgewählten Bilder sind keine Bildschirmfotos. "
            "Abgebrochen, es wurde nichts geändert.",
        )

    freed = sum((erlaubt[i].get("exifInfo") or {}).get("fileSizeInByte") or 0
                for i in data.asset_ids)
    try:
        immich.trash_assets(url, key, data.asset_ids)
    except Exception as e:
        raise HTTPException(502, f"Immich hat die Änderung abgelehnt: {e}")
    return schemas.ImmichTrashResult(trashed=len(data.asset_ids), freed_bytes=freed)


PHOTOS_PAGE_SIZE = 60


@api_router.get("/immich/photos", response_model=schemas.ImmichPhotosOut)
def immich_photos(offset: int = 0, limit: int = PHOTOS_PAGE_SIZE, shuffle: bool = False, db: Session = Depends(get_db)):
    """Blaettert ohne jeden Filter durch die gesamte Bibliothek - fuer den
    Swipe-Modus 'Alle Fotos', der bewusst nicht wie Screenshots/Unschaerfe auf
    einen engeren Kandidaten-Ausschnitt beschraenkt ist, sondern wirklich jedes
    Foto zeigt."""
    url, key = _immich_credentials(db)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    if shuffle:
        # Immich kennt keine "random"-Sortierung (nur asc/desc) - stattdessen
        # bei jedem Aufruf eine zufaellige Seite aus der ganzen Bibliothek
        # ziehen und ihren Inhalt zusaetzlich mischen. Das offset-Argument wird
        # hier bewusst ignoriert (jeder Aufruf ist unabhaengig "zufaellig"),
        # has_more bleibt True - es gibt kein Ende, nur den naechsten Zufallsgriff.
        try:
            total = max(1, immich.server_statistics(url, key).get("photos", 0))
        except Exception:
            total = 1
        page_num = random.randint(1, max(1, (total + limit - 1) // limit))
    else:
        # Immichs eigene Seitenzaehlung ist 1-basiert und pro Seite fest an `limit`
        # gebunden - offset muss daher ein Vielfaches von limit sein. Das ist die
        # einzige Art, wie das Frontend diesen Endpunkt tatsaechlich aufruft
        # (0, 60, 120, ... - siehe SWIPE_CONFIG).
        page_num = offset // limit + 1
    try:
        raw, has_more = immich.list_assets_page(url, key, page_num, size=limit)
    except Exception as e:
        raise HTTPException(502, f"Immich nicht erreichbar oder Schlüssel abgelehnt: {e}")
    if shuffle:
        random.shuffle(raw)
        has_more = True
    try:
        trash = immich.trash_config(url, key)
    except Exception:
        trash = {"enabled": True, "days": None}
    return schemas.ImmichPhotosOut(
        assets=[schemas.ImmichAssetOut(**immich.asset_summary(a)) for a in raw],
        offset=offset, limit=limit, has_more=has_more,
        trash_enabled=trash["enabled"], trash_days=trash["days"],
    )


@api_router.post("/immich/photos/trash", response_model=schemas.ImmichTrashResult)
def immich_trash_photos(data: schemas.ImmichTrashRequest, db: Session = Depends(get_db)):
    """Wirft Fotos aus dem Swipe-Modus 'Alle Fotos' weg. Anders als bei
    Screenshots/Unschaerfe gibt es hier keinen engeren Kandidatenkreis, gegen
    den sich die IDs serverseitig gegenpruefen liessen - jedes Foto der
    Bibliothek ist hier ein gueltiges Ziel, genau wie beim Aufloesen einer
    Duplikat-Gruppe."""
    url, key = _immich_credentials(db)
    if not data.asset_ids:
        raise HTTPException(400, "Es wurde nichts ausgewählt.")
    try:
        trash = immich.trash_config(url, key)
    except Exception as e:
        raise HTTPException(502, f"Papierkorb-Einstellung nicht prüfbar, abgebrochen: {e}")
    if not trash["enabled"]:
        raise HTTPException(
            400,
            "Abgebrochen: In Immich ist der Papierkorb abgeschaltet. Aussortierte "
            "Bilder wären sofort unwiderruflich gelöscht. Es wurde nichts geändert.",
        )
    try:
        immich.trash_assets(url, key, data.asset_ids)
    except Exception as e:
        raise HTTPException(502, f"Immich hat die Änderung abgelehnt: {e}")
    return schemas.ImmichTrashResult(trashed=len(data.asset_ids), freed_bytes=0)


QUALITY_PAGE_SIZE = 60


@api_router.get("/immich/quality", response_model=schemas.ImmichQualityOut)
def immich_quality(offset: int = 0, limit: int = QUALITY_PAGE_SIZE, reason: str = "", db: Session = Depends(get_db)):
    """Listet vom Hintergrund-Scan erkannte unscharfe/leere Fotos.

    Liest aus dem lokalen Zwischenspeicher (immich_quality_flags), nicht live
    aus Immich - bei ~24.000 Fotos waere ein Scan bei jedem Seitenaufruf viel
    zu langsam. Siehe _scheduled_immich_quality_scan für den Hintergrund-Job.
    """
    url, key = _immich_credentials(db)
    alle = db.query(models.ImmichQualityFlag).filter(models.ImmichQualityFlag.dismissed.is_(False)).all()

    by_reason: dict[str, int] = {}
    for f in alle:
        by_reason[f.reason] = by_reason.get(f.reason, 0) + 1

    # Nach Grund filtern, BEVOR die Seite geschnitten wird - sonst waere die
    # Zaehlung "wie viele Seiten gibt es" beim Filtern falsch.
    gefiltert = [f for f in alle if not reason or f.reason == reason]
    total_size = sum(f.size_bytes or 0 for f in gefiltert)

    # Neueste zuerst - bei unscharfen/leeren Fotos ist kein "Alter" wie bei
    # Screenshots ausschlaggebend, sondern schlicht, dass sie ueberhaupt
    # gefunden wurden.
    gefiltert.sort(key=lambda f: f.scanned_at, reverse=True)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    page = gefiltert[offset:offset + limit]

    try:
        trash = immich.trash_config(url, key)
    except Exception:
        trash = {"enabled": True, "days": None}
    settings = auth.get_or_create_settings(db)

    return schemas.ImmichQualityOut(
        assets=[schemas.ImmichQualityAssetOut(
            id=f.asset_id, file_name=f.file_name, created_at=f.created_at_immich,
            size_bytes=f.size_bytes, width=f.width, height=f.height,
            reason=f.reason, score=f.score,
        ) for f in page],
        total=len(gefiltert), total_size_bytes=total_size, by_reason=by_reason,
        offset=offset, limit=limit, has_more=offset + limit < len(gefiltert),
        trash_enabled=trash["enabled"], trash_days=trash["days"],
        scan_page=settings.immich_quality_scan_page,
    )


@api_router.post("/immich/quality/trash", response_model=schemas.ImmichTrashResult)
def immich_trash_quality(data: schemas.ImmichTrashRequest, db: Session = Depends(get_db)):
    """Verschiebt ausgewählte unscharfe/leere Fotos in Immichs Papierkorb."""
    url, key = _immich_credentials(db)
    if not data.asset_ids:
        raise HTTPException(400, "Es wurde nichts ausgewählt.")

    try:
        trash = immich.trash_config(url, key)
    except Exception as e:
        raise HTTPException(502, f"Papierkorb-Einstellung nicht prüfbar, abgebrochen: {e}")
    if not trash["enabled"]:
        raise HTTPException(
            400,
            "Abgebrochen: In Immich ist der Papierkorb abgeschaltet. Aussortierte "
            "Bilder wären sofort unwiderruflich gelöscht. Es wurde nichts geändert.",
        )

    # Nur Fotos annehmen, die der eigene Scan tatsächlich markiert hat - die
    # IDs kommen aus dem Browser und duerfen nicht ungeprueft an Immich
    # weitergereicht werden.
    erlaubt = {
        f.asset_id: f for f in db.query(models.ImmichQualityFlag)
        .filter(models.ImmichQualityFlag.asset_id.in_(data.asset_ids)).all()
    }
    unbekannt = [i for i in data.asset_ids if i not in erlaubt]
    if unbekannt:
        raise HTTPException(
            400,
            f"{len(unbekannt)} der ausgewählten Bilder sind nicht als unnötig markiert. "
            "Abgebrochen, es wurde nichts geändert.",
        )

    freed = sum(erlaubt[i].size_bytes or 0 for i in data.asset_ids)
    try:
        immich.trash_assets(url, key, data.asset_ids)
    except Exception as e:
        raise HTTPException(502, f"Immich hat die Änderung abgelehnt: {e}")

    for i in data.asset_ids:
        db.delete(erlaubt[i])
    db.commit()
    return schemas.ImmichTrashResult(trashed=len(data.asset_ids), freed_bytes=freed)


@api_router.delete("/immich/quality/{asset_id}")
def immich_dismiss_quality(asset_id: str, db: Session = Depends(get_db)):
    """Blendet ein Foto aus der Liste aus, ohne es anzufassen ("ist doch okay")."""
    flag = db.query(models.ImmichQualityFlag).filter(models.ImmichQualityFlag.asset_id == asset_id).first()
    if not flag:
        raise HTTPException(404, "Nicht gefunden.")
    flag.dismissed = True
    db.commit()
    return {"ok": True}


@api_router.get("/immich/people", response_model=schemas.ImmichPeopleOut)
def immich_people(db: Session = Depends(get_db)):
    """Benannte Personen aus Immichs eigener Gesichtserkennung, als weiterer
    Filter zum gezielten Aufräumen ("alle Fotos von X ansehen")."""
    url, key = _immich_credentials(db)
    try:
        people = immich.list_people(url, key)
    except Exception as e:
        raise HTTPException(502, f"Immich nicht erreichbar oder Schlüssel abgelehnt: {e}")
    return schemas.ImmichPeopleOut(people=[schemas.ImmichPersonOut(**p) for p in people])


@api_router.get("/immich/people/{person_id}/thumbnail")
def immich_person_thumbnail(person_id: str, db: Session = Depends(get_db)):
    url, key = _immich_credentials(db)
    try:
        content, content_type = immich.fetch_person_thumbnail(url, key, person_id)
    except Exception as e:
        raise HTTPException(502, f"Immich nicht erreichbar: {e}")
    return Response(content=content, media_type=content_type)


@api_router.get("/immich/people/{person_id}/assets", response_model=schemas.ImmichPersonAssetsOut)
def immich_person_assets(person_id: str, page: int = 1, db: Session = Depends(get_db)):
    url, key = _immich_credentials(db)
    try:
        items, has_more = immich.person_assets(url, key, person_id, page)
    except Exception as e:
        raise HTTPException(502, f"Immich nicht erreichbar oder Schlüssel abgelehnt: {e}")
    try:
        trash = immich.trash_config(url, key)
    except Exception:
        trash = {"enabled": True, "days": None}
    return schemas.ImmichPersonAssetsOut(
        assets=[schemas.ImmichAssetOut(**immich.asset_summary(a)) for a in items],
        page=page, has_more=has_more,
        trash_enabled=trash["enabled"], trash_days=trash["days"],
    )


@api_router.post("/immich/people/{person_id}/trash", response_model=schemas.ImmichTrashResult)
def immich_trash_person_assets(person_id: str, data: schemas.ImmichTrashRequest, db: Session = Depends(get_db)):
    """Verschiebt ausgewählte Fotos einer Person in Immichs Papierkorb."""
    url, key = _immich_credentials(db)
    if not data.asset_ids:
        raise HTTPException(400, "Es wurde nichts ausgewählt.")

    try:
        trash = immich.trash_config(url, key)
    except Exception as e:
        raise HTTPException(502, f"Papierkorb-Einstellung nicht prüfbar, abgebrochen: {e}")
    if not trash["enabled"]:
        raise HTTPException(
            400,
            "Abgebrochen: In Immich ist der Papierkorb abgeschaltet. Aussortierte "
            "Bilder wären sofort unwiderruflich gelöscht. Es wurde nichts geändert.",
        )

    # Wie bei den Screenshots: nur IDs annehmen, die wirklich zu dieser Person
    # gehören - die IDs kommen aus dem Browser und dürfen nicht ungeprüft an
    # Immich weitergereicht werden. Dafür alle Seiten der Person durchsuchen.
    erlaubt: dict[str, dict] = {}
    page = 1
    while True:
        try:
            items, has_more = immich.person_assets(url, key, person_id, page)
        except Exception as e:
            raise HTTPException(502, f"Abgleich mit Immich fehlgeschlagen: {e}")
        for a in items:
            erlaubt[a["id"]] = a
        if not has_more or set(data.asset_ids) <= set(erlaubt):
            break
        page += 1
    unbekannt = [i for i in data.asset_ids if i not in erlaubt]
    if unbekannt:
        raise HTTPException(
            400,
            f"{len(unbekannt)} der ausgewählten Bilder gehören nicht zu dieser Person. "
            "Abgebrochen, es wurde nichts geändert.",
        )

    freed = sum((erlaubt[i].get("exifInfo") or {}).get("fileSizeInByte") or 0 for i in data.asset_ids)
    try:
        immich.trash_assets(url, key, data.asset_ids)
    except Exception as e:
        raise HTTPException(502, f"Immich hat die Änderung abgelehnt: {e}")
    return schemas.ImmichTrashResult(trashed=len(data.asset_ids), freed_bytes=freed)


@api_router.delete("/immich/duplicates/{duplicate_id}")
def immich_dismiss(duplicate_id: str, db: Session = Depends(get_db)):
    """Gruppe ausblenden, ohne ein Bild anzufassen."""
    url, key = _immich_credentials(db)
    try:
        immich.dismiss_duplicate(url, key, duplicate_id)
    except Exception as e:
        raise HTTPException(502, f"Immich hat die Änderung abgelehnt: {e}")
    return {"ok": True}


# Ergebnis kurz zwischenspeichern - dieser Endpunkt wird bei jedem Seitenaufruf
# abgefragt, ein anonymer GHCR-Blick fuer jeden davon waere unnoetig und bei
# vielen Tabs/Nutzern schnell spuerbar langsam.
_latest_version_cache: dict = {"checked_at": None, "result": None}
GHCR_IMAGE = "tim-stubbe/finance-app"


def _fetch_latest_published_sha() -> schemas.LatestVersionOut:
    """Fragt anonym bei ghcr.io nach dem git-SHA-Label des aktuell
    veroeffentlichten :latest-Images. Braucht dafuer, dass das Paket wirklich
    oeffentlich ist (siehe Docker-LABEL im Dockerfile) - ist es das (noch)
    nicht, kommt sauber `available=False` zurueck statt eines Fehlers, der wie
    ein Problem im eigenen System aussehen wuerde."""
    try:
        token_resp = requests.get(
            "https://ghcr.io/token",
            params={"service": "ghcr.io", "scope": f"repository:{GHCR_IMAGE}:pull"},
            timeout=5,
        )
        token = token_resp.json().get("token") if token_resp.ok else None
        if not token:
            return schemas.LatestVersionOut(available=False, error="Paket nicht öffentlich abrufbar")

        manifest_headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.docker.distribution.manifest.v2+json, "
                      "application/vnd.docker.distribution.manifest.list.v2+json, "
                      "application/vnd.oci.image.manifest.v1+json, "
                      "application/vnd.oci.image.index.v1+json",
        }
        manifest_resp = requests.get(
            f"https://ghcr.io/v2/{GHCR_IMAGE}/manifests/latest",
            headers=manifest_headers, timeout=5,
        )
        manifest_resp.raise_for_status()
        manifest = manifest_resp.json()

        # Multi-Architektur-Image: das docker-publish.yml-Buildx baut fuer
        # mehrere Plattformen, "latest" zeigt deshalb auf eine Index-Liste statt
        # direkt auf ein einzelnes Manifest - amd64 heraussuchen (das laeuft auf
        # der TrueNAS-Box).
        if "manifests" in manifest:
            eintrag = next(
                (m for m in manifest["manifests"]
                 if m.get("platform", {}).get("architecture") == "amd64"),
                manifest["manifests"][0],
            )
            manifest_resp = requests.get(
                f"https://ghcr.io/v2/{GHCR_IMAGE}/manifests/{eintrag['digest']}",
                headers=manifest_headers, timeout=5,
            )
            manifest_resp.raise_for_status()
            manifest = manifest_resp.json()

        config_digest = manifest["config"]["digest"]

        config_resp = requests.get(
            f"https://ghcr.io/v2/{GHCR_IMAGE}/blobs/{config_digest}",
            headers={"Authorization": f"Bearer {token}"}, timeout=5,
        )
        config_resp.raise_for_status()
        sha = config_resp.json().get("config", {}).get("Labels", {}).get(
            "org.opencontainers.image.revision")
        if not sha:
            return schemas.LatestVersionOut(available=False, error="Kein Revisions-Label im Image")
        return schemas.LatestVersionOut(available=True, git_sha=sha, git_sha_short=sha[:7])
    except Exception as e:
        return schemas.LatestVersionOut(available=False, error=str(e))


@api_router.get("/version/latest", response_model=schemas.LatestVersionOut)
def get_latest_version():
    now = datetime.utcnow()
    if (_latest_version_cache["checked_at"]
            and now - _latest_version_cache["checked_at"] < timedelta(minutes=10)):
        return _latest_version_cache["result"]
    result = _fetch_latest_published_sha()
    _latest_version_cache["checked_at"] = now
    _latest_version_cache["result"] = result
    return result


@api_router.get("/version", response_model=schemas.VersionOut)
def get_version():
    """Welcher Stand tatsächlich läuft - unabhängig davon, ob ein Update
    (Watchtower oder manuell) wirklich angekommen ist oder ob eine sichtbare
    Änderung schlicht an einem alten, nicht aktualisierten Container liegt."""
    sha = os.environ.get("GIT_SHA", "dev")
    return schemas.VersionOut(
        git_sha=sha,
        git_sha_short=sha[:7],
        build_date=os.environ.get("BUILD_DATE") or None,
    )


# ---------------- Einrichtungsstatus der Anbindungen ----------------
@api_router.get("/integrations/status", response_model=schemas.IntegrationStatusOut)
def integrations_status(db: Session = Depends(get_db)):
    """Zeigt, welche Anbindungen einsatzbereit sind und welche noch Zugangsdaten
    brauchen. Bewusst nur eine Prüfung der hinterlegten Einstellungen, kein
    Verbindungstest: die Übersicht wird bei jedem Seitenaufruf geladen und darf
    nicht auf externen Servern hängen bleiben."""
    s = auth.get_or_create_settings(db)

    # Anzahl der Pflichtfelder je Anbindung. Fehlen alle, ist die Anbindung gar
    # nicht eingerichtet ("missing"); fehlen nur einzelne, wurde sie angefangen
    # ("partial") - das ist der Fall, den man beim Einrichten leicht übersieht.
    FIELD_COUNT = {
        "ollama": 2, "telegram": 2, "twilio": 4, "brave": 1,
        "fints": 2, "enablebanking": 3, "bitvavo": 1, "paypal": 1,
        "immich": 2, "mail": 3, "ebay": 3, "radicale": 2,
    }

    def entry(key, name, purpose, missing, optional=True, enabled=True, detail_ok=""):
        if missing:
            status = "missing" if len(missing) >= FIELD_COUNT[key] else "partial"
        elif not enabled:
            status = "off"
        else:
            status = "ok"
        detail = {
            "ok": detail_ok or "Einsatzbereit.",
            "off": "Vollständig eingerichtet, aber abgeschaltet.",
            "partial": "Angefangen, aber noch nicht nutzbar.",
            "missing": "Noch nicht eingerichtet.",
        }[status]
        return schemas.IntegrationStatusItem(
            key=key, name=name, purpose=purpose, status=status,
            detail=detail, missing=missing, optional=optional,
        )

    items = []

    missing = []
    if not s.ollama_url:
        missing.append("Server-Adresse")
    if not s.ollama_model:
        missing.append("Modell")
    items.append(entry(
        "ollama", "Ollama (KI)",
        "KI-Chat, automatische Kategorisierung, Beleg-Auswertung, Antworten des Telegram-Bots",
        missing, optional=False,
    ))

    missing = []
    if not s.telegram_bot_token_encrypted:
        missing.append("Bot-Token")
    if not s.telegram_chat_id:
        missing.append("Chat-ID")
    items.append(entry(
        "telegram", "Telegram",
        "Benachrichtigungen zu Zielen, Cashflow und Budgets; Fragen per Chat",
        missing, enabled=s.notifications_enabled,
    ))

    missing = [label for label, value in (
        ("Account SID", s.twilio_account_sid),
        ("Auth-Token", s.twilio_auth_token_encrypted),
        ("Absendernummer", s.twilio_from_number),
        ("Zielnummer", s.twilio_to_number),
    ) if not value]
    items.append(entry(
        "twilio", "Twilio (Anrufe)",
        "Echte Anrufe bei zeitkritischen Lagen – kostenpflichtig",
        missing, enabled=s.calls_enabled,
    ))

    items.append(entry(
        "brave", "Brave Search",
        "Websuche im KI-Chat",
        [] if s.brave_search_api_key_encrypted else ["API-Schlüssel"],
    ))

    missing = []
    if not s.fints_product_id:
        missing.append("Produkt-ID")
    if db.query(models.BankConnection).count() == 0:
        missing.append("mindestens eine Bank-Verbindung")
    items.append(entry(
        "fints", "Bank (FinTS)",
        "Umsätze deutscher Banken automatisch abholen",
        missing,
    ))

    missing = []
    if not s.enablebanking_app_id:
        missing.append("Anwendungs-ID")
    if not s.enablebanking_private_key_encrypted:
        missing.append("Privater Schlüssel")
    if db.query(models.EnableBankingConnection).count() == 0:
        missing.append("mindestens eine Verbindung")
    items.append(entry(
        "enablebanking", "Enable Banking (PSD2)",
        "Banken ohne FinTS anbinden",
        missing,
    ))

    n_bitvavo = db.query(models.BitvavoConnection).count()
    items.append(entry(
        "bitvavo", "Bitvavo",
        "Krypto-Bestände automatisch abgleichen",
        [] if n_bitvavo else ["mindestens eine Verbindung"],
        detail_ok=f"{n_bitvavo} Verbindung{'en' if n_bitvavo != 1 else ''} eingerichtet.",
    ))

    n_paypal = db.query(models.PayPalConnection).count()
    items.append(entry(
        "paypal", "PayPal",
        "PayPal-Umsätze automatisch abholen",
        [] if n_paypal else ["mindestens eine Verbindung"],
        detail_ok=f"{n_paypal} Verbindung{'en' if n_paypal != 1 else ''} eingerichtet.",
    ))

    missing = []
    if not s.ebay_app_id:
        missing.append("App-ID")
    if not s.ebay_cert_id_encrypted:
        missing.append("Cert-ID")
    if not s.ebay_ru_name:
        missing.append("RuName")
    n_ebay = db.query(models.EbayConnection).filter(models.EbayConnection.status == "connected").count()
    if not missing and n_ebay == 0:
        missing.append("mindestens eine Verbindung")
    items.append(entry(
        "ebay", "eBay",
        "Verkäufe wie ein Konto einbinden",
        missing,
        detail_ok=f"{n_ebay} Verbindung{'en' if n_ebay != 1 else ''} verbunden." if n_ebay else None,
    ))

    missing = []
    if not s.radicale_url:
        missing.append("Server-Adresse")
    if not s.radicale_password_encrypted:
        missing.append("Zugangsdaten")
    n_todos = db.query(models.Todo).count()
    items.append(entry(
        "radicale", "To-Dos (Radicale)",
        "To-Dos zweiseitig mit dem Handy synchronisieren",
        missing,
        detail_ok=f"{n_todos} To-Do{'s' if n_todos != 1 else ''} synchronisiert." if n_todos else None,
    ))

    missing = []
    if not s.immich_url:
        missing.append("Server-Adresse")
    if not s.immich_api_key_encrypted:
        missing.append("API-Schlüssel")
    items.append(entry(
        "immich", "Immich (Fotos)",
        "Doppelte Fotos finden und nach Bestätigung aufräumen",
        missing,
    ))

    missing = [label for label, value in (
        ("IMAP-Server", s.imap_host),
        ("Benutzername", s.imap_user),
        ("Passwort", s.imap_password_encrypted),
    ) if not value]
    items.append(entry(
        "mail", "E-Mail-Postfach",
        "Belege aus Anhängen holen und Buchungen zuordnen",
        missing, enabled=s.mail_enabled,
    ))

    return schemas.IntegrationStatusOut(
        items=items,
        ready=sum(1 for i in items if i.status == "ok"),
        incomplete=sum(1 for i in items if i.status in ("missing", "partial")),
    )


# ---------------- Benachrichtigungen (Telegram) ----------------
@api_router.get("/settings/notifications", response_model=schemas.NotificationSettingsOut)
def get_notification_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.NotificationSettingsOut(
        enabled=settings.notifications_enabled,
        telegram_configured=bool(settings.telegram_bot_token_encrypted and settings.telegram_chat_id),
    )


@api_router.put("/settings/notifications", response_model=schemas.NotificationSettingsOut)
def update_notification_settings(data: schemas.NotificationSettingsUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.notifications_enabled = data.enabled
    if data.telegram_bot_token:
        settings.telegram_bot_token_encrypted = bank_sync.encrypt_secret(settings.secret_key, data.telegram_bot_token)
    if data.telegram_chat_id:
        settings.telegram_chat_id = data.telegram_chat_id.strip()
    db.commit()
    return schemas.NotificationSettingsOut(
        enabled=settings.notifications_enabled,
        telegram_configured=bool(settings.telegram_bot_token_encrypted and settings.telegram_chat_id),
    )


@api_router.delete("/settings/notifications/telegram", response_model=schemas.NotificationSettingsOut)
def remove_telegram_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.telegram_bot_token_encrypted = None
    settings.telegram_chat_id = None
    db.commit()
    return schemas.NotificationSettingsOut(enabled=settings.notifications_enabled, telegram_configured=False)


@api_router.post("/notifications/test", response_model=schemas.NotificationTestResult)
def send_test_notification(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    if not settings.telegram_bot_token_encrypted or not settings.telegram_chat_id:
        return schemas.NotificationTestResult(ok=False, message="Bot-Token und Chat-ID zuerst speichern.")
    try:
        token = bank_sync.decrypt_secret(settings.secret_key, settings.telegram_bot_token_encrypted)
        notifications.send_telegram(token, settings.telegram_chat_id, "🔔 Testnachricht von Kies - Telegram ist korrekt eingerichtet.")
    except Exception as e:
        return schemas.NotificationTestResult(ok=False, message=f"Fehlgeschlagen: {e}")
    return schemas.NotificationTestResult(ok=True, message="Gesendet - schau in Telegram nach.")


# ---------------- Echte Anrufe (Twilio) für akute Fälle ----------------
@api_router.get("/settings/calls", response_model=schemas.CallSettingsOut)
def get_call_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.CallSettingsOut(
        enabled=settings.calls_enabled,
        twilio_configured=bool(
            settings.twilio_account_sid and settings.twilio_auth_token_encrypted
            and settings.twilio_from_number and settings.twilio_to_number
        ),
    )


@api_router.put("/settings/calls", response_model=schemas.CallSettingsOut)
def update_call_settings(data: schemas.CallSettingsUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.calls_enabled = data.enabled
    if data.twilio_account_sid:
        settings.twilio_account_sid = data.twilio_account_sid.strip()
    if data.twilio_auth_token:
        settings.twilio_auth_token_encrypted = bank_sync.encrypt_secret(settings.secret_key, data.twilio_auth_token)
    if data.twilio_from_number:
        settings.twilio_from_number = data.twilio_from_number.strip()
    if data.twilio_to_number:
        settings.twilio_to_number = data.twilio_to_number.strip()
    db.commit()
    return schemas.CallSettingsOut(
        enabled=settings.calls_enabled,
        twilio_configured=bool(
            settings.twilio_account_sid and settings.twilio_auth_token_encrypted
            and settings.twilio_from_number and settings.twilio_to_number
        ),
    )


@api_router.delete("/settings/calls/twilio", response_model=schemas.CallSettingsOut)
def remove_twilio_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.twilio_account_sid = None
    settings.twilio_auth_token_encrypted = None
    settings.twilio_from_number = None
    settings.twilio_to_number = None
    db.commit()
    return schemas.CallSettingsOut(enabled=settings.calls_enabled, twilio_configured=False)


@api_router.post("/calls/test", response_model=schemas.NotificationTestResult)
def send_test_call(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    if not (settings.twilio_account_sid and settings.twilio_auth_token_encrypted
            and settings.twilio_from_number and settings.twilio_to_number):
        return schemas.NotificationTestResult(ok=False, message="Twilio-Zugangsdaten und Nummern zuerst speichern.")
    try:
        token = bank_sync.decrypt_secret(settings.secret_key, settings.twilio_auth_token_encrypted)
        calls.make_call(
            settings.twilio_account_sid, token, settings.twilio_from_number, settings.twilio_to_number,
            "Testanruf von Kies. Wenn du das hörst, ist Twilio korrekt eingerichtet.",
        )
    except Exception as e:
        return schemas.NotificationTestResult(ok=False, message=f"Fehlgeschlagen: {e}")
    return schemas.NotificationTestResult(ok=True, message="Anruf ausgelöst - dein Telefon sollte gleich klingeln.")


# ---------------- Enable Banking (Open-Banking-Aggregator, z.B. C24, Finom) ----------------
@api_router.get("/settings/enablebanking", response_model=schemas.EnableBankingSettingsOut)
def get_enablebanking_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.EnableBankingSettingsOut(
        app_id=settings.enablebanking_app_id,
        private_key_set=bool(settings.enablebanking_private_key_encrypted),
        redirect_base_url=settings.enablebanking_redirect_base_url,
    )


@api_router.put("/settings/enablebanking", response_model=schemas.EnableBankingSettingsOut)
def update_enablebanking_settings(data: schemas.EnableBankingSettingsUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.enablebanking_app_id = data.app_id
    settings.enablebanking_private_key_encrypted = bank_sync.encrypt_secret(settings.secret_key, data.private_key)
    settings.enablebanking_redirect_base_url = data.redirect_base_url.strip().rstrip("/") if data.redirect_base_url else None
    db.commit()
    return schemas.EnableBankingSettingsOut(
        app_id=settings.enablebanking_app_id, private_key_set=True,
        redirect_base_url=settings.enablebanking_redirect_base_url,
    )


@api_router.get("/enablebanking/aspsps", response_model=List[schemas.AspspOut])
def search_aspsps(country: str, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    if not settings.enablebanking_app_id or not settings.enablebanking_private_key_encrypted:
        raise HTTPException(400, "Bitte zuerst Enable-Banking-App-ID und privaten Schlüssel in den Einstellungen hinterlegen")
    private_key = bank_sync.decrypt_secret(settings.secret_key, settings.enablebanking_private_key_encrypted)
    try:
        aspsps = enablebanking_sync.list_aspsps(settings.enablebanking_app_id, private_key, country.upper())
    except Exception as e:
        raise HTTPException(400, f"Enable-Banking-Fehler: {e}")
    return [
        schemas.AspspOut(name=a.get("name", ""), country=a.get("country", country.upper()), logo=a.get("logo"))
        for a in aspsps
    ]


@api_router.get("/enablebanking/connections", response_model=List[schemas.EnableBankingConnectionOut])
def list_enablebanking_connections(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.get_enablebanking_connections(db, space_id)


@api_router.post("/enablebanking/connections", response_model=schemas.EnableBankingAuthStart)
def create_enablebanking_connection(data: schemas.EnableBankingConnectionCreate, request: Request, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if not crud.get_account(db, data.account_id, space_id):
        raise HTTPException(400, "Ziel-Konto existiert nicht in diesem Bereich")
    settings = auth.get_or_create_settings(db)
    if not settings.enablebanking_app_id or not settings.enablebanking_private_key_encrypted:
        raise HTTPException(400, "Bitte zuerst Enable-Banking-App-ID und privaten Schlüssel in den Einstellungen hinterlegen")
    private_key = bank_sync.decrypt_secret(settings.secret_key, settings.enablebanking_private_key_encrypted)

    state = uuid.uuid4().hex
    conn = crud.create_enablebanking_connection(db, space_id, data.account_id, data.aspsp_name, data.aspsp_country, state)
    # Enable Banking verlangt für Live-Apps eine https-Redirect-URL, die exakt mit
    # der im Portal hinterlegten übereinstimmt - die App selbst läuft aber nur über
    # http. redirect_base_url erlaubt eine feste Override-Adresse (z.B. einen
    # separaten https-Proxy), statt sich auf die zufällig aufgerufene Adresse zu
    # verlassen, die nie https sein wird.
    base = settings.enablebanking_redirect_base_url or str(request.base_url).rstrip("/")
    redirect_url = f"{base}/api/enablebanking/callback"
    try:
        url = enablebanking_sync.start_auth(
            settings.enablebanking_app_id, private_key, data.aspsp_name, data.aspsp_country, redirect_url, state,
        )
    except Exception as e:
        crud.delete_enablebanking_connection(db, conn.id, space_id)
        raise HTTPException(400, f"Enable-Banking-Fehler: {e}")
    return schemas.EnableBankingAuthStart(id=conn.id, url=url)


@api_router.get("/enablebanking/callback")
def enablebanking_callback(code: str = None, state: str = None, error: str = None, db: Session = Depends(get_db)):
    if not state:
        return RedirectResponse(url="/?enablebanking_error=missing_state")
    conn = crud.get_enablebanking_connection_by_state(db, state)
    if not conn:
        return RedirectResponse(url="/?enablebanking_error=unknown_state")
    if error or not code:
        conn.status = "error"
        conn.last_sync_status = f"Autorisierung abgebrochen oder fehlgeschlagen: {error or 'kein Code erhalten'}"
        db.commit()
        return RedirectResponse(url=f"/?enablebanking_done={conn.id}")
    settings = auth.get_or_create_settings(db)
    private_key = bank_sync.decrypt_secret(settings.secret_key, settings.enablebanking_private_key_encrypted)
    enablebanking_sync.finalize_connection(db, conn, settings.enablebanking_app_id, private_key, code)
    return RedirectResponse(url=f"/?enablebanking_done={conn.id}")


@api_router.delete("/enablebanking/connections/{connection_id}")
def remove_enablebanking_connection(connection_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.delete_enablebanking_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "Verbindung nicht gefunden")
    return {"ok": True}


@api_router.post("/enablebanking/connections/{connection_id}/sync", response_model=schemas.SyncResult)
def sync_enablebanking_connection(connection_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.get_enablebanking_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "Verbindung nicht gefunden")
    if conn.status != "linked":
        raise HTTPException(400, "Verbindung ist noch nicht abgeschlossen (Bank-Autorisierung ausstehend)")
    settings = auth.get_or_create_settings(db)
    private_key = bank_sync.decrypt_secret(settings.secret_key, settings.enablebanking_private_key_encrypted)
    result = enablebanking_sync.sync(db, conn, settings.enablebanking_app_id, private_key)
    return schemas.SyncResult(imported=result.get("imported", 0), skipped=result.get("skipped", 0), error=result.get("error"))


# ---------------- eBay (Verkäufe als Konto) ----------------
@api_router.get("/settings/ebay", response_model=schemas.EbaySettingsOut)
def get_ebay_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.EbaySettingsOut(
        app_id=settings.ebay_app_id,
        cert_id_set=bool(settings.ebay_cert_id_encrypted),
        ru_name=settings.ebay_ru_name,
    )


@api_router.put("/settings/ebay", response_model=schemas.EbaySettingsOut)
def update_ebay_settings(data: schemas.EbaySettingsUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.ebay_app_id = data.app_id
    settings.ebay_cert_id_encrypted = bank_sync.encrypt_secret(settings.secret_key, data.cert_id)
    settings.ebay_ru_name = data.ru_name
    db.commit()
    return schemas.EbaySettingsOut(app_id=settings.ebay_app_id, cert_id_set=True, ru_name=settings.ebay_ru_name)


@api_router.get("/ebay/connections", response_model=List[schemas.EbayConnectionOut])
def list_ebay_connections(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.get_ebay_connections(db, space_id)


@api_router.post("/ebay/connections", response_model=schemas.EbayAuthStart)
def create_ebay_connection(data: schemas.EbayConnectionCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if not crud.get_account(db, data.account_id, space_id):
        raise HTTPException(400, "Ziel-Konto existiert nicht in diesem Bereich")
    settings = auth.get_or_create_settings(db)
    if not settings.ebay_app_id or not settings.ebay_cert_id_encrypted or not settings.ebay_ru_name:
        raise HTTPException(400, "Bitte zuerst App-ID, Cert-ID und RuName in den Einstellungen hinterlegen")

    state = uuid.uuid4().hex
    conn = crud.create_ebay_connection(db, space_id, data.account_id, state)
    url = ebay_sync.build_consent_url(settings.ebay_app_id, settings.ebay_ru_name, state)
    return schemas.EbayAuthStart(id=conn.id, url=url)


@api_router.get("/ebay/callback")
def ebay_callback(code: str = None, state: str = None, error: str = None, db: Session = Depends(get_db)):
    if not state:
        return RedirectResponse(url="/?ebay_error=missing_state")
    conn = crud.get_ebay_connection_by_state(db, state)
    if not conn:
        return RedirectResponse(url="/?ebay_error=unknown_state")
    if error or not code:
        conn.status = "error"
        conn.last_sync_status = f"Autorisierung abgebrochen oder fehlgeschlagen: {error or 'kein Code erhalten'}"
        db.commit()
        return RedirectResponse(url=f"/?ebay_done={conn.id}")
    settings = auth.get_or_create_settings(db)
    cert_id = bank_sync.decrypt_secret(settings.secret_key, settings.ebay_cert_id_encrypted)
    ebay_sync.finalize_connection(db, conn, settings.ebay_app_id, cert_id, settings.ebay_ru_name, code)
    return RedirectResponse(url=f"/?ebay_done={conn.id}")


@api_router.delete("/ebay/connections/{connection_id}")
def remove_ebay_connection(connection_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.delete_ebay_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "Verbindung nicht gefunden")
    return {"ok": True}


@api_router.post("/ebay/connections/{connection_id}/sync", response_model=schemas.SyncResult)
def sync_ebay_connection(connection_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.get_ebay_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "Verbindung nicht gefunden")
    if conn.status != "connected":
        raise HTTPException(400, "Verbindung ist noch nicht abgeschlossen (eBay-Autorisierung ausstehend)")
    settings = auth.get_or_create_settings(db)
    cert_id = bank_sync.decrypt_secret(settings.secret_key, settings.ebay_cert_id_encrypted)
    result = ebay_sync.sync(db, conn, settings.ebay_app_id, cert_id)
    return schemas.SyncResult(imported=result.get("imported", 0), skipped=result.get("skipped", 0), error=result.get("error"))


# ---------------- To-Dos (Radicale/CalDAV) ----------------
@api_router.get("/settings/radicale", response_model=schemas.RadicaleSettingsOut)
def get_radicale_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.RadicaleSettingsOut(
        url=settings.radicale_url, username=settings.radicale_username,
        password_set=bool(settings.radicale_password_encrypted),
        calendar_url=settings.radicale_calendar_url,
    )


@api_router.put("/settings/radicale", response_model=schemas.RadicaleSettingsOut)
def update_radicale_settings(data: schemas.RadicaleSettingsUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.radicale_url = data.url
    settings.radicale_username = data.username
    settings.radicale_password_encrypted = bank_sync.encrypt_secret(settings.secret_key, data.password)
    settings.radicale_calendar_url = (data.calendar_url or "").strip() or None
    db.commit()
    return schemas.RadicaleSettingsOut(
        url=settings.radicale_url, username=settings.radicale_username, password_set=True,
        calendar_url=settings.radicale_calendar_url,
    )


@api_router.get("/settings/travel", response_model=schemas.TravelSettingsOut)
def get_travel_settings(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    return schemas.TravelSettingsOut(
        home_address=s.home_address, home_geocoded=bool(s.home_lat and s.home_lon),
        api_key_set=bool(s.openroute_api_key_encrypted),
    )


@api_router.put("/settings/travel", response_model=schemas.TravelSettingsOut)
def update_travel_settings(data: schemas.TravelSettingsUpdate, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    changes = data.model_dump(exclude_unset=True)
    # exclude_unset statt "leer heisst loeschen": beim Speichern nur des
    # API-Keys (Adresse nicht mitgeschickt) darf die schon gespeicherte
    # Adresse nicht verschwinden - live als echter Bug aufgetreten.
    if "home_address" in changes:
        address = (changes["home_address"] or "").strip()
        if address and address != s.home_address:
            # Bei jeder tatsaechlichen Adressaenderung neu geokodieren - ein
            # Fehlschlag hier soll das Speichern der uebrigen Felder nicht
            # verhindern, nur eben ohne Koordinaten (Fahrzeit-Berechnung greift
            # dann einfach nicht).
            try:
                coords = travel_time.geocode(address)
            except Exception:
                coords = None
            s.home_lat, s.home_lon = coords if coords else (None, None)
        elif not address:
            s.home_lat, s.home_lon = None, None
        s.home_address = address or None
    if changes.get("api_key"):
        s.openroute_api_key_encrypted = bank_sync.encrypt_secret(s.secret_key, changes["api_key"])
    db.commit()
    return get_travel_settings(db)


@api_router.post("/radicale/test")
def test_radicale(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    if not settings.radicale_url:
        raise HTTPException(400, "Bitte zuerst die Radicale-Adresse in den Einstellungen hinterlegen")
    password = bank_sync.decrypt_secret(settings.secret_key, settings.radicale_password_encrypted)
    try:
        n = radicale_sync.check_connection(settings.radicale_url, settings.radicale_username, password)
    except Exception as e:
        # Nur Fehlertyp + Nachricht statt roher Exception-Repraesentation
        # (koennte interne Details enthalten - CodeQL: py/stack-trace-exposure).
        # Bleibt fuer die Fehlersuche bei der eigenen Verbindung nuetzlich.
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return {"ok": True, "todo_count": n}


def _radicale_credentials(db: Session) -> tuple[str, str, str]:
    settings = auth.get_or_create_settings(db)
    if not settings.radicale_url:
        raise HTTPException(400, "Radicale ist noch nicht eingerichtet. Trage unter Einstellungen die Adresse ein.")
    password = bank_sync.decrypt_secret(settings.secret_key, settings.radicale_password_encrypted)
    return settings.radicale_url, settings.radicale_username, password


@api_router.get("/calendar/upcoming", response_model=List[schemas.CalendarEventOut])
def get_upcoming_calendar_events(days: int = 7, db: Session = Depends(get_db)):
    return crud.get_upcoming_calendar_events(db, days=days)


@api_router.get("/todos", response_model=List[schemas.TodoOut])
def list_todos(include_done: bool = True, db: Session = Depends(get_db)):
    # Beim Öffnen des Tabs direkt abgleichen statt auf den nächsten
    # Hintergrund-Sync (alle 3 Minuten) zu warten oder auf die nächste lokale
    # Änderung - sonst wirkt es, als kämen am Handy eingetragene To-Dos gar
    # nicht an, bis man selbst etwas hier ändert.
    if settings_has_radicale(db):
        url, username, password = _radicale_credentials(db)
        try:
            radicale_sync.sync(db, url, username, password)
        except Exception:
            pass
    return crud.get_todos(db, include_done)


@api_router.post("/todos", response_model=schemas.TodoOut)
def create_todo(data: schemas.TodoCreate, db: Session = Depends(get_db)):
    todo = crud.create_todo(db, data.title, data.due_date)
    # Sofort hochladen, damit ein neues To-Do nicht erst auf den nächsten
    # Hintergrund-Sync warten muss, um am Handy sichtbar zu werden.
    if settings_has_radicale(db):
        url, username, password = _radicale_credentials(db)
        try:
            radicale_sync.sync(db, url, username, password)
        except Exception:
            pass
    return todo


@api_router.patch("/todos/{todo_id}", response_model=schemas.TodoOut)
def update_todo(todo_id: int, data: schemas.TodoUpdate, db: Session = Depends(get_db)):
    todo = crud.get_todo(db, todo_id)
    if not todo:
        raise HTTPException(404, "To-Do nicht gefunden")
    todo = crud.update_todo(db, todo, data.title, data.done, data.due_date)
    if settings_has_radicale(db):
        url, username, password = _radicale_credentials(db)
        try:
            radicale_sync.sync(db, url, username, password)
        except Exception:
            pass
    return todo


@api_router.delete("/todos/{todo_id}")
def remove_todo(todo_id: int, db: Session = Depends(get_db)):
    todo = crud.get_todo(db, todo_id)
    if not todo:
        raise HTTPException(404, "To-Do nicht gefunden")
    if settings_has_radicale(db):
        crud.delete_todo(db, todo)
        url, username, password = _radicale_credentials(db)
        try:
            radicale_sync.sync(db, url, username, password)
        except Exception:
            pass
    else:
        # Ohne Radicale gibt es nichts zum Nachtragen - sofort endgültig
        # löschen, statt als "pending_delete" liegen zu bleiben, bis
        # irgendwann doch noch eine Verbindung eingerichtet wird.
        db.delete(todo)
        db.commit()
    return {"ok": True}


@api_router.post("/todos/sync", response_model=schemas.TodoSyncResult)
def sync_todos(db: Session = Depends(get_db)):
    url, username, password = _radicale_credentials(db)
    result = radicale_sync.sync(db, url, username, password)
    return schemas.TodoSyncResult(**result)


def settings_has_radicale(db: Session) -> bool:
    settings = auth.get_or_create_settings(db)
    return bool(settings.radicale_url)


# ---------------- Dashboard ----------------
@api_router.get("/dashboard", response_model=schemas.DashboardSummary)
def dashboard(year: int = date.today().year, month: Optional[int] = None, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.dashboard_summary(db, space_id, year, month)


@api_router.get("/dashboard/top-recipients", response_model=List[schemas.TopExpenseRecipientOut])
def dashboard_top_recipients(
    year: int = date.today().year, month: Optional[int] = None, limit: int = 10,
    db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id),
):
    limit = max(1, min(limit, 50))
    return crud.top_expense_recipients(db, space_id, year, month, limit)


@api_router.get("/dashboard/trend", response_model=schemas.DashboardTrendOut)
def dashboard_trend(months: int = 6, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    """Kleine monatliche Einnahmen/Ausgaben-Reihe fuer die Sparklines auf dem
    Hub - bewusst ein eigener, leichtgewichtiger Endpunkt statt N Aufrufe von
    /dashboard je Monat vom Frontend aus."""
    months = max(2, min(months, 24))
    return schemas.DashboardTrendOut(points=[
        schemas.DashboardTrendPoint(**p) for p in crud.monthly_flow_trend(db, space_id, months)
    ])


@api_router.get("/year-review", response_model=schemas.YearReviewOut)
def year_review(year: int = date.today().year, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    """Jahresrueckblick - reine Auswertung, keine neue Datenerfassung."""
    data = crud.year_review(db, space_id, year)
    return schemas.YearReviewOut(**data)


# ---------------- Geschäftlich (Filter auf is_business-Konten, kein eigener Bereich) ----------------
@api_router.get("/business/summary", response_model=schemas.DashboardSummary)
def business_summary(year: int = date.today().year, month: Optional[int] = None, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.dashboard_summary(db, space_id, year, month, business_only=True)


# ---------------- Export / Import ----------------
@api_router.get("/export/transactions.csv")
def export_transactions_csv(
    account_id: Optional[int] = None,
    category_id: Optional[int] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    transactions = crud.get_transactions(db, space_id, account_id, category_id, year, month, search)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Datum", "Betrag", "Konto", "Kategorie", "Beschreibung", "Notiz"])
    for t in transactions:
        writer.writerow([
            t.date.isoformat(),
            f"{t.amount:.2f}".replace(".", ","),
            t.account.name if t.account else "",
            t.category.name if t.category else "",
            t.description or "",
            t.notes or "",
        ])
    filename = f"buchungen_{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_router.post("/import/transactions")
def import_transactions_csv(file: UploadFile = File(...), db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    raw = file.file.read().decode("utf-8-sig")
    delimiter = ";" if raw.split("\n", 1)[0].count(";") >= raw.split("\n", 1)[0].count(",") else ","
    reader = list(csv.reader(io.StringIO(raw), delimiter=delimiter))
    if not reader:
        raise HTTPException(400, "Leere Datei")

    header = [h.strip().lower() for h in reader[0]]
    accounts_by_name = {a.name.lower(): a for a in crud.get_accounts(db, space_id)}
    categories_by_name = {c.name.lower(): c for c in crud.get_categories(db)}

    imported, skipped, errors = 0, 0, []
    for i, row in enumerate(reader[1:], start=2):
        if not row or not any(cell.strip() for cell in row):
            continue
        data = dict(zip(header, row))
        try:
            acc = accounts_by_name.get((data.get("konto") or "").strip().lower())
            if not acc:
                raise ValueError(f"Konto '{data.get('konto', '')}' nicht gefunden")
            cat = categories_by_name.get((data.get("kategorie") or "").strip().lower())
            amount = float((data.get("betrag") or "0").replace(",", "."))
            tx_date = date.fromisoformat(data["datum"].strip())
            crud.create_transaction(db, schemas.TransactionCreate(
                date=tx_date, amount=amount, account_id=acc.id,
                category_id=cat.id if cat else None,
                description=(data.get("beschreibung") or None),
                notes=(data.get("notiz") or None),
            ))
            imported += 1
        except Exception as e:
            # Nur Fehlertyp + Nachricht statt roher Exception-Repraesentation
            # (koennte interne Details enthalten - CodeQL: py/stack-trace-exposure).
            # Bleibt fuer den Import des eigenen CSVs nuetzlich.
            errors.append(f"Zeile {i}: {type(e).__name__}: {e}")
            skipped += 1

    return {"imported": imported, "skipped": skipped, "errors": errors}


# ---------------- Export / Import: Investments ----------------
HOLDING_ASSET_TYPE_ALIASES = {
    "aktie": models.AssetType.aktie,
    "etf": models.AssetType.etf,
    "anleihe": models.AssetType.anleihe,
    "krypto": models.AssetType.krypto,
    "sonstiges": models.AssetType.sonstiges,
}


@api_router.get("/export/holdings.csv")
def export_holdings_csv(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    holdings = crud.get_holdings(db, space_id)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Anlageklasse", "Name", "Symbol", "Sektor", "Stückzahl", "Kaufpreis", "Kaufdatum"])
    for h in holdings:
        writer.writerow([
            h.asset_type.value,
            h.name,
            h.symbol,
            h.sector or "",
            f"{h.quantity}".replace(".", ","),
            f"{h.purchase_price:.4f}".replace(".", ","),
            h.purchase_date.isoformat() if h.purchase_date else "",
        ])
    filename = f"positionen_{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_router.post("/import/holdings")
def import_holdings_csv(file: UploadFile = File(...), db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    raw = file.file.read().decode("utf-8-sig")
    delimiter = ";" if raw.split("\n", 1)[0].count(";") >= raw.split("\n", 1)[0].count(",") else ","
    reader = list(csv.reader(io.StringIO(raw), delimiter=delimiter))
    if not reader:
        raise HTTPException(400, "Leere Datei")

    header = [h.strip().lower() for h in reader[0]]
    existing = {(h.asset_type, h.symbol.lower()): h for h in crud.get_holdings(db, space_id)}

    created, added_lots, skipped, errors = 0, 0, 0, []
    for i, row in enumerate(reader[1:], start=2):
        if not row or not any(cell.strip() for cell in row):
            continue
        data = dict(zip(header, row))
        try:
            asset_type = HOLDING_ASSET_TYPE_ALIASES.get((data.get("anlageklasse") or "").strip().lower())
            if not asset_type:
                raise ValueError(f"Unbekannte Anlageklasse '{data.get('anlageklasse', '')}' (aktie/etf/anleihe/krypto/sonstiges)")
            name = (data.get("name") or "").strip()
            symbol = (data.get("symbol") or "").strip()
            if not name or not symbol:
                raise ValueError("Name und Symbol erforderlich")
            quantity = float((data.get("stückzahl") or "0").replace(",", "."))
            purchase_price = float((data.get("kaufpreis") or "0").replace(",", "."))
            purchase_date_raw = (data.get("kaufdatum") or "").strip()
            purchase_date = date.fromisoformat(purchase_date_raw) if purchase_date_raw else None
            sector = (data.get("sektor") or "").strip() or None

            key = (asset_type, symbol.lower())
            if key in existing:
                h = existing[key]
                crud.create_lot(db, h.id, space_id, schemas.HoldingLotCreate(
                    date=purchase_date or date.today(), type=models.LotType.kauf,
                    quantity=quantity, price_per_unit=purchase_price,
                ))
                added_lots += 1
            else:
                h = crud.create_holding(db, schemas.HoldingCreate(
                    asset_type=asset_type, name=name, symbol=symbol, sector=sector,
                    quantity=quantity, purchase_price=purchase_price, purchase_date=purchase_date,
                ), space_id)
                existing[key] = h
                created += 1
        except Exception as e:
            # Nur Fehlertyp + Nachricht statt roher Exception-Repraesentation
            # (koennte interne Details enthalten - CodeQL: py/stack-trace-exposure).
            # Bleibt fuer den Import des eigenen CSVs nuetzlich.
            errors.append(f"Zeile {i}: {type(e).__name__}: {e}")
            skipped += 1

    return {"created": created, "added_lots": added_lots, "skipped": skipped, "errors": errors}


# ---------------- Backup / Restore (bereichsübergreifend) ----------------
def _build_backup_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        db_path = os.path.join(DATA_DIR, "finance.db")
        if os.path.exists(db_path):
            zf.write(db_path, "finance.db")
        if os.path.isdir(UPLOAD_DIR):
            for root, _, files in os.walk(UPLOAD_DIR):
                for fname in files:
                    full = os.path.join(root, fname)
                    rel = os.path.join("uploads", os.path.relpath(full, UPLOAD_DIR))
                    zf.write(full, rel)
    return buf.getvalue()


@api_router.get("/backup")
def backup():
    data = _build_backup_zip_bytes()
    filename = f"finanztool_backup_{date.today().isoformat()}.zip"
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


BACKUP_DIR = os.path.join(DATA_DIR, "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)
BACKUP_FILENAME_RE = re.compile(r"^auto_backup_\d{8}_\d{6}\.zip$")


def _write_backup_to_disk(retention: int) -> schemas.BackupFileOut:
    data = _build_backup_zip_bytes()
    filename = f"auto_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.zip"
    full_path = os.path.join(BACKUP_DIR, filename)
    with open(full_path, "wb") as f:
        f.write(data)

    existing = sorted(f for f in os.listdir(BACKUP_DIR) if BACKUP_FILENAME_RE.fullmatch(f))
    excess = len(existing) - retention
    for old in existing[:max(excess, 0)]:
        os.remove(os.path.join(BACKUP_DIR, old))

    stat = os.stat(full_path)
    return schemas.BackupFileOut(
        filename=filename, size_bytes=stat.st_size,
        created_at=datetime.utcfromtimestamp(stat.st_mtime),
    )


def _scheduled_auto_backup():
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        if not settings.auto_backup_enabled:
            return
        _write_backup_to_disk(settings.backup_retention)
    finally:
        db.close()


@api_router.get("/settings/backup", response_model=schemas.BackupSettingsOut)
def get_backup_settings(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    return schemas.BackupSettingsOut(enabled=s.auto_backup_enabled, hour=s.backup_hour, retention=s.backup_retention)


@api_router.put("/settings/backup", response_model=schemas.BackupSettingsOut)
def update_backup_settings(data: schemas.BackupSettingsUpdate, db: Session = Depends(get_db)):
    if not 0 <= data.hour <= 23:
        raise HTTPException(400, "Stunde muss zwischen 0 und 23 liegen")
    if not 1 <= data.retention <= 365:
        raise HTTPException(400, "Aufbewahrung muss zwischen 1 und 365 liegen")
    s = auth.get_or_create_settings(db)
    s.auto_backup_enabled = data.enabled
    s.backup_hour = data.hour
    s.backup_retention = data.retention
    db.commit()
    scheduler.reschedule_job("auto_backup", trigger=CronTrigger(hour=data.hour, minute=0))
    return schemas.BackupSettingsOut(enabled=s.auto_backup_enabled, hour=s.backup_hour, retention=s.backup_retention)


@api_router.get("/backups", response_model=List[schemas.BackupFileOut])
def list_backups():
    items = []
    for fname in os.listdir(BACKUP_DIR):
        if not BACKUP_FILENAME_RE.fullmatch(fname):
            continue
        stat = os.stat(os.path.join(BACKUP_DIR, fname))
        items.append(schemas.BackupFileOut(
            filename=fname, size_bytes=stat.st_size,
            created_at=datetime.utcfromtimestamp(stat.st_mtime),
        ))
    items.sort(key=lambda b: b.created_at, reverse=True)
    return items


@api_router.post("/backups/run", response_model=schemas.BackupFileOut)
def run_backup_now(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return _write_backup_to_disk(settings.backup_retention)


@api_router.get("/backups/{filename}")
def download_backup(filename: str):
    safe_name = os.path.basename(filename)
    if not BACKUP_FILENAME_RE.fullmatch(safe_name):
        raise HTTPException(404, "Backup nicht gefunden")
    full = os.path.join(BACKUP_DIR, safe_name)
    if not os.path.exists(full):
        raise HTTPException(404, "Backup nicht gefunden")
    return FileResponse(full, media_type="application/zip", filename=safe_name)


@api_router.delete("/backups/{filename}")
def delete_backup(filename: str):
    safe_name = os.path.basename(filename)
    if not BACKUP_FILENAME_RE.fullmatch(safe_name):
        raise HTTPException(404, "Backup nicht gefunden")
    full = os.path.join(BACKUP_DIR, safe_name)
    if os.path.exists(full):
        os.remove(full)
    return {"ok": True}


@api_router.post("/restore")
def restore(file: UploadFile = File(...)):
    content = file.file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(400, "Ungültige Backup-Datei")
    if "finance.db" not in zf.namelist():
        raise HTTPException(400, "Backup enthält keine finance.db")

    db_path = os.path.join(DATA_DIR, "finance.db")
    if os.path.exists(db_path):
        shutil.copy2(db_path, db_path + ".bak")

    zf.extract("finance.db", DATA_DIR)
    for name in zf.namelist():
        if name.startswith("uploads/") and not name.endswith("/"):
            zf.extract(name, DATA_DIR)

    return {
        "ok": True,
        "message": "Wiederhergestellt. Bitte den Container neu starten (docker compose restart), damit die Daten geladen werden.",
    }


app.include_router(api_router)


# ---------------- Automatischer Sync (Bank, Bitvavo, PayPal, Enable Banking) ----------------
def _scheduled_bank_sync():
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        if settings.fints_product_id:
            for conn in crud.get_all_bank_connections(db):
                try:
                    pin = bank_sync.decrypt_pin(settings.secret_key, conn.pin_encrypted)
                    since = conn.last_sync_at.date() if conn.last_sync_at else date.today() - timedelta(days=90)
                    bank_sync.start_sync(db, conn, pin, settings.fints_product_id, since)
                except Exception as e:
                    conn.last_sync_status = f"Fehler beim automatischen Sync: {e}"
                    db.commit()

        for bv_conn in crud.get_all_bitvavo_connections(db):
            try:
                api_key = bank_sync.decrypt_secret(settings.secret_key, bv_conn.api_key_encrypted)
                api_secret = bank_sync.decrypt_secret(settings.secret_key, bv_conn.api_secret_encrypted)
                exchange_sync.sync(db, bv_conn, api_key, api_secret, bv_conn.space_id)
            except Exception as e:
                bv_conn.last_sync_status = f"Fehler beim automatischen Sync: {e}"
                db.commit()

        for pp_conn in crud.get_all_paypal_connections(db):
            try:
                client_id = bank_sync.decrypt_secret(settings.secret_key, pp_conn.client_id_encrypted)
                client_secret = bank_sync.decrypt_secret(settings.secret_key, pp_conn.client_secret_encrypted)
                paypal_sync.sync(db, pp_conn, client_id, client_secret)
            except Exception as e:
                pp_conn.last_sync_status = f"Fehler beim automatischen Sync: {e}"
                db.commit()

        if settings.enablebanking_app_id and settings.enablebanking_private_key_encrypted:
            private_key = bank_sync.decrypt_secret(settings.secret_key, settings.enablebanking_private_key_encrypted)
            for eb_conn in crud.get_all_enablebanking_connections(db):
                if eb_conn.status != "linked":
                    continue
                try:
                    enablebanking_sync.sync(db, eb_conn, settings.enablebanking_app_id, private_key)
                except Exception as e:
                    eb_conn.last_sync_status = f"Fehler beim automatischen Sync: {e}"
                    db.commit()

        if settings.ebay_app_id and settings.ebay_cert_id_encrypted:
            cert_id = bank_sync.decrypt_secret(settings.secret_key, settings.ebay_cert_id_encrypted)
            for eb_conn in crud.get_all_ebay_connections(db):
                if eb_conn.status != "connected":
                    continue
                try:
                    ebay_sync.sync(db, eb_conn, settings.ebay_app_id, cert_id)
                except Exception as e:
                    eb_conn.last_sync_status = f"Fehler beim automatischen Sync: {e}"
                    db.commit()
    finally:
        db.close()

    # Direkt im Anschluss auswerten, damit die Ziele auf den frisch synchronisierten
    # Kontoständen/Kursen rechnen - kein eigener Zeitplan nötig.
    _scheduled_goal_evaluation()
    _check_daily_alerts()


def _scheduled_goal_evaluation():
    """Schreibt für jedes offene automatische Ziel einen Verlaufspunkt und hakt
    erreichte Ziele ab. Der Fortschritt selbst wird beim Abruf live gerechnet -
    dieser Job existiert für die Historie (Graph) und für Zeiträume, in denen die
    App gar nicht geöffnet wird."""
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        for goal in crud.get_open_auto_goals(db):
            try:
                was_open = goal.status == models.GoalStatus.open
                result = goals.evaluate_goal(db, goal)
                if result.value is not None:
                    goals.record_progress_snapshot(db, goal, result.value)
                # Genau der Moment des Statuswechsels - feuert also nur einmal pro Ziel.
                if was_open and goal.status == models.GoalStatus.completed:
                    notifications.notify(settings, f"🎉 Ziel erreicht: „{goal.title}“")
                    calls.call(settings, f"Kies: Glückwunsch, du hast dein Ziel {goal.title} erreicht.")
                db.commit()
            except Exception:
                db.rollback()
    finally:
        db.close()


def _check_daily_alerts():
    """Cashflow-Prognose und Budgets einmal täglich prüfen und bei Bedarf per
    Telegram warnen - jeweils höchstens einmal pro Tag/Monat, damit derselbe
    Zustand nicht bei jedem Sync erneut meldet (siehe last_cashflow_alert_date/
    last_budget_alert_month)."""
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        if not settings.notifications_enabled:
            return
        today = date.today()
        month_key = today.strftime("%Y-%m")

        for space in crud.get_spaces(db):
            try:
                if settings.last_cashflow_alert_date != today:
                    forecast = crud.cashflow_forecast(db, space.id, 90)
                    if forecast.goes_negative:
                        notifications.notify(
                            settings,
                            f"⚠️ Cashflow-Prognose ({space.name}): Kontostand könnte am "
                            f"{forecast.first_negative_date} ins Minus rutschen (Tiefstand "
                            f"{forecast.lowest_balance:.2f} EUR am {forecast.lowest_date}).",
                        )
                        # Anrufen nur im wirklich akuten Fenster (1-3 Tage) - bei einer
                        # erst in Wochen drohenden Flaute reicht die Telegram-Meldung.
                        first_negative = date.fromisoformat(forecast.first_negative_date)
                        if (first_negative - today).days <= 3:
                            calls.call(
                                settings,
                                f"Kies-Notruf: Dein Kontostand könnte spätestens am "
                                f"{first_negative.strftime('%-d. %-m.')} ins Minus rutschen. Bitte prüfe die App.",
                            )
                        settings.last_cashflow_alert_date = today
                        db.commit()
            except Exception:
                db.rollback()

            try:
                if settings.last_budget_alert_month != month_key:
                    over = [b for b in crud.budget_progress(db, space.id, today.year, today.month) if b.percent >= 100]
                    if over:
                        lines = "\n".join(f"- {b.category_name}: {b.spent:.2f} von {b.limit:.2f} EUR" for b in over)
                        notifications.notify(
                            settings,
                            f"📊 Budget überschritten ({space.name}, {month_key}):\n{lines}",
                        )
                        settings.last_budget_alert_month = month_key
                        db.commit()
            except Exception:
                db.rollback()

            try:
                for reminder in crud.evaluate_contract_reminders(db, space.id):
                    notifications.notify(
                        settings,
                        f"📄 Kündigungsfrist ({space.name}): „{reminder.label}“ verlängert sich am "
                        f"{reminder.renewal_date.strftime('%d.%m.%Y')} automatisch - "
                        f"Kündigungsfrist beginnt jetzt ({reminder.notice_period_days} Tage vorher).",
                    )
            except Exception:
                db.rollback()

            try:
                for r in crud.evaluate_return_deadlines(db, space.id):
                    notifications.notify(
                        settings,
                        f"🔄 Rückgabefrist ({space.name}): „{r['label']}“ läuft am "
                        f"{r['deadline_date'].strftime('%d.%m.%Y')} ab (noch {r['days_left']} Tag(e)).",
                    )
            except Exception:
                db.rollback()

            try:
                for bill in crud.evaluate_creditcard_bills(db, space.id):
                    betrag_text = f"{bill['amount']:.2f} €" if bill["amount"] is not None else "unbekannter Betrag"
                    notifications.notify(
                        settings,
                        f"💳 Kreditkarten-Rechnung ({bill['account_name']}): {betrag_text} fällig am "
                        f"{bill['due_date'].strftime('%d.%m.%Y')} (noch {bill['days_left']} Tag(e)).",
                    )
            except Exception:
                db.rollback()

            try:
                # Sofortmeldung bei negativem Saldo, unabhängig von der 90-Tage-
                # Cashflow-Prognose (die nur die schon erkannten wiederkehrenden
                # Zahlungen fortschreibt und einen echten, plötzlichen Dispo-Rutsch
                # erst Tage später "sehen" würde). dispo_alert_sent verhindert eine
                # taegliche Wiederholung, solange das Konto im Minus bleibt.
                for acc in crud.get_accounts(db, space.id):
                    balance = crud.account_balance(db, acc)
                    if balance < 0 and not acc.dispo_alert_sent:
                        notifications.notify(
                            settings,
                            f"🔴 Dispo ({space.name}): „{acc.name}“ ist ins Minus gerutscht "
                            f"({balance:.2f} EUR).",
                        )
                        acc.dispo_alert_sent = True
                        db.commit()
                    elif balance >= 0 and acc.dispo_alert_sent:
                        acc.dispo_alert_sent = False
                        db.commit()
            except Exception:
                db.rollback()

            try:
                for est in crud.evaluate_dividend_reminders(db, space.id):
                    notifications.notify(
                        settings,
                        f"💰 Dividende erwartet ({space.name}): „{est['name']}“ ca. am "
                        f"{est['estimated_date'].strftime('%d.%m.%Y')} - geschätzt "
                        f"{est['estimated_amount']:.2f} EUR (Schätzung aus dem bisherigen "
                        f"Zahlungsmuster, keine Zusage des Unternehmens).",
                    )
            except Exception:
                db.rollback()
    finally:
        db.close()


def _run_ai_maintenance_for_space(db: Session, space_id: int, settings: models.Settings) -> schemas.AutoCategorizeRunResult:
    """Umbuchungen erkennen + (falls eingeschaltet) unkategorisierte Buchungen per
    KI zuordnen. Gemeinsam genutzt vom stündlichen Job und vom manuellen 'Jetzt
    ausführen'-Button, damit beide garantiert dasselbe tun."""
    transfers_marked = crud.detect_and_mark_transfers(db, space_id)
    if transfers_marked:
        settings.transfers_marked_since_digest = (settings.transfers_marked_since_digest or 0) + transfers_marked
        db.commit()
    if not settings.auto_categorize_enabled:
        return schemas.AutoCategorizeRunResult(transfers_marked=transfers_marked, categorized=0, skipped=0)
    result = ai_auto.auto_categorize(db, space_id, settings)
    return schemas.AutoCategorizeRunResult(
        transfers_marked=transfers_marked, categorized=result.categorized,
        skipped=result.skipped, error=result.error,
    )


def _scheduled_ai_maintenance():
    """Stündlich: Umbuchungen erkennen und offene Buchungen automatisch
    kategorisieren, für jeden Bereich getrennt (Kategorien sind zwar global,
    Buchungen aber nicht)."""
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        for space in crud.get_spaces(db):
            try:
                _run_ai_maintenance_for_space(db, space.id, settings)
            except Exception:
                db.rollback()

        # Belege aus dem Postfach laufen im selben Stundentakt mit - ein
        # eigener Zeitplan waere nur eine weitere Stellschraube ohne Nutzen.
        # Fehler duerfen die Kategorisierung nicht mitreissen.
        if settings.mail_enabled and settings.imap_host:
            for space in crud.get_spaces(db):
                try:
                    _run_mail_sync(db, space.id)
                except Exception:
                    db.rollback()
    finally:
        db.close()


def _scheduled_net_worth_snapshot():
    """Einmal taeglich kurz vor Mitternacht: Nettovermoegen je Bereich
    festhalten. Einzige Quelle fuer eine echte Verlaufskurve - siehe
    NetWorthSnapshot-Modell fuer die Begruendung, warum es vorher keine gab."""
    db = SessionLocal()
    try:
        for space in crud.get_spaces(db):
            try:
                crud.record_net_worth_snapshot(db, space.id)
            except Exception:
                db.rollback()
    finally:
        db.close()


DIGEST_HOURS = [6, 9, 12, 15, 18, 21, 0]  # alle 3 Stunden, 06:30 bis 00:30


def _scheduled_digest():
    """Proaktives Status-Update per Telegram, mehrmals taeglich (siehe
    DIGEST_HOURS) - Nutzerwunsch nach einem Assistenten, der sich von selbst
    meldet statt nur auf Nachfrage zu antworten. Bewusst reine Auswertung
    (crud.build_digest), keine eigene "notified"-Logik wie die Sofort-
    Warnungen in _check_daily_alerts - beides laeuft unabhaengig nebeneinander."""
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        home_coords = (settings.home_lat, settings.home_lon) if settings.home_lat and settings.home_lon else None
        ors_api_key = (
            bank_sync.decrypt_secret(settings.secret_key, settings.openroute_api_key_encrypted)
            if settings.openroute_api_key_encrypted else None
        )
        since = settings.last_digest_sent_at
        transfers_marked = settings.transfers_marked_since_digest or 0
        for space in crud.get_spaces(db):
            try:
                text = crud.build_digest(
                    db, space.id, home_coords=home_coords, ors_api_key=ors_api_key,
                    since=since, transfers_marked=transfers_marked,
                )
                notifications.notify(settings, text)
            except Exception:
                db.rollback()
        settings.last_digest_sent_at = datetime.utcnow()
        settings.transfers_marked_since_digest = 0
        db.commit()
    finally:
        db.close()


def _geocode_missing_event_locations(db: Session):
    """Geokodiert Termin-Orte, die noch keine Koordinaten haben - einmalig pro
    Termin, nicht bei jedem Digest-Lauf (siehe CalendarEvent.lat/lon). Nur
    zukünftige Termine, damit nicht bei jedem Sync alte/vergangene Orte erneut
    versucht werden. Nominatim-Nutzungsbedingungen: max. 1 Anfrage/Sekunde -
    bei der hier üblichen Anzahl (wenige Termine) ohne Sleep unproblematisch."""
    events = (
        db.query(models.CalendarEvent)
        .filter(
            models.CalendarEvent.location.isnot(None),
            models.CalendarEvent.lat.is_(None),
            models.CalendarEvent.start >= datetime.utcnow(),
        )
        .all()
    )
    for ev in events:
        try:
            coords = travel_time.geocode(ev.location)
        except Exception:
            continue
        if coords:
            ev.lat, ev.lon = coords
    if events:
        db.commit()


def _scheduled_radicale_sync():
    """Alle paar Minuten mit dem Radicale-Server abgleichen - läuft öfter als
    die anderen Sync-Jobs, weil To-Dos, die man gerade am Handy einträgt, sich
    anders als Bankumsätze typischerweise sofort sehen lassen sollen.

    Räumt zusätzlich abgehakte To-Dos auf, die seit 2 Tagen erledigt sind -
    das läuft auch ohne Radicale-Anbindung (rein lokale Nutzung)."""
    db = SessionLocal()
    try:
        crud.cleanup_old_done_todos(db)
        settings = auth.get_or_create_settings(db)
        if not settings.radicale_url:
            # Ohne Server nichts zum Abgleichen - zur Löschung markierte
            # To-Dos direkt entfernen, statt auf einen Sync zu warten, der nie
            # kommt.
            for todo in db.query(models.Todo).filter(models.Todo.pending_delete.is_(True)).all():
                db.delete(todo)
            db.commit()
            return
        password = bank_sync.decrypt_secret(settings.secret_key, settings.radicale_password_encrypted)
        try:
            radicale_sync.sync(db, settings.radicale_url, settings.radicale_username, password)
        except Exception:
            pass
        if settings.radicale_calendar_url:
            try:
                radicale_sync.sync_calendar(db, settings.radicale_calendar_url, settings.radicale_username, password)
            except Exception:
                pass
            _geocode_missing_event_locations(db)
    finally:
        db.close()


def _scheduled_immich_quality_scan():
    """Scannt alle paar Minuten eine weitere Seite der Immich-Bibliothek auf
    unscharfe/leere Fotos. Läuft absichtlich in kleinen Häppchen statt in
    einem Rutsch - bei ~24.000 Fotos wäre ein einzelner Durchlauf viel zu
    lang für einen einzelnen Job-Aufruf. Nach der letzten Seite geht es wieder
    bei Seite 1 los, damit auch neu hinzugekommene Fotos erfasst werden."""
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        if not settings.immich_url or not settings.immich_api_key_encrypted:
            return
        url, key = _immich_credentials(db)
        page = settings.immich_quality_scan_page or 1
        try:
            items, has_more = immich.list_assets_page(url, key, page)
        except Exception:
            return

        for a in items:
            asset_id = a.get("id")
            if not asset_id:
                continue
            existing = db.query(models.ImmichQualityFlag).filter(
                models.ImmichQualityFlag.asset_id == asset_id).first()
            # Vom Nutzer bewusst behaltene Fotos nicht erneut bewerten -
            # sonst tauchen sie nach dem naechsten Durchlauf wieder auf.
            if existing and existing.dismissed:
                continue
            try:
                content, _ = immich.fetch_thumbnail(url, key, asset_id)
                reason, score = immich.assess_quality(content)
            except Exception:
                continue

            if reason is None:
                if existing:
                    db.delete(existing)
                continue

            summary = immich.asset_summary(a)
            if existing:
                existing.reason = reason
                existing.score = score
                existing.file_name = summary["file_name"]
                existing.created_at_immich = summary["created_at"]
                existing.width = summary["width"]
                existing.height = summary["height"]
                existing.size_bytes = summary["size_bytes"]
                existing.scanned_at = datetime.utcnow()
            else:
                db.add(models.ImmichQualityFlag(
                    asset_id=asset_id, reason=reason, score=score,
                    file_name=summary["file_name"], created_at_immich=summary["created_at"],
                    width=summary["width"], height=summary["height"], size_bytes=summary["size_bytes"],
                ))
        db.commit()

        settings.immich_quality_scan_page = page + 1 if has_more else 1
        db.commit()
    finally:
        db.close()


scheduler = BackgroundScheduler()
scheduler.add_job(
    _scheduled_bank_sync, CronTrigger(hour=INITIAL_SYNC_HOUR, minute=0),
    id="bank_sync", misfire_grace_time=3600,
)
scheduler.add_job(
    _scheduled_ai_maintenance, CronTrigger(minute=0),
    id="ai_maintenance", misfire_grace_time=1800,
)
scheduler.add_job(
    _scheduled_auto_backup, CronTrigger(hour=INITIAL_BACKUP_HOUR, minute=0),
    id="auto_backup", misfire_grace_time=3600,
)
scheduler.add_job(
    _scheduled_immich_quality_scan, CronTrigger(minute="*/5"),
    id="immich_quality_scan", misfire_grace_time=600,
)
scheduler.add_job(
    _scheduled_radicale_sync, CronTrigger(minute="*/3"),
    id="radicale_sync", misfire_grace_time=300,
)
scheduler.add_job(
    _scheduled_net_worth_snapshot, CronTrigger(hour=23, minute=55),
    id="net_worth_snapshot", misfire_grace_time=3600,
)
scheduler.add_job(
    _scheduled_digest, CronTrigger(hour=",".join(str(h) for h in DIGEST_HOURS), minute=30),
    id="digest", misfire_grace_time=1800,
)
scheduler.start()
# Direkt beim Start einmal ausfuehren statt bis 23:55 zu warten - sonst gibt es
# nach der Einfuehrung dieses Features fast einen ganzen Tag lang noch gar
# keinen ersten Snapshot. record_net_worth_snapshot ist idempotent (ueberspringt,
# wenn heute schon einer existiert), ein Neustart am selben Tag legt also nichts
# doppelt an.
_scheduled_net_worth_snapshot()

# Läuft dauerhaft im Hintergrund (kein Cron-Job, da Long-Polling blockiert) -
# prüft selbst bei jedem Durchlauf, ob Telegram überhaupt konfiguriert ist.
threading.Thread(target=telegram_bot.run_polling_loop, daemon=True, name="telegram-polling").start()


@app.on_event("shutdown")
def _shutdown_scheduler():
    scheduler.shutdown(wait=False)


# ---------------- Frontend ausliefern ----------------
FRONTEND_DIR = os.environ.get("FRONTEND_DIR", "/frontend")
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

import os
import shutil
import uuid
from datetime import date, datetime, timedelta
from typing import Optional, List

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session

import threading

from . import models, schemas, crud, auth, bank_sync, radicale_sync, ollama_client, document_extract, goals, websearch, notifications, telegram_bot, calls, immich, travel_time, weather
from . import sync_tombstones  # noqa: F401 - Seiteneffekt: registriert die Tombstone-Session-Events
from .sync import sync_router
from .routers.investments import investments_router
from .routers.tax_endpoints import tax_router
from .routers.debts import debts_router
from .routers.goals import goals_router, goal_out
from .routers.trips import trips_router
from .routers.wishlist import wishlist_router
from .routers.personal import personal_router
from .routers.business_life import business_life_router
from .routers.budgets_alerts import budgets_alerts_router
from .routers.deadlines import deadlines_router
from .routers.calendar_todos import calendar_todos_router
from .routers.categories import categories_router
from .routers.immich_routes import immich_router, immich_credentials
from .routers.bank_connections import bank_connections_router
from .routers.enablebanking_ebay import enablebanking_ebay_router
from .routers.mail_routes import mail_router, run_mail_sync
from .routers.spaces_accounts import spaces_accounts_router
from .routers.backup_restore import backup_router, write_backup_to_disk
from .routers.export_import import export_import_router
from .routers.analytics import analytics_router
from .routers.settings_misc import settings_misc_router, run_ai_maintenance_for_space
from .routers.notify_settings import notify_settings_router
from .routers.dashboard import dashboard_router
from .routers.profile_ollama import profile_ollama_router
from .routers.sync_all import sync_all_router, sync_all_connections
from .routers.ai_assistant import ai_assistant_router, websearch_configured, websearch_run
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
# Ziel-Fortschritts-Regel kam nach den ersten drei Alarm-Regeltypen dazu.
ensure_columns("alert_rules", {
    "goal_id": "INTEGER",
})
ensure_columns("transactions", {
    "categorized_at": "DATETIME",
})
ensure_columns("transactions", {
    "receipt_text": "TEXT",
    "receipt_indexed_at": "DATETIME",
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
    "websearch_provider": "VARCHAR DEFAULT 'brave'",
    "searxng_url": "VARCHAR",
})
ensure_columns("settings", {
    "display_currency": "VARCHAR DEFAULT 'EUR'",
})
ensure_columns("settings", {
    "residence_country": "VARCHAR DEFAULT 'DE'",
})
ensure_columns("settings", {
    "notifications_enabled": "BOOLEAN DEFAULT 1",
    "telegram_bot_token_encrypted": "VARCHAR",
    "telegram_chat_id": "VARCHAR",
    "last_cashflow_alert_date": "DATE",
    "last_budget_alert_month": "VARCHAR",
})
ensure_columns("settings", {
    "n8n_webhook_secret_encrypted": "VARCHAR",
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
    "calendar_url": "VARCHAR",
    "updated_at": "DATETIME",
    "last_synced_at": "DATETIME",
    "pending_delete": "BOOLEAN DEFAULT 0",
    "travel_reminder_sent": "BOOLEAN DEFAULT 0",
})
ensure_columns("calendar_events", {
    "rrule": "VARCHAR",
})
ensure_columns("life_areas", {
    "target_days_per_week": "INTEGER",
})
ensure_columns("todos", {
    "completed_at": "DATETIME",
})
ensure_columns("contract_reminders", {
    "notes": "TEXT",
    "should_cancel": "BOOLEAN DEFAULT 0",
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
ensure_columns("business_projects", {
    "account_id": "INTEGER",
})
ensure_columns("settings", {
    "native_sync_secret_encrypted": "VARCHAR",
})
ensure_columns("holdings", {
    "import_source": "VARCHAR",
})
ensure_columns("settings", {
    "scalable_enabled": "BOOLEAN DEFAULT 0",
    "scalable_last_sync_at": "DATETIME",
    "scalable_last_sync_status": "VARCHAR",
    "scalable_space_id": "INTEGER",
})
ensure_columns("spaces", {
    "last_digest_net_worth": "FLOAT",
})

# updated_at fuer den Offline-Sync des nativen Clients (siehe sync.py) - fehlte
# bisher auf fast allen Tabellen ausser todos/calendar_events, ohne die Spalte
# ist kein Diff-Sync ("was hat sich seit dem letzten Pull geaendert") moeglich.
# Backfill laeuft idempotent bei jedem Start mit (WHERE updated_at IS NULL),
# kein separates Migrations-Tracking noetig.
_SYNC_UPDATED_AT_TABLES = [
    "spaces", "accounts", "categories", "budgets", "trips", "holdings",
    "holding_lots", "transactions", "debts", "debt_payments", "goals",
    "goal_triggers", "goal_progress", "alert_rules", "contract_reminders",
    "return_deadlines", "net_worth_snapshots", "business_projects",
    "business_issues", "life_areas", "life_checkins", "wishlist_items",
    "account_balance_log", "creditcard_bills",
]
for _table in _SYNC_UPDATED_AT_TABLES:
    ensure_columns(_table, {"updated_at": "DATETIME"})
with engine.connect() as _conn:
    for _table in _SYNC_UPDATED_AT_TABLES:
        _cols = {row[1] for row in _conn.exec_driver_sql(f"PRAGMA table_info({_table})")}
        _fallback = "created_at" if "created_at" in _cols else "CURRENT_TIMESTAMP"
        _conn.exec_driver_sql(
            f"UPDATE {_table} SET updated_at = {_fallback} WHERE updated_at IS NULL"
        )
    _conn.commit()

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
    # "/" und "/index.html" fehlten hier bisher - normales heuristisches
    # Browser-Caching konnte die HTML-Seite tagelang veraltet halten, waehrend
    # style.css/app.js (schon abgesichert) frisch nachgeladen wurden. Neues JS
    # gegen eine alte, gecachte Seite ohne die dort erwarteten Elemente
    # (fehlende IDs -> addEventListener auf null -> Abbruch mitten im Skript)
    # sah dann wie "alle Daten weg" aus, obwohl der Server alles hatte.
    if request.url.path in ("/", "/index.html", "/style.css", "/app.js", "/sw.js"):
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


# ---------------- Heute / Fokus ----------------
# Fenster für den Fokus-View. Bewusst unterschiedlich weit: eine Kündigungs-
# oder Rückgabefrist muss man ein paar Tage vorher sehen (sonst ist sie weg),
# eine Abbuchung interessiert nur kurzfristig, und ein Ziel mit Datum darf
# ruhig einen Monat vorher auftauchen, weil man dafür noch handeln kann.
TODAY_DEADLINE_WINDOW_DAYS = 14
TODAY_PAYMENT_WINDOW_DAYS = 7
TODAY_GOAL_WINDOW_DAYS = 30
TODAY_GOAL_NEAR_PERCENT = 80.0
TODAY_MAX_DEADLINES = 8
TODAY_MAX_GOALS = 5


@api_router.get("/today", response_model=schemas.TodayOut)
def today_overview(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    """Alles, was HEUTE ansteht, in einer Antwort - Termine, offene/überfällige
    To-Dos, ablaufende Fristen, nahe Ziele und die Tagesbilanz.

    Bewusst ein Backend-Endpunkt statt (wie beim übrigen Hub) mehrerer
    Einzelaufrufe im Frontend: die Zusammenstellung „was ist heute dran" ist
    fachliche Logik mit Schwellwerten (welche Frist gilt als bald, wie weit
    schaut das Fenster für Zahlungen), die auch der Telegram-Digest brauchen
    kann - die soll nicht doppelt im Frontend liegen.

    Kein Kalender-Sync hier (anders als /calendar-events): der Fokus-View wird
    bei jedem Hub-Aufruf geladen, ein CalDAV-Roundtrip pro Aufruf wäre zu teuer.
    Der Hintergrund-Sync hält die Termine ohnehin aktuell."""
    today = date.today()
    day_start = datetime.combine(today, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    # --- Termine des Tages, inkl. Fahrzeit/„losfahren um" wo berechenbar ---
    events: list[schemas.TodayEvent] = []
    raw_events = crud.get_calendar_events(db, day_start, day_end)
    settings = auth.get_or_create_settings(db)
    home_coords = None
    ors_key = None
    if settings.home_lat and settings.home_lon and settings.openroute_api_key_encrypted:
        home_coords = (settings.home_lat, settings.home_lon)
        ors_key = bank_sync.decrypt_secret(settings.secret_key, settings.openroute_api_key_encrypted)
    for ev in raw_events:
        minutes = None
        if ors_key and home_coords and not ev.all_day and ev.lat and ev.lon and ev.start >= datetime.utcnow():
            try:
                minutes = travel_time.travel_time_minutes(ors_key, home_coords, (ev.lat, ev.lon))
            except Exception:
                minutes = None  # Fahrzeit ist Zusatzinfo, kein Grund den View zu kippen
        events.append(schemas.TodayEvent(
            id=ev.id, title=ev.title, start=ev.start, end=ev.end, location=ev.location,
            all_day=ev.all_day, travel_minutes=minutes,
            leave_at=(ev.start - timedelta(minutes=minutes)) if minutes else None,
        ))
    events.sort(key=lambda e: (not e.all_day, e.start))

    # --- To-Dos: heute fällig oder überfällig (undatierte gehören nicht in
    #     einen Tagesfokus - die stehen weiter unten in der normalen Liste) ---
    todos = [
        schemas.TodayTodo(id=t.id, title=t.title, due_date=t.due_date, overdue=t.due_date < today)
        for t in crud.get_todos(db, include_done=False)
        if t.due_date and t.due_date <= today
    ]
    todos.sort(key=lambda t: t.due_date)

    # --- Fristen: Kündigung, Rücksendung, anstehende Abbuchungen ---
    deadlines: list[schemas.TodayDeadline] = []
    for r in crud.get_contract_reminders(db, space_id):
        if r.days_until_reminder <= TODAY_DEADLINE_WINDOW_DAYS:
            deadlines.append(schemas.TodayDeadline(
                kind="kuendigung", label=r.label, date=r.reminder_date,
                days_left=r.days_until_reminder,
                detail=f"Verlängerung {r.renewal_date.strftime('%d.%m.%Y')}, {r.notice_period_days} Tage Frist",
            ))
    for d in crud.get_return_deadlines(db, space_id):
        if not d.returned and d.days_left <= TODAY_DEADLINE_WINDOW_DAYS:
            deadlines.append(schemas.TodayDeadline(
                kind="ruecksendung", label=d.transaction_description or "Rückgabe",
                date=d.deadline_date, days_left=d.days_left, amount=d.transaction_amount,
            ))
    try:
        forecast = crud.cashflow_forecast(db, space_id, horizon_days=TODAY_PAYMENT_WINDOW_DAYS)
        for e in forecast.upcoming_events:
            deadlines.append(schemas.TodayDeadline(
                kind="zahlung", label=e.description or "Abbuchung", date=e.date,
                days_left=(e.date - today).days, amount=e.amount,
            ))
    except Exception:
        pass  # Prognose braucht genug Historie - fehlt sie, bleibt der Rest nutzbar
    deadlines.sort(key=lambda d: d.days_left)

    # --- Ziele mit nahem Zieldatum bzw. kurz vor dem Ziel ---
    goals: list[schemas.TodayGoal] = []
    for g in crud.get_goals(db, space_id):
        out = goal_out(db, g, evaluate=True)
        if out.status != schemas.GoalStatus.open:
            continue
        days_left = (out.target_date - today).days if out.target_date else None
        near_date = days_left is not None and days_left <= TODAY_GOAL_WINDOW_DAYS
        near_done = out.progress_percent is not None and out.progress_percent >= TODAY_GOAL_NEAR_PERCENT
        if near_date or near_done:
            goals.append(schemas.TodayGoal(
                id=out.id, title=out.title, target_date=out.target_date,
                progress_percent=out.progress_percent, days_left=days_left,
            ))
    db.commit()  # evtl. automatisch erreichte Ziele festschreiben (wie in list_goals)
    goals.sort(key=lambda g: (g.days_left if g.days_left is not None else 99999))

    return schemas.TodayOut(
        date=today, events=events, todos=todos, deadlines=deadlines[:TODAY_MAX_DEADLINES],
        goals=goals[:TODAY_MAX_GOALS], balance=crud.day_balance(db, space_id, today),
    )


def _scheduled_auto_backup():
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        if not settings.auto_backup_enabled:
            return
        write_backup_to_disk(settings.backup_retention)
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


app.include_router(api_router)
app.include_router(investments_router)
app.include_router(tax_router)
app.include_router(debts_router)
app.include_router(goals_router)
app.include_router(trips_router)
app.include_router(wishlist_router)
app.include_router(personal_router)
app.include_router(business_life_router)
app.include_router(budgets_alerts_router)
app.include_router(deadlines_router)
app.include_router(calendar_todos_router)
app.include_router(categories_router)
app.include_router(immich_router)
app.include_router(bank_connections_router)
app.include_router(enablebanking_ebay_router)
app.include_router(mail_router)
app.include_router(spaces_accounts_router)
app.include_router(backup_router)
app.include_router(export_import_router)
app.include_router(analytics_router)
app.include_router(settings_misc_router)
app.include_router(notify_settings_router)
app.include_router(dashboard_router)
app.include_router(profile_ollama_router)
app.include_router(sync_all_router)
app.include_router(ai_assistant_router)
app.include_router(sync_router)


def _scheduled_bank_sync():
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        sync_all_connections(db, settings)
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


def _scheduled_ai_maintenance():
    """Stündlich: Umbuchungen erkennen und offene Buchungen automatisch
    kategorisieren, für jeden Bereich getrennt (Kategorien sind zwar global,
    Buchungen aber nicht)."""
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        for space in crud.get_spaces(db):
            try:
                run_ai_maintenance_for_space(db, space.id, settings)
            except Exception:
                db.rollback()

        # Belege aus dem Postfach laufen im selben Stundentakt mit - ein
        # eigener Zeitplan waere nur eine weitere Stellschraube ohne Nutzen.
        # Fehler duerfen die Kategorisierung nicht mitreissen.
        if settings.mail_enabled and settings.imap_host:
            for space in crud.get_spaces(db):
                try:
                    run_mail_sync(db, space.id)
                except Exception:
                    db.rollback()
    finally:
        db.close()


def _scheduled_anomaly_check():
    """Alle 30 Minuten: Preiserhöhungen bei Abos, Ausgaben-Ausreißer und
    überschneidende Termine sofort per Telegram melden, statt nur im
    3-Stunden-Digest aufzutauchen - nutzt die schon vorhandenen Auswertungen
    (detect_price_increases/detect_spending_anomalies/detect_calendar_conflicts,
    sonst nur passiv in der App sichtbar). NotifiedAnomaly verhindert, dieselbe
    Auffälligkeit bei jedem Lauf erneut zu schicken (siehe dort für die
    Begründung)."""
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        if not settings.notifications_enabled:
            return
        spaces = crud.get_spaces(db)
        for space in spaces:
            try:
                for inc in crud.detect_price_increases(db, space.id):
                    key = f"price:{space.id}:{inc['account_id']}:{inc['description']}:{inc['new_amount']}"
                    if crud.is_anomaly_notified(db, space.id, key):
                        continue
                    notifications.notify(
                        settings,
                        f"💸 Preiserhöhung erkannt: „{inc['description']}“ ({inc['account_name']}) "
                        f"{inc['old_amount']:.2f} € → {inc['new_amount']:.2f} € ({inc['increase_pct']:.0f}% mehr).",
                    )
                    crud.mark_anomaly_notified(db, space.id, key)

                today = date.today()
                for an in crud.detect_spending_anomalies(db, space.id):
                    key = f"spend:{space.id}:{an['category_id']}:{today.year}:{today.month}"
                    if crud.is_anomaly_notified(db, space.id, key):
                        continue
                    notifications.notify(
                        settings,
                        f"📈 Ausgaben-Ausreißer: „{an['category_name']}“ liegt diesen Monat hochgerechnet bei "
                        f"{an['projected_spent']:.2f} € (sonst ø {an['avg_prior_months']:.2f} €, "
                        f"+{an['deviation_pct']:.0f}%).",
                    )
                    crud.mark_anomaly_notified(db, space.id, key)
            except Exception:
                db.rollback()

        # Termine sind bereichsübergreifend (kein space_id) - Konflikte deshalb
        # nur einmal prüfen, nicht pro Bereich, sonst käme dieselbe Meldung
        # mehrfach. NotifiedAnomaly braucht trotzdem ein space_id (FK
        # not null) - der erste Bereich dient hier nur als Namensraum.
        if spaces:
            try:
                for c in crud.detect_calendar_conflicts(db):
                    key = f"conflict:{min(c['event_a_id'], c['event_b_id'])}:{max(c['event_a_id'], c['event_b_id'])}"
                    if crud.is_anomaly_notified(db, spaces[0].id, key):
                        continue
                    notifications.notify(
                        settings,
                        f"⚠️ Terminüberschneidung: „{c['event_a_title']}“ ({c['event_a_start'].strftime('%d.%m. %H:%M')}) "
                        f"und „{c['event_b_title']}“ ({c['event_b_start'].strftime('%d.%m. %H:%M')}).",
                    )
                    crud.mark_anomaly_notified(db, spaces[0].id, key)
            except Exception:
                db.rollback()
    finally:
        db.close()


def _scheduled_alert_rules():
    """Alle 30 Minuten: nutzerdefinierte Regeln (Einstellungen → Benach-
    richtigungen → Eigene Regeln) prüfen und bei Auslösung sofort per
    Telegram melden. last_triggered_date statt der dauerhaften NotifiedAnomaly-
    Logik, damit z.B. ein weiter zu niedriger Kontostand nicht nach einer
    einzigen Meldung verstummt - stattdessen hoechstens einmal pro Tag."""
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        if not settings.notifications_enabled:
            return
        today = date.today()
        for space in crud.get_spaces(db):
            rules = db.query(models.AlertRule).filter(
                models.AlertRule.space_id == space.id, models.AlertRule.active.is_(True),
            ).all()
            for rule in rules:
                if rule.last_triggered_date == today:
                    continue
                try:
                    triggered, message = crud.evaluate_alert_rule(db, rule)
                except Exception:
                    db.rollback()
                    continue
                if triggered:
                    notifications.notify(settings, message)
                    rule.last_triggered_date = today
                    db.commit()
    finally:
        db.close()


def _scheduled_business_check_reminder():
    """Einmal täglich: Business-Projekte mit hinterlegtem Prüf-Intervall
    (check_interval_days) erinnern, wenn seit last_checked_at (bzw.
    created_at, falls noch nie geprüft) zu lange nichts passiert ist -
    das Sekretariats-Prinzip aus models.BusinessProject: Kies kann nicht
    selbst prüfen, ob z.B. ein Roblox-Spiel noch läuft, aber dafür sorgen,
    dass der Nutzer regelmäßig aktiv hinschaut. last_reminded_date begrenzt
    auf höchstens eine Erinnerung pro Tag und Projekt."""
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        if not settings.notifications_enabled:
            return
        today = date.today()
        now = datetime.utcnow()
        projects = db.query(models.BusinessProject).filter(
            models.BusinessProject.active.is_(True),
            models.BusinessProject.check_interval_days.isnot(None),
        ).all()
        for p in projects:
            if p.last_reminded_date == today:
                continue
            reference = p.last_checked_at or p.created_at
            if not reference or (now - reference).days < p.check_interval_days:
                continue
            try:
                open_count = (
                    db.query(models.BusinessIssue)
                    .filter(models.BusinessIssue.project_id == p.id, models.BusinessIssue.resolved.is_(False))
                    .count()
                )
                days_ago = (now - reference).days
                offene = f" · {open_count} offene(r) Punkt(e)" if open_count else ""
                notifications.notify(
                    settings,
                    f"📋 Prüfung fällig: „{p.name}“ seit {days_ago} Tagen nicht bestätigt{offene}. "
                    f"Per /projekt_geprueft {p.name} bestätigen, wenn alles ok ist.",
                )
                p.last_reminded_date = today
                db.commit()
            except Exception:
                # Ein Fehler bei einem Projekt (z.B. DB-Hänger) darf die
                # übrigen Projekte in diesem Lauf nicht mit abbrechen.
                db.rollback()
                continue
    finally:
        db.close()


def _scheduled_life_check_reminder():
    """Einmal täglich: persönliche Lebensbereiche mit hinterlegtem Check-
    Intervall erinnern, wenn seit dem letzten Check-in zu lange nichts kam -
    exakt dasselbe Prinzip wie _scheduled_business_check_reminder, nur für
    models.LifeArea statt BusinessProject (Nutzerwunsch nach aktivem
    Nachhaken, nicht nur passivem Anzeigen - "strenger Vater"-Prinzip)."""
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        if not settings.notifications_enabled:
            return
        today = date.today()
        now = datetime.utcnow()
        areas = db.query(models.LifeArea).filter(
            models.LifeArea.active.is_(True),
            models.LifeArea.check_interval_days.isnot(None),
        ).all()
        for a in areas:
            if a.last_reminded_date == today:
                continue
            reference = a.last_checked_at or a.created_at
            if not reference or (now - reference).days < a.check_interval_days:
                continue
            try:
                days_ago = (now - reference).days
                fortschritt = f" · Fortschritt {a.progress_percent}%" if a.progress_percent is not None else ""
                notifications.notify(
                    settings,
                    f"🎯 Check-in fällig: „{a.name}“ seit {days_ago} Tagen nichts eingetragen{fortschritt}. "
                    f"Per /leben {a.name}; <Notiz> eintragen, sonst kommst du vom Kurs ab.",
                )
                a.last_reminded_date = today
                db.commit()
            except Exception:
                db.rollback()
                continue
    finally:
        db.close()


def _scheduled_wishlist_reminder():
    """Einmal täglich: Wunschlisten-Einträge mit Prüf-Intervall erinnern,
    selbst nachzuschauen - die zuverlässige Grundfunktion (kein Preis-
    Versprechen, nur eine Erinnerung), unabhängig von der experimentellen
    Auto-Prüfung unten."""
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        if not settings.notifications_enabled:
            return
        today = date.today()
        now = datetime.utcnow()
        items = db.query(models.WishlistItem).filter(
            models.WishlistItem.active.is_(True), models.WishlistItem.purchased.is_(False),
            models.WishlistItem.check_interval_days.isnot(None),
        ).all()
        for i in items:
            if i.last_reminded_date == today:
                continue
            reference = i.last_checked_at or i.created_at
            if not reference or (now - reference).days < i.check_interval_days:
                continue
            try:
                preis = f" (Zielpreis {i.target_price:.2f} EUR)" if i.target_price else ""
                notifications.notify(
                    settings,
                    f"🛒 Schau mal nach: „{i.name}“{preis} - seit {(now - reference).days} Tagen nicht geprüft.",
                )
                i.last_reminded_date = today
                db.commit()
            except Exception:
                db.rollback()
                continue
    finally:
        db.close()


EVENING_REVIEW_HOUR = 21


def _scheduled_evening_review():
    """Einmal täglich abends: fester Tagesrhythmus statt nur der Intervall-
    basierten Einzel-Erinnerungen oben - Nutzerwunsch nach einem täglichen
    Fixpunkt ("strenger Vater"-Prinzip: nicht nur bei einer überfälligen
    Woche nachhaken, sondern jeden Abend kurz Bilanz). Ergänzt die
    intervallbasierten Jobs, ersetzt sie nicht - die bleiben für längere
    Rhythmen (wöchentlich etc.) zuständig. Läuft nur, wenn überhaupt ein
    Lebensbereich existiert, sonst wäre es ein Ping ins Leere."""
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        if not settings.notifications_enabled:
            return
        areas = db.query(models.LifeArea).filter(models.LifeArea.active.is_(True)).all()
        if not areas:
            return

        today_start = datetime.combine(date.today(), datetime.min.time())
        lines = ["🌙 Tagesbilanz:"]
        missing_today = [
            a.name for a in areas
            if not db.query(models.LifeCheckIn)
            .filter(models.LifeCheckIn.area_id == a.id, models.LifeCheckIn.created_at >= today_start)
            .first()
        ]
        if missing_today:
            lines.append("Heute noch kein Check-in: " + ", ".join(f"„{n}“" for n in missing_today) + ".")
        else:
            lines.append("Alle Lebensbereiche heute schon eingecheckt. 👍")

        open_issues = db.query(models.BusinessIssue).filter(models.BusinessIssue.resolved.is_(False)).count()
        if open_issues:
            lines.append(f"📋 {open_issues} offene Projekt-Punkt(e) insgesamt.")

        now = datetime.utcnow()
        overdue_wishlist = [
            w for w in db.query(models.WishlistItem).filter(
                models.WishlistItem.active.is_(True), models.WishlistItem.purchased.is_(False),
                models.WishlistItem.check_interval_days.isnot(None),
            ).all()
            if (now - (w.last_checked_at or w.created_at)).days >= w.check_interval_days
        ]
        if overdue_wishlist:
            lines.append(f"🛒 {len(overdue_wishlist)} Wunschlisten-Eintrag/Einträge überfällig.")

        notifications.notify(settings, "\n".join(lines))
    finally:
        db.close()


WEEKLY_REVIEW_WEEKDAY = "sun"
WEEKLY_REVIEW_HOUR = 20


def _scheduled_weekly_review():
    """Einmal wöchentlich (Sonntagabend): Rückblick über ALLE Bereiche der
    App, nicht nur Finanzen - Nutzerwunsch nach einem regelmäßigen
    Gesamtüberblick. Ergänzt _scheduled_evening_review (täglich, nur Leben)
    und build_digest (mehrmals täglich, nur Finanzen je Space) um eine
    wöchentliche bereichsübergreifende Sicht. Bewusst ein eigener,
    standalone Job statt Erweiterung von build_digest - das würde bei
    mehreren Spaces die space-losen Bereiche (Projekte/Leben/Wunschliste)
    mehrfach melden, siehe crud.build_digest-Docstring."""
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        if not settings.notifications_enabled:
            return
        lines = ["📅 Wochenrückblick:"]

        week_ago = date.today() - timedelta(days=7)
        for space in crud.get_spaces(db):
            nw = crud.net_worth(db, space.id)
            snapshot = (
                db.query(models.NetWorthSnapshot)
                .filter(models.NetWorthSnapshot.space_id == space.id, models.NetWorthSnapshot.date <= week_ago)
                .order_by(models.NetWorthSnapshot.date.desc())
                .first()
            )
            verlauf = ""
            if snapshot:
                delta = round(nw.total - snapshot.total, 2)
                pfeil = "📈" if delta > 0 else ("📉" if delta < 0 else "➡️")
                verlauf = f" ({pfeil} {delta:+.2f} EUR diese Woche)"
            lines.append(f"💰 {space.name}: {nw.total:.2f} EUR{verlauf}")

        projects = db.query(models.BusinessProject).filter(models.BusinessProject.active.is_(True)).all()
        if projects:
            open_issues = db.query(models.BusinessIssue).filter(models.BusinessIssue.resolved.is_(False)).count()
            lines.append(f"📋 {len(projects)} aktive(s) Projekt(e), {open_issues} offene Punkt(e).")

        areas = db.query(models.LifeArea).filter(models.LifeArea.active.is_(True)).all()
        if areas:
            teile = []
            for a in areas:
                _, streak = crud._life_area_streak_and_history(db, a.id)
                teile.append(f"„{a.name}“ {streak}d" if streak else f"„{a.name}“ –")
            lines.append("🔥 Streaks: " + ", ".join(teile))

        wishlist_count = (
            db.query(models.WishlistItem)
            .filter(models.WishlistItem.active.is_(True), models.WishlistItem.purchased.is_(False))
            .count()
        )
        if wishlist_count:
            lines.append(f"🛒 {wishlist_count} offene(r) Wunschlisten-Eintrag/Einträge.")

        if len(lines) == 1:
            return
        notifications.notify(settings, "\n".join(lines))
    finally:
        db.close()


WISHLIST_AUTO_CHECK_BATCH_SIZE = 3
WISHLIST_AUTO_CHECK_MIN_HOURS = 20  # nicht öfter als ~1x/Tag pro Eintrag, Suchanfragen sind begrenzt


def _scheduled_wishlist_auto_check():
    """EXPERIMENTELL, täglich: für Wunschlisten-Einträge mit auto_check_enabled
    per Brave-Suche + Ollama grob einschätzen, ob gerade ein Deal vorliegt -
    siehe models.WishlistItem für die ausführliche Begründung (keine echte
    Preis-API angebunden, kann Deals verpassen oder falsch Alarm schlagen).
    Läuft in kleinen Batches wie main._scheduled_receipt_indexing, um die
    Suchanfragen zu begrenzen. Jede Meldung sagt klar, dass es eine
    KI-Einschätzung ist, kein verifizierter Preis."""
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        if not settings.notifications_enabled or not websearch_configured(settings):
            return
        chat_model = settings.ollama_model or settings.beleg_chat_model
        if not settings.ollama_url or not chat_model:
            return

        cutoff = datetime.utcnow() - timedelta(hours=WISHLIST_AUTO_CHECK_MIN_HOURS)
        items = (
            db.query(models.WishlistItem)
            .filter(
                models.WishlistItem.active.is_(True), models.WishlistItem.purchased.is_(False),
                models.WishlistItem.auto_check_enabled.is_(True),
                (models.WishlistItem.last_auto_check_at.is_(None)) | (models.WishlistItem.last_auto_check_at < cutoff),
            )
            # Ohne Sortierung liefert ein LIMIT bei mehr als BATCH_SIZE aktiven
            # Einträgen jeden Tag dieselben (niedrigste ID) zuerst - waeren es
            # mehr als 3, kaemen spaeter angelegte nie an die Reihe. Laengst
            # nicht geprueft (bzw. noch nie, NULL sortiert in SQLite zuerst)
            # zuerst rotiert fair durch.
            .order_by(models.WishlistItem.last_auto_check_at.asc())
            .limit(WISHLIST_AUTO_CHECK_BATCH_SIZE)
            .all()
        )
        for item in items:
            item.last_auto_check_at = datetime.utcnow()
            db.commit()
            try:
                query = f"{item.name} günstig Angebot Preis"
                if item.target_price:
                    query += f" unter {item.target_price:.0f} Euro"
                results = websearch_run(settings, query)
                if not results:
                    continue
                prompt = (
                    "Du bekommst Web-Suchergebnisse zu einem Wunsch-Artikel. Schätze NUR anhand dieser "
                    "Ergebnisse ein, ob gerade ein besonders günstiges Angebot/ein Deal vorliegt "
                    f"(Zielpreis, falls genannt: {item.target_price} EUR). Wenn ja, nenne kurz Preis/Quelle. "
                    "Wenn unklar oder kein echter Deal erkennbar, antworte NUR mit 'NEIN'. Antworte NUR mit "
                    "'NEIN' oder einem kurzen Satz auf Deutsch, sonst nichts.\n\n"
                    + websearch.format_for_prompt(query, results)
                )
                antwort = ollama_client.chat(settings.ollama_url, chat_model, [{"role": "user", "content": prompt}], timeout=120)
                antwort = antwort.strip()
                if antwort and not antwort.upper().startswith("NEIN"):
                    notifications.notify(
                        settings,
                        f"🤖💸 Möglicher Deal bei „{item.name}“ (KI-Einschätzung, KEIN verifizierter Preis - "
                        f"selbst prüfen!): {antwort}",
                    )
            except Exception:
                db.rollback()
                continue
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
    Warnungen in _check_daily_alerts - beides laeuft unabhaengig nebeneinander.

    Synct vor jeder Meldung erst alle Bank-/Broker-Verbindungen (siehe
    sync_all_connections), damit das gemeldete Nettovermögen nicht auf dem
    Stand vom letzten taeglichen Sync-Lauf haengt, sondern frisch ist -
    bewusst OHNE Investment-Kurse (siehe sync_all_connections-Docstring)."""
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        sync_all_connections(db, settings)

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
                # Erst NACH erfolgreichem Versand fortschreiben - sonst wuerde
                # ein Fehler beim Senden den Vergleichswert trotzdem verbrauchen
                # und der naechste Digest faelschlich "keine Aenderung" zeigen.
                space.last_digest_net_worth = crud.net_worth(db, space.id).total
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


TRAVEL_PREP_BUFFER_MINUTES = 10  # Zeit zum Fertigmachen/Anziehen vor der reinen Fahrzeit


def _scheduled_travel_reminder():
    """Alle 5 Minuten: rechtzeitig vor einem Termin mit Ort per Telegram zum
    Losfahren auffordern, statt die Fahrzeit nur passiv im Digest zu zeigen -
    genau der proaktive "Jarvis"-Charakter, den sich der Nutzer gewünscht hat.
    travel_reminder_sent verhindert eine Wiederholung fuer denselben Termin."""
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        if not settings.notifications_enabled:
            return
        if not (settings.home_lat and settings.home_lon and settings.openroute_api_key_encrypted):
            return
        home_coords = (settings.home_lat, settings.home_lon)
        api_key = bank_sync.decrypt_secret(settings.secret_key, settings.openroute_api_key_encrypted)

        now = datetime.utcnow()
        events = (
            db.query(models.CalendarEvent)
            .filter(
                models.CalendarEvent.all_day.is_(False),
                models.CalendarEvent.lat.isnot(None),
                models.CalendarEvent.lon.isnot(None),
                models.CalendarEvent.travel_reminder_sent.is_(False),
                models.CalendarEvent.start > now,
                models.CalendarEvent.start <= now + timedelta(hours=3),
            )
            .all()
        )
        for ev in events:
            try:
                minutes = travel_time.travel_time_minutes(api_key, home_coords, (ev.lat, ev.lon))
            except Exception:
                continue
            if minutes is None:
                continue

            buffer_minutes = TRAVEL_PREP_BUFFER_MINUTES
            rain_note = ""
            try:
                rain_pct = weather.precipitation_probability_percent(*home_coords, ev.start)
            except Exception:
                rain_pct = None
            # Bei Regenwahrscheinlichkeit ab 50% etwas mehr Puffer (langsamerer
            # Verkehr, Parkplatzsuche im Regen usw.) statt nur die reine Fahrzeit.
            if rain_pct is not None and rain_pct >= 50:
                buffer_minutes += 10
                rain_note = f" 🌧 Regenwahrscheinlichkeit {rain_pct}%, etwas mehr Puffer eingeplant."

            leave_by = ev.start - timedelta(minutes=minutes + buffer_minutes)
            if now >= leave_by:
                notifications.notify(
                    settings,
                    f"🚗 Los geht's: Fahrzeit ca. {minutes} Min zu „{ev.title}“ um "
                    f"{ev.start.strftime('%H:%M')}. Jetzt losfahren, um pünktlich zu sein.{rain_note}",
                )
                ev.travel_reminder_sent = True
                db.commit()
    finally:
        db.close()


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
            # Mehrere Kalender-Collections, kommagetrennt (z.B. Privat, Arbeit,
            # Urlaub getrennt gefuehrt) - jede einzeln syncen, damit sync_calendar
            # seine Loeschung nur auf den jeweils eigenen Pfad-Praefix begrenzt.
            for cal_url in [u.strip() for u in settings.radicale_calendar_url.split(",") if u.strip()]:
                try:
                    radicale_sync.sync_calendar(db, cal_url, settings.radicale_username, password)
                except Exception:
                    pass
            _geocode_missing_event_locations(db)
    finally:
        db.close()


RECEIPT_INDEX_BATCH_SIZE = 5


def _scheduled_receipt_indexing():
    """Alle 10 Minuten ein kleines Häppchen noch nicht indexierter Belege für
    die Beleg-Suche einlesen (document_extract.extract_receipt_text) - in
    kleinen Batches statt auf einen Schlag, weil ein Foto/gescanntes PDF ohne
    eingebetteten Text über das (auf Produktion langsame, CPU-gebundene)
    Vision-Modell laufen muss. Durchsuchbare PDFs sind dagegen sofort fertig
    (reiner PyMuPDF-Text, kein KI-Aufruf). receipt_indexed_at wird immer
    gesetzt, auch bei leerem Ergebnis, sonst würde ein dauerhaft nicht
    lesbarer Beleg bei jedem Lauf erneut versucht."""
    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        pending = (
            db.query(models.Transaction)
            .filter(
                models.Transaction.receipt_filename.isnot(None),
                models.Transaction.receipt_indexed_at.is_(None),
            )
            .limit(RECEIPT_INDEX_BATCH_SIZE)
            .all()
        )
        for tx in pending:
            path = os.path.join(UPLOAD_DIR, tx.receipt_filename)
            try:
                with open(path, "rb") as f:
                    content = f.read()
                text = document_extract.extract_receipt_text(
                    settings.ollama_url, settings.ollama_model, settings.beleg_chat_model,
                    content, tx.receipt_filename,
                )
            except Exception:
                text = None
            tx.receipt_text = text
            tx.receipt_indexed_at = datetime.utcnow()
            db.commit()
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
        url, key = immich_credentials(db)
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
    _scheduled_anomaly_check, CronTrigger(minute="*/30"),
    id="anomaly_check", misfire_grace_time=900,
)
scheduler.add_job(
    _scheduled_alert_rules, CronTrigger(minute="*/30"),
    id="alert_rules", misfire_grace_time=900,
)
scheduler.add_job(
    _scheduled_business_check_reminder, CronTrigger(hour=8, minute=15),
    id="business_check_reminder", misfire_grace_time=3600,
)
scheduler.add_job(
    _scheduled_life_check_reminder, CronTrigger(hour=8, minute=30),
    id="life_check_reminder", misfire_grace_time=3600,
)
scheduler.add_job(
    _scheduled_wishlist_reminder, CronTrigger(hour=8, minute=45),
    id="wishlist_reminder", misfire_grace_time=3600,
)
scheduler.add_job(
    _scheduled_evening_review, CronTrigger(hour=EVENING_REVIEW_HOUR, minute=0),
    id="evening_review", misfire_grace_time=3600,
)
scheduler.add_job(
    _scheduled_weekly_review, CronTrigger(day_of_week=WEEKLY_REVIEW_WEEKDAY, hour=WEEKLY_REVIEW_HOUR, minute=0),
    id="weekly_review", misfire_grace_time=3600,
)
scheduler.add_job(
    _scheduled_wishlist_auto_check, CronTrigger(hour=9, minute=0),
    id="wishlist_auto_check", misfire_grace_time=3600,
)
scheduler.add_job(
    _scheduled_travel_reminder, CronTrigger(minute="*/5"),
    id="travel_reminder", misfire_grace_time=300,
)
scheduler.add_job(
    _scheduled_receipt_indexing, CronTrigger(minute="*/10"),
    id="receipt_indexing", misfire_grace_time=600,
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

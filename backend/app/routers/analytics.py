"""Analytics-Endpunkte: Cashflow-Forecast, Netto-Vermoegen, Benchmark,
Beleg-Suche, wiederkehrende-Zahlungen-Ignorieren.

Zwanzigster Schritt der Code-Modularisierung (siehe ROADMAP.md), nach
investments/tax/debts/goals/trips/wishlist/personal/business_life/
budgets_alerts/deadlines/calendar_todos/categories/immich_routes/
bank_connections/enablebanking_ebay/mail_routes/spaces_accounts/
backup_restore/export_import. Fuenf eigenstaendige, aber im main.py
zwischen den Kern-Transaktions-Endpunkten verstreute Analytics-Bloecke,
hier gebuendelt statt einzeln.

Bewusst NICHT mit hierher gezogen: /transactions/{id}/receipt (Upload/
Delete) und /settings/birth-year bleiben in main.py - Ersteres ist Teil
der Kern-Transaktions-CRUD (RECEIPT_ALLOWED_EXTENSIONS), Letzteres liegt
zwischen net-worth und benchmark, aber gehoert inhaltlich zu Settings.

UPLOAD_DIR eigenstaendig berechnet statt aus main importiert - main.py
importiert diesen Router beim Start VOR der Stelle, an der main.UPLOAD_DIR
definiert wird (siehe mail_routes.py/backup_restore.py-Docstring)."""

import os
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import schemas, crud, auth, benchmark
from ..database import get_db, DATA_DIR

UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

analytics_router = APIRouter(prefix="/api")


@analytics_router.get("/recurring-ignores", response_model=List[schemas.IgnoredRecurringPaymentOut])
def list_ignored_recurring_payments(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.get_ignored_recurring_payments(db, space_id)


@analytics_router.post("/recurring-ignores", response_model=schemas.IgnoredRecurringPaymentOut)
def add_ignored_recurring_payment(
    data: schemas.IgnoredRecurringPaymentCreate,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    return crud.create_ignored_recurring_payment(db, space_id, data)


@analytics_router.delete("/recurring-ignores/{ignore_id}")
def remove_ignored_recurring_payment(
    ignore_id: int,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    if not crud.delete_ignored_recurring_payment(db, ignore_id, space_id):
        raise HTTPException(404, "Eintrag nicht gefunden.")
    return {"ok": True}


@analytics_router.get("/forecast/cashflow", response_model=schemas.CashflowForecastOut)
def get_cashflow_forecast(days: int = 90, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    days = max(7, min(days, 365))
    return crud.cashflow_forecast(db, space_id, days)


@analytics_router.post("/forecast/cashflow/scenario", response_model=schemas.CashflowScenarioOut)
def get_cashflow_scenario(data: schemas.CashflowScenarioRequest, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    days = max(7, min(data.horizon_days, 365))
    return crud.cashflow_scenario(
        db, space_id, days,
        cancel_description_key=data.cancel_description_key,
        extra_monthly_saving=data.extra_monthly_saving,
        extra_monthly_expense=data.extra_monthly_expense,
    )


@analytics_router.get("/receipts/{filename}")
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


@analytics_router.get("/receipts/search/query", response_model=List[schemas.TransactionOut])
def search_receipts(q: str, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if len(q.strip()) < 2:
        return []
    return crud.search_receipts(db, space_id, q)


@analytics_router.get("/net-worth", response_model=schemas.NetWorthOut)
def get_net_worth(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.net_worth(db, space_id)


@analytics_router.get("/net-worth/history", response_model=schemas.NetWorthHistoryOut)
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


@analytics_router.get("/benchmark", response_model=schemas.BenchmarkOut)
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

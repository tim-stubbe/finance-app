"""Dashboard-Übersicht: Zusammenfassung, Top-Empfänger, Trend-Sparklines,
Jahresrückblick, geschäftliche Zusammenfassung (Filter auf is_business,
kein eigener Bereich).

Dreiundzwanzigster Schritt der Code-Modularisierung (siehe ROADMAP.md),
nach investments/tax/debts/goals/trips/wishlist/personal/business_life/
budgets_alerts/deadlines/calendar_todos/categories/immich_routes/
bank_connections/enablebanking_ebay/mail_routes/spaces_accounts/
backup_restore/export_import/analytics/settings_misc/notify_settings.
Reine Verschiebung ohne Verhaltensänderung."""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import schemas, crud, auth
from ..database import get_db

dashboard_router = APIRouter(prefix="/api")


# ---------------- Dashboard ----------------
@dashboard_router.get("/dashboard", response_model=schemas.DashboardSummary)
def dashboard(year: int = date.today().year, month: Optional[int] = None, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.dashboard_summary(db, space_id, year, month)


@dashboard_router.get("/dashboard/top-recipients", response_model=List[schemas.TopExpenseRecipientOut])
def dashboard_top_recipients(
    year: int = date.today().year, month: Optional[int] = None, limit: int = 10,
    db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id),
):
    limit = max(1, min(limit, 50))
    return crud.top_expense_recipients(db, space_id, year, month, limit)


@dashboard_router.get("/dashboard/trend", response_model=schemas.DashboardTrendOut)
def dashboard_trend(months: int = 6, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    """Kleine monatliche Einnahmen/Ausgaben-Reihe fuer die Sparklines auf dem
    Hub - bewusst ein eigener, leichtgewichtiger Endpunkt statt N Aufrufe von
    /dashboard je Monat vom Frontend aus."""
    months = max(2, min(months, 24))
    return schemas.DashboardTrendOut(points=[
        schemas.DashboardTrendPoint(**p) for p in crud.monthly_flow_trend(db, space_id, months)
    ])


@dashboard_router.get("/year-review", response_model=schemas.YearReviewOut)
def year_review(year: int = date.today().year, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    """Jahresrueckblick - reine Auswertung, keine neue Datenerfassung."""
    data = crud.year_review(db, space_id, year)
    return schemas.YearReviewOut(**data)


# ---------------- Geschäftlich (Filter auf is_business-Konten, kein eigener Bereich) ----------------
@dashboard_router.get("/business/summary", response_model=schemas.DashboardSummary)
def business_summary(year: int = date.today().year, month: Optional[int] = None, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.dashboard_summary(db, space_id, year, month, business_only=True)

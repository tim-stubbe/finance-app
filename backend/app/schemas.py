from datetime import date, datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict
from .models import (
    AccountType, CategoryType, AssetType, LotType,
    GoalType, GoalStatus, GoalMetricType, GoalComparison,
    DebtKind, DebtStatus, AlertRuleType, MediaStatus, HealthMetricType,
)


# ---------- Account ----------
class AccountBase(BaseModel):
    name: str
    type: AccountType = AccountType.girokonto
    initial_balance: float = 0.0
    is_business: bool = False


class AccountCreate(AccountBase):
    pass


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[AccountType] = None
    initial_balance: Optional[float] = None
    is_business: Optional[bool] = None


class AccountOut(AccountBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    current_balance: float = 0.0


class AccountBalanceLogOut(BaseModel):
    account_name: str
    old_balance: float
    new_balance: float
    source: str
    created_at: datetime


# ---------- Category ----------
class CategoryBase(BaseModel):
    name: str
    type: CategoryType
    parent_id: Optional[int] = None


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[CategoryType] = None
    parent_id: Optional[int] = None


class CategoryOut(CategoryBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class CategorySignMismatch(BaseModel):
    category_id: int
    category_name: str
    category_type: str
    count: int


# ---------- Space ----------
class SpaceCreate(BaseModel):
    name: str
    icon: str = "🏠"


class SpaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    icon: str


# ---------- Trip ----------
class TripCreate(BaseModel):
    name: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: Optional[float] = None


class TripUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: Optional[float] = None


class TripOut(BaseModel):
    id: int
    name: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: Optional[float] = None
    total_spent: float = 0.0
    transaction_count: int = 0
    missing_receipts_count: int = 0


# ---------- Transaction ----------
class TransactionBase(BaseModel):
    date: date
    amount: float
    description: Optional[str] = None
    notes: Optional[str] = None
    account_id: int
    category_id: Optional[int] = None
    trip_id: Optional[int] = None


class TransactionCreate(TransactionBase):
    pass


class TransactionUpdate(BaseModel):
    date: Optional[date] = None
    amount: Optional[float] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    account_id: Optional[int] = None
    category_id: Optional[int] = None
    trip_id: Optional[int] = None
    # Manuelle Korrektur, falls die automatische Umbuchungs-Erkennung (siehe
    # crud.detect_transfers) eine interne Bewegung zwischen eigenen Konten
    # nicht erkannt hat (z.B. Rundungssparen mit ungleichem Betrag auf beiden
    # Seiten, oder PayPal-Kartendeckung ohne exaktes Gegenstück).
    is_transfer: Optional[bool] = None


class TransactionOut(TransactionBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    receipt_filename: Optional[str] = None
    is_transfer: bool = False
    created_at: datetime

class BulkCategorizeRequest(BaseModel):
    transaction_ids: List[int]
    category_id: Optional[int] = None


class DuplicateTransactionGroup(BaseModel):
    account_id: int
    account_name: str
    date: date
    amount: float
    description: Optional[str] = None
    transaction_ids: List[int]


# ---------- Profil ----------
class ProfileOut(BaseModel):
    display_name: str


class ProfileUpdate(BaseModel):
    display_name: str


# ---------- Budget ----------
class BudgetCreate(BaseModel):
    category_id: int
    monthly_limit: float


class BudgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category_id: int
    category_name: str
    monthly_limit: float


class AlertRuleCreate(BaseModel):
    rule_type: AlertRuleType
    category_id: Optional[int] = None
    account_id: Optional[int] = None
    goal_id: Optional[int] = None
    threshold: float
    active: bool = True


class AlertRuleUpdate(BaseModel):
    threshold: Optional[float] = None
    active: Optional[bool] = None


class AlertRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule_type: AlertRuleType
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    account_id: Optional[int] = None
    account_name: Optional[str] = None
    goal_id: Optional[int] = None
    goal_title: Optional[str] = None
    threshold: float
    active: bool


class BudgetSuggestionOut(BaseModel):
    category_id: int
    category_name: str
    suggested_limit: float
    months_used: int
    avg_monthly_spend: float


class BudgetProgress(BaseModel):
    category_id: int
    category_name: str
    limit: float
    spent: float
    remaining: float
    percent: float
    # Nur gesetzt, wenn gerade der laufende Monat angezeigt wird - eine
    # Hochrechnung für einen abgeschlossenen oder zukünftigen Monat wäre
    # bedeutungslos. Zeigt, ob das aktuelle Tempo bis Monatsende übers
    # Limit tragen würde, bevor es tatsächlich so weit ist.
    projected_total: Optional[float] = None


# ---------- Holdings (Investments) ----------
class HoldingCreate(BaseModel):
    asset_type: AssetType
    name: str
    symbol: str
    sector: Optional[str] = None
    quantity: float
    purchase_price: float
    purchase_date: Optional[date] = None


class HoldingUpdate(BaseModel):
    asset_type: Optional[AssetType] = None
    name: Optional[str] = None
    symbol: Optional[str] = None
    sector: Optional[str] = None
    country: Optional[str] = None
    currency: Optional[str] = None
    current_price: Optional[float] = None


class HoldingOut(BaseModel):
    id: int
    asset_type: AssetType
    name: str
    symbol: str
    sector: Optional[str] = None
    country: Optional[str] = None
    currency: Optional[str] = None
    risk_level: str
    quantity: float
    purchase_price: float
    purchase_date: Optional[date] = None
    current_price: Optional[float] = None
    price_updated_at: Optional[datetime] = None
    import_source: Optional[str] = None
    purchase_value: float
    current_value: float
    gain_abs: float
    gain_pct: float
    lot_count: int = 0
    # Nur direkt nach dem Anlegen gefuellt (siehe main.create_holding) - kein
    # gespeichertes Feld, sondern eine einmalige Rueckmeldung an den Nutzer
    # ("mit bestehender Position zusammengefuehrt" / "Symbol nicht gefunden").
    price_warning: Optional[str] = None


class NetWorthOut(BaseModel):
    accounts_total: float
    investments_total: float
    debts_total: float = 0.0
    # Konten + Investments ohne Schulden
    gross_total: float = 0.0
    # Nettovermögen: gross_total - debts_total
    total: float


class NetWorthHistoryPoint(BaseModel):
    date: date
    accounts_total: float
    investments_total: float
    debts_total: float
    total: float


class NetWorthHistoryOut(BaseModel):
    points: List[NetWorthHistoryPoint]


class PriceRefreshResult(BaseModel):
    updated: int
    failed: List[str]
    holdings: List[HoldingOut]


# ---------- Holding-Lots (einzelne Käufe/Verkäufe) ----------
class HoldingLotCreate(BaseModel):
    date: date
    type: LotType = LotType.kauf
    quantity: float
    price_per_unit: float
    notes: Optional[str] = None


class HoldingLotUpdate(BaseModel):
    date: Optional[date] = None
    type: Optional[LotType] = None
    quantity: Optional[float] = None
    price_per_unit: Optional[float] = None
    notes: Optional[str] = None


class HoldingLotOut(BaseModel):
    id: int
    date: date
    type: LotType
    quantity: float
    price_per_unit: float
    notes: Optional[str] = None


# ---------- Kurshistorie & Portfolio-Verlauf ----------
class HoldingHistoryPoint(BaseModel):
    date: str
    price: float


class HoldingHistoryOut(BaseModel):
    holding: HoldingOut
    points: List[HoldingHistoryPoint]
    lots: List[HoldingLotOut]


class PortfolioHistoryPoint(BaseModel):
    date: str
    value: float
    invested: float
    return_pct: Optional[float] = None


class PortfolioHistoryOut(BaseModel):
    points: List[PortfolioHistoryPoint]
    partial: bool = False


# ---------- Diversifikation & Risiko ----------
class DiversificationSlice(BaseModel):
    label: str
    value: float
    percent: float


class RiskFlag(BaseModel):
    level: str
    message: str


class DiversificationOut(BaseModel):
    by_asset_type: List[DiversificationSlice]
    by_sector: List[DiversificationSlice]
    by_position: List[DiversificationSlice]
    by_region: List[DiversificationSlice]
    by_currency: List[DiversificationSlice]
    risk_flags: List[RiskFlag]


class HoldingVolatility(BaseModel):
    holding_id: int
    name: str
    volatility_pct: Optional[float] = None


class SavingsPlanOut(BaseModel):
    id: int
    isin: str
    name: str
    amount: float
    frequency: str
    day_of_month: Optional[int] = None
    dynamization_rate: Optional[float] = None
    next_execution_date: Optional[date] = None
    security_type: Optional[str] = None
    import_source: str

    model_config = ConfigDict(from_attributes=True)


class SavingsPlansOut(BaseModel):
    plans: List[SavingsPlanOut]
    total_monthly_amount: float


class VolatilityOut(BaseModel):
    holdings: List[HoldingVolatility]


# ---------- Dividenden ----------
class DividendPayment(BaseModel):
    date: str
    amount_per_share: float
    quantity: float
    total: float


class HoldingDividendsOut(BaseModel):
    holding_id: int
    name: str
    symbol: str
    history: List[DividendPayment]
    annual_rate_per_share: float
    annual_income_estimate: float
    forecast_1y: float
    forecast_5y: float
    forecast_10y: float


class YearlyDividendPoint(BaseModel):
    year: int
    total: float


class PortfolioDividendsOut(BaseModel):
    total_annual_income_estimate: float
    forecast_1y: float
    forecast_5y: float
    forecast_10y: float
    by_year: List[YearlyDividendPoint]
    holdings: List[HoldingDividendsOut]


class UpcomingDividendOut(BaseModel):
    holding_id: int
    name: str
    symbol: str
    estimated_date: date
    estimated_amount: float


# ---------- KI-Assistent (Ollama) ----------
class OllamaSettingsUpdate(BaseModel):
    url: str
    model: Optional[str] = None
    beleg_chat_model: Optional[str] = None


class OllamaSettingsOut(BaseModel):
    url: Optional[str] = None
    model: Optional[str] = None
    beleg_chat_model: Optional[str] = None


class OllamaModelsOut(BaseModel):
    models: List[str]


class OllamaPullRequest(BaseModel):
    model: str
    url: Optional[str] = None


class OllamaPullResult(BaseModel):
    ok: bool
    status: str


class AiTextResult(BaseModel):
    text: Optional[str] = None
    error: Optional[str] = None


class MissingReceiptsOut(BaseModel):
    transactions: List[TransactionOut]
    total_amount: float
    summary: Optional[str] = None


# ---------- Bank-Sync (FinTS) ----------
class BankConnectionCreate(BaseModel):
    name: str
    blz: str
    fints_url: str
    login: str
    pin: str
    account_id: int
    iban: str


class BankConnectionOut(BaseModel):
    id: int
    name: str
    blz: str
    fints_url: str
    login: str
    account_id: int
    iban: Optional[str] = None
    last_sync_at: Optional[datetime] = None
    last_sync_status: Optional[str] = None


class FintsSettingsUpdate(BaseModel):
    fints_product_id: str


class SyncResult(BaseModel):
    tan_required: bool = False
    challenge: Optional[str] = None
    imported: int = 0
    skipped: int = 0
    error: Optional[str] = None


class TanSubmit(BaseModel):
    tan: str


class SyncAllConnectionResult(BaseModel):
    name: str
    kind: str
    status: Optional[str] = None


class SyncAllResult(BaseModel):
    connections: List[SyncAllConnectionResult]


# ---------- Bitvavo (Krypto-Börse) ----------
class BitvavoConnectionCreate(BaseModel):
    name: str
    api_key: str
    api_secret: str


class BitvavoConnectionOut(BaseModel):
    id: int
    name: str
    last_sync_at: Optional[datetime] = None
    last_sync_status: Optional[str] = None


class BitvavoSyncResult(BaseModel):
    created: int = 0
    updated: int = 0
    failed: List[str] = []
    error: Optional[str] = None


# ---------- PayPal ----------
class PayPalConnectionCreate(BaseModel):
    name: str
    client_id: str
    client_secret: str
    account_id: int


class PayPalConnectionOut(BaseModel):
    id: int
    name: str
    account_id: int
    last_sync_at: Optional[datetime] = None
    last_sync_status: Optional[str] = None


class PayPalSyncResult(BaseModel):
    imported: int = 0
    skipped: int = 0
    error: Optional[str] = None


# ---------- Automatischer Sync (Zeitplan) ----------
class SyncScheduleOut(BaseModel):
    hour: int


class SyncScheduleUpdate(BaseModel):
    hour: int


# ---------- Morgen-Briefing & Quiet Mode ("Jarvis"-Verhalten) ----------
class MorningBriefingSettingsOut(BaseModel):
    enabled: bool
    hour: int
    minute: int
    send_empty: bool


class MorningBriefingSettingsUpdate(BaseModel):
    enabled: bool
    hour: int
    minute: int
    send_empty: bool


class QuietHoursSettingsOut(BaseModel):
    enabled: bool
    start_hour: int
    end_hour: int
    quiet_until: Optional[datetime] = None


class QuietHoursSettingsUpdate(BaseModel):
    enabled: bool
    start_hour: int
    end_hour: int


class QuietUntilUpdate(BaseModel):
    # None = manuelle Überschreibung sofort aufheben ("/ruhe aus"-Äquivalent
    # in der App).
    until: Optional[datetime] = None


class MidweekCheckinSettingsOut(BaseModel):
    enabled: bool


class MidweekCheckinSettingsUpdate(BaseModel):
    enabled: bool


class CommunicationStyleOut(BaseModel):
    style: str


class CommunicationStyleUpdate(BaseModel):
    style: str


class CategoryRuleOut(BaseModel):
    id: int
    pattern: str
    category_name: str
    created_at: datetime


class SyncErrorOut(BaseModel):
    source: str
    name: str
    status: str
    at: datetime


class AssistantSuggestionOut(BaseModel):
    id: int
    kind: str
    title: str
    status: str
    created_at: datetime
    decided_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AssistantSuggestionDecisionIn(BaseModel):
    """Web-Pendant zu /ok, /später, /nein im Telegram-Bot (siehe
    crud.decide_pending_suggestion) - dieselbe decision-Werte-Menge."""
    decision: str  # "accept" | "snooze" | "reject"


# ---------- Routinen (Spezifikation Abschnitt G) ----------
class RoutineBase(BaseModel):
    name: str
    weekdays: List[str]  # z.B. ["mon", "wed", "fri"]
    hour: int
    minute: int
    items: List[str]
    active: bool = True


class RoutineCreate(RoutineBase):
    pass


class RoutineUpdate(RoutineBase):
    pass


class RoutineOut(BaseModel):
    id: int
    name: str
    weekdays: List[str]
    hour: int
    minute: int
    items: List[str]
    active: bool
    checked_items: List[str] = []  # heutiger Abhak-Stand, siehe models.RoutineRun


class RoutineItemToggle(BaseModel):
    item: str
    checked: bool


# ---------- Enable Banking (Open-Banking-Aggregator für PSD2-Banken) ----------
class EnableBankingSettingsUpdate(BaseModel):
    app_id: str
    private_key: str
    redirect_base_url: Optional[str] = None


class EnableBankingSettingsOut(BaseModel):
    app_id: Optional[str] = None
    private_key_set: bool = False
    redirect_base_url: Optional[str] = None


class AspspOut(BaseModel):
    name: str
    country: str
    logo: Optional[str] = None


class EnableBankingConnectionCreate(BaseModel):
    aspsp_name: str
    aspsp_country: str
    account_id: int


class EnableBankingConnectionOut(BaseModel):
    id: int
    aspsp_name: str
    aspsp_country: str
    account_id: int
    status: str
    last_sync_at: Optional[datetime] = None
    last_sync_status: Optional[str] = None


class EnableBankingAuthStart(BaseModel):
    id: int
    url: str


class EbaySettingsUpdate(BaseModel):
    app_id: str
    cert_id: str
    ru_name: str


class EbaySettingsOut(BaseModel):
    app_id: Optional[str] = None
    cert_id_set: bool = False
    ru_name: Optional[str] = None


class EbayConnectionCreate(BaseModel):
    account_id: int


class EbayConnectionOut(BaseModel):
    id: int
    account_id: int
    ebay_username: Optional[str] = None
    status: str
    last_sync_at: Optional[datetime] = None
    last_sync_status: Optional[str] = None
    refresh_token_expires_at: Optional[datetime] = None


class EbayAuthStart(BaseModel):
    id: int
    url: str


# ---------- Dashboard ----------
class CategorySummary(BaseModel):
    category_id: Optional[int]
    category_name: str
    total: float


class TopExpenseRecipientOut(BaseModel):
    description: str
    total: float
    count: int


class DashboardSummary(BaseModel):
    year: int
    month: Optional[int]
    total_income: float
    total_expense: float
    balance: float
    by_category: List[CategorySummary]
    account_balances: List[AccountOut]


class DashboardTrendPoint(BaseModel):
    year: int
    month: int
    income: float
    expense: float


class DashboardTrendOut(BaseModel):
    points: List[DashboardTrendPoint]


class CategoryTrendSeries(BaseModel):
    category_id: int
    category_name: str
    points: List[float]


class CategoryTrendOut(BaseModel):
    months: List[str]
    series: List[CategoryTrendSeries]


# ---------- Jahresrückblick ----------
class YearReviewStat(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = None
    total: Optional[float] = None
    count: Optional[int] = None
    month: Optional[int] = None
    date: Optional[str] = None
    category_name: Optional[str] = None


class YearReviewOut(BaseModel):
    year: int
    total_income: float
    total_expense: float
    saved: float
    savings_rate: Optional[float] = None
    transaction_count: int
    biggest_expense: Optional[YearReviewStat] = None
    top_category: Optional[YearReviewStat] = None
    most_frequent_category: Optional[YearReviewStat] = None
    busiest_month: Optional[YearReviewStat] = None
    income_change_pct: Optional[float] = None
    expense_change_pct: Optional[float] = None
    investment_return_pct: Optional[float] = None
    net_worth_now: float
    monthly_points: List[DashboardTrendPoint]


# ---------- Wiederkehrende Zahlungen ----------
class RecurringPaymentOut(BaseModel):
    description: Optional[str] = None
    description_key: str
    account_id: int
    account_name: Optional[str] = None
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    frequency: str
    avg_amount: float
    occurrences: int
    last_date: date
    next_expected_date: date
    total_amount: float


class PriceIncreaseOut(BaseModel):
    description: Optional[str] = None
    description_key: str
    account_id: int
    account_name: Optional[str] = None
    frequency: str
    old_amount: float
    new_amount: float
    increase_pct: float
    changed_date: date


class SpendingAnomalyOut(BaseModel):
    category_id: int
    category_name: str
    current_spent: float
    projected_spent: float
    avg_prior_months: float
    deviation_pct: float


class CalendarConflictOut(BaseModel):
    event_a_id: int
    event_a_title: str
    event_a_start: datetime
    event_b_id: int
    event_b_title: str
    event_b_start: datetime


class OverlappingContractGroupOut(BaseModel):
    category_id: int
    category_name: str
    items: List[RecurringPaymentOut]
    monthly_total: float


# ---------- Kündigungsfrist-Erinnerungen ----------
class ContractReminderCreate(BaseModel):
    account_id: int
    description_key: str
    label: str
    notice_period_days: int
    renewal_date: date
    auto_advance_frequency: Optional[str] = None
    notes: Optional[str] = None
    should_cancel: bool = False


class ContractReminderUpdate(BaseModel):
    label: Optional[str] = None
    notice_period_days: Optional[int] = None
    renewal_date: Optional[date] = None
    auto_advance_frequency: Optional[str] = None
    notes: Optional[str] = None
    should_cancel: Optional[bool] = None


class ContractReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    account_id: int
    account_name: Optional[str] = None
    description_key: str
    label: str
    notice_period_days: int
    renewal_date: date
    auto_advance_frequency: Optional[str] = None
    reminder_date: date
    days_until_reminder: int
    due: bool
    notes: Optional[str] = None
    should_cancel: bool = False


# ---------- Ignorierte wiederkehrende Zahlungen (Fehlerkennungen) ----------
class IgnoredRecurringPaymentCreate(BaseModel):
    account_id: int
    description_key: str
    label: str


class IgnoredRecurringPaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    account_id: int
    account_name: Optional[str] = None
    description_key: str
    label: str


# ---------- Rückgabefristen ----------
class ReturnDeadlineCreate(BaseModel):
    transaction_id: int
    start_date: date
    deadline_days: int
    remind_days_before: int = 3


class ReturnDeadlineUpdate(BaseModel):
    start_date: Optional[date] = None
    deadline_days: Optional[int] = None
    remind_days_before: Optional[int] = None
    returned: Optional[bool] = None


class ReturnDeadlineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    transaction_id: int
    transaction_description: Optional[str] = None
    transaction_amount: Optional[float] = None
    start_date: date
    deadline_days: int
    remind_days_before: int
    returned: bool
    deadline_date: date
    days_left: int
    due: bool


# ---------- Cashflow-Prognose ----------
class CashflowPoint(BaseModel):
    date: str
    balance: float


class CashflowEvent(BaseModel):
    date: date
    amount: float
    description: Optional[str] = None


class CashflowForecastOut(BaseModel):
    start_balance: float
    horizon_days: int
    points: List[CashflowPoint]
    upcoming_events: List[CashflowEvent]
    lowest_balance: float
    lowest_date: Optional[str] = None
    goes_negative: bool
    first_negative_date: Optional[str] = None


class CashflowScenarioRequest(BaseModel):
    horizon_days: int = 90
    cancel_description_key: Optional[str] = None
    extra_monthly_saving: float = 0.0
    extra_monthly_expense: float = 0.0


class CashflowScenarioOut(BaseModel):
    baseline: CashflowForecastOut
    scenario: CashflowForecastOut


# ---------- Automatische Backups ----------
class BackupSettingsOut(BaseModel):
    enabled: bool
    hour: int
    retention: int


class BackupSettingsUpdate(BaseModel):
    enabled: bool
    hour: int
    retention: int


class BackupFileOut(BaseModel):
    filename: str
    size_bytes: int
    created_at: datetime


# ---------- Steuer (Vorabpauschale / realisierte Gewinne) ----------
class VorabpauschaleOut(BaseModel):
    holding_id: int
    name: str
    symbol: str
    year: int
    basiszins_percent: float
    basisertrag: float
    wertsteigerung: float
    ausschuettung: float
    vorabpauschale: float
    teilfreistellung_percent: float
    steuerpflichtiger_betrag: float
    is_estimate: bool


class PortfolioVorabpauschaleOut(BaseModel):
    year: int
    rows: List[VorabpauschaleOut]
    total_steuerpflichtig: float
    missing_basiszins: bool = False


class RealizedGainRow(BaseModel):
    holding_id: int
    name: str
    symbol: str
    date: date
    quantity: float
    proceeds: float
    cost_basis: float
    gain: float


class RealizedGainsOut(BaseModel):
    year: int
    rows: List[RealizedGainRow]
    total_gain: float


class TaxSummaryOut(BaseModel):
    year: int
    vorabpauschale_total: float
    realized_gain_total: float
    sparerpauschbetrag: float
    taxable_after_allowance: float


class BasiszinsRateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    year: int
    rate_percent: float


class BasiszinsRateUpdate(BaseModel):
    year: int
    rate_percent: float


# ---------- Beleg-Chat (KI liest Belege/Abrechnungen aus Bild/PDF/Text) ----------
class BelegChatResult(BaseModel):
    reply: str
    proposals: List[Dict[str, Any]] = []
    attachment_filename: Optional[str] = None
    attachment_base64: Optional[str] = None
    error: Optional[str] = None


class BelegChatApply(BaseModel):
    type: str
    data: Dict[str, Any]
    account_id: Optional[int] = None
    attachment_filename: Optional[str] = None
    attachment_base64: Optional[str] = None


class BelegChatApplyResult(BaseModel):
    ok: bool
    transaction_id: Optional[int] = None
    holding_id: Optional[int] = None
    debt_id: Optional[int] = None
    message: str


class SparerpauschbetragUpdate(BaseModel):
    amount: float
    budgets: List[BudgetProgress] = []


# ---------- Schulden ----------
class DebtBase(BaseModel):
    name: str
    kind: DebtKind = DebtKind.annuitaeten
    lender: Optional[str] = None
    original_amount: float
    interest_rate_percent: float = 0.0
    monthly_payment: Optional[float] = None
    start_date: Optional[date] = None
    planned_end_date: Optional[date] = None
    account_id: Optional[int] = None
    notes: Optional[str] = None
    # Zinsbindung
    interest_fixed_until: Optional[date] = None
    follow_up_interest_rate_percent: Optional[float] = None
    # Bereitstellungszinsen
    commitment_rate_percent: Optional[float] = None
    commitment_free_months: Optional[int] = None
    undisbursed_amount: Optional[float] = None
    # Nebenkosten
    upfront_fees: Optional[float] = None
    monthly_fee: Optional[float] = None
    monthly_insurance: Optional[float] = None


class DebtCreate(DebtBase):
    pass


class DebtUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[DebtKind] = None
    lender: Optional[str] = None
    original_amount: Optional[float] = None
    interest_rate_percent: Optional[float] = None
    monthly_payment: Optional[float] = None
    start_date: Optional[date] = None
    planned_end_date: Optional[date] = None
    account_id: Optional[int] = None
    notes: Optional[str] = None
    status: Optional[DebtStatus] = None
    interest_fixed_until: Optional[date] = None
    follow_up_interest_rate_percent: Optional[float] = None
    commitment_rate_percent: Optional[float] = None
    commitment_free_months: Optional[int] = None
    undisbursed_amount: Optional[float] = None
    upfront_fees: Optional[float] = None
    monthly_fee: Optional[float] = None
    monthly_insurance: Optional[float] = None


class DebtOut(DebtBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    current_balance: float
    status: DebtStatus
    created_at: Optional[datetime] = None
    # Abgeleitete Kennzahlen
    paid_off_amount: float = 0.0
    paid_off_percent: float = 0.0
    total_interest_paid: float = 0.0
    total_fees_paid: float = 0.0
    payment_count: int = 0
    account_name: Optional[str] = None
    # Tatsächliche Monatsbelastung inkl. Gebühren und Versicherung
    monthly_total_burden: float = 0.0
    monthly_commitment_interest: float = 0.0
    # Prognose (nur in der Detailansicht gefüllt)
    projected_end_date: Optional[date] = None
    projected_remaining_interest: Optional[float] = None
    projected_remaining_fees: Optional[float] = None
    projection_note: Optional[str] = None
    # Zinsbindung
    balance_at_fixed_interest_end: Optional[float] = None


class DebtPaymentCreate(BaseModel):
    date: date
    total_amount: float
    # None = Zinsanteil automatisch aus Restschuld und Zinssatz rechnen
    interest_amount: Optional[float] = None
    # None = laufende Nebenkosten des Kredits ansetzen
    fee_amount: Optional[float] = None
    is_extra_repayment: bool = False
    transaction_id: Optional[int] = None
    notes: Optional[str] = None


class DebtPaymentUpdate(BaseModel):
    date: Optional[date] = None
    total_amount: Optional[float] = None
    interest_amount: Optional[float] = None
    fee_amount: Optional[float] = None
    is_extra_repayment: Optional[bool] = None
    transaction_id: Optional[int] = None
    notes: Optional[str] = None


class DebtPaymentOut(BaseModel):
    id: int
    date: date
    total_amount: float
    interest_amount: float
    fee_amount: float
    principal_amount: float
    balance_after: float
    is_extra_repayment: bool
    interest_is_manual: bool
    transaction_id: Optional[int] = None
    notes: Optional[str] = None


class DebtScheduleRow(BaseModel):
    month_index: int
    date: date
    payment: float
    interest: float
    fee: float
    principal: float
    balance_after: float
    after_fixed_interest: bool = False


class DebtScheduleOut(BaseModel):
    rows: List[DebtScheduleRow] = []
    note: Optional[str] = None
    total_interest: float = 0.0
    total_fees: float = 0.0
    end_date: Optional[date] = None


class DebtSummaryOut(BaseModel):
    total_balance: float
    total_original: float
    total_interest_paid: float
    total_fees_paid: float = 0.0
    monthly_burden: float
    active_count: int
    paid_off_count: int


# ---------- Automatisierung (Umbuchungen + Auto-Kategorisierung) ----------
class AutoCategorizeSettingsOut(BaseModel):
    enabled: bool


class AutoCategorizeSettingsUpdate(BaseModel):
    enabled: bool


class AutoCategorizeRunResult(BaseModel):
    transfers_marked: int
    categorized: int
    skipped: int
    queued: int = 0
    error: Optional[str] = None


# ---------- Assistant-Chat (schwebender KI-Button, allgemeine Anweisungen) ----------
class AssistantChatResult(BaseModel):
    reply: str
    proposals: List[Dict[str, Any]] = []
    # Für die Anzeige "🌐 hat im Internet gesucht: ..." im Chat.
    web_searches: List[str] = []
    error: Optional[str] = None


class WebSearchSettingsOut(BaseModel):
    provider: str = "brave"
    api_key_set: bool = False
    searxng_url: Optional[str] = None


class WebSearchSettingsUpdate(BaseModel):
    api_key: Optional[str] = None


class WebSearchProviderUpdate(BaseModel):
    provider: str
    searxng_url: Optional[str] = None


# ---------- Anzeige-Währung ----------
class CurrencySettingsOut(BaseModel):
    currency: str = "EUR"


class CurrencySettingsUpdate(BaseModel):
    currency: str


class CountrySettingsOut(BaseModel):
    country: str = "DE"


class CountrySettingsUpdate(BaseModel):
    country: str


class FxRateOut(BaseModel):
    from_currency: str
    to_currency: str
    rate: float


# ---------- Einrichtungsstatus der Anbindungen ----------
class IntegrationStatusItem(BaseModel):
    key: str
    name: str
    # Wozu die Anbindung gebraucht wird - ohne das ist die Liste nur eine
    # Ansammlung von Produktnamen und hilft beim Einrichten nicht weiter.
    purpose: str
    # "ok" = einsatzbereit, "partial" = teilweise, "missing" = nicht eingerichtet,
    # "off" = eingerichtet, aber bewusst abgeschaltet.
    status: str
    detail: str
    # Was fehlt noch - leer, wenn nichts fehlt.
    missing: List[str] = []
    optional: bool


class IntegrationStatusOut(BaseModel):
    items: List[IntegrationStatusItem]
    ready: int
    incomplete: int


class VersionOut(BaseModel):
    git_sha: str
    git_sha_short: str
    build_date: Optional[str] = None


class LatestVersionOut(BaseModel):
    # False, solange sich der neueste Stand nicht ermitteln laesst (z.B. weil
    # das GHCR-Paket noch nicht wirklich oeffentlich abrufbar ist) - dann zeigt
    # das Frontend bewusst gar nichts an, statt etwas zu behaupten.
    available: bool
    git_sha: Optional[str] = None
    git_sha_short: Optional[str] = None
    error: Optional[str] = None


# ---------- Immich (Fotobibliothek) ----------
class ImmichSettingsOut(BaseModel):
    url: Optional[str] = None
    # Der Schlüssel selbst wird nie zurückgegeben, nur ob einer hinterlegt ist.
    api_key_set: bool
    skip_confirm: bool = False


class ImmichSettingsUpdate(BaseModel):
    url: str
    # Leer lassen heisst "bestehenden Schlüssel behalten" - sonst müsste man ihn
    # bei jeder URL-Änderung neu eintippen.
    api_key: Optional[str] = None
    skip_confirm: bool = False


class ImmichTestResult(BaseModel):
    ok: bool
    version: Optional[str] = None
    duplicate_groups: Optional[int] = None
    error: Optional[str] = None


class ImmichStatsOut(BaseModel):
    photos: int = 0
    videos: int = 0
    usage_bytes: int = 0
    usage_photos_bytes: int = 0
    usage_videos_bytes: int = 0
    available: bool = True


class ImmichPersonOut(BaseModel):
    id: str
    name: str
    asset_count: int = 0


class ImmichPeopleOut(BaseModel):
    people: List[ImmichPersonOut]


class ImmichPersonAssetsOut(BaseModel):
    assets: List["ImmichAssetOut"]
    page: int
    has_more: bool
    trash_enabled: bool = True
    trash_days: Optional[int] = None


class ImmichAssetOut(BaseModel):
    id: str
    file_name: Optional[str] = None
    type: Optional[str] = None
    created_at: Optional[str] = None
    size_bytes: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    camera: Optional[str] = None


class ImmichDuplicateGroupOut(BaseModel):
    duplicate_id: str
    assets: List[ImmichAssetOut]
    # Immichs eigener Vorschlag, was behalten werden sollte.
    suggested_keep_ids: List[str]
    # Gesamtzahl in der Gruppe. Kann groesser sein als len(assets), wenn die
    # Gruppe fuer die Anzeige gekuerzt wurde (siehe MAX_ASSETS_PER_GROUP).
    asset_count: int = 0
    # Byte-identisch (checksum-Duplikat) = 100%, sonst der beste paarweise
    # Perceptual-Hash-Vergleich innerhalb der Gruppe. Bestimmt die
    # Sortierung der Seite (siehe main.immich_duplicates) und lässt sich
    # direkt anzeigen, ohne dafür extra die Similarity-Route aufzurufen.
    best_similarity_percent: Optional[float] = None


class ImmichDuplicatesOut(BaseModel):
    groups: List[ImmichDuplicateGroupOut]
    total_groups: int
    total_assets: int
    # Seitenweises Laden - bei mehreren tausend Gruppen kann nicht alles auf
    # einmal geliefert werden.
    offset: int = 0
    limit: int = 0
    has_more: bool = False
    # Zustand von Immichs Papierkorb - entscheidet darüber, ob aussortierte
    # Bilder wiederherstellbar sind. Wird in der Oberfläche angezeigt.
    trash_enabled: bool = True
    trash_days: Optional[int] = None


class ImmichResolveGroup(BaseModel):
    duplicate_id: str
    keep_ids: List[str]
    trash_ids: List[str]


class ImmichResolveRequest(BaseModel):
    groups: List[ImmichResolveGroup]


class ImmichResolveResult(BaseModel):
    resolved_groups: int
    trashed_assets: int


class ImmichScreenshotsOut(BaseModel):
    assets: List[ImmichAssetOut]
    # Gesamtzahl nach Altersfilter (nicht nur die angezeigte Seite).
    total: int
    total_size_bytes: int
    # Verteilung ueber alle Bildschirmfotos, unabhaengig vom Filter - macht
    # sichtbar, wie viel jeweils dahintersteckt.
    by_age: Dict[str, int]
    offset: int
    limit: int
    has_more: bool
    trash_enabled: bool = True
    trash_days: Optional[int] = None


class ImmichSimilarityOut(BaseModel):
    duplicate_id: str
    # Je Bild-ID die Übereinstimmung in Prozent zu jedem anderen Bild der
    # Gruppe. Vollständig, damit die Anzeige beim Umwählen des zu behaltenden
    # Bildes nicht neu rechnen muss.
    pairs: Dict[str, Dict[str, float]]
    error: Optional[str] = None


class ImmichPhotosOut(BaseModel):
    assets: List[ImmichAssetOut]
    offset: int
    limit: int
    has_more: bool
    trash_enabled: bool = True
    trash_days: Optional[int] = None


class ImmichTrashRequest(BaseModel):
    asset_ids: List[str]


class ImmichTrashResult(BaseModel):
    trashed: int
    freed_bytes: int


class ImmichAiSuggestionRequest(BaseModel):
    asset_ids: List[str]


class ImmichAiSuggestionResult(BaseModel):
    reason: Optional[str] = None
    error: Optional[str] = None


class ImmichQualityAssetOut(ImmichAssetOut):
    reason: str  # "blur" oder "blank"
    score: Optional[float] = None


class ImmichQualityOut(BaseModel):
    assets: List[ImmichQualityAssetOut]
    total: int
    total_size_bytes: int
    by_reason: Dict[str, int]
    offset: int
    limit: int
    has_more: bool
    trash_enabled: bool = True
    trash_days: Optional[int] = None
    # Fortschritt des Hintergrund-Scans (welche Seite der Bibliothek zuletzt
    # geprüft wurde) - macht sichtbar, dass hier laufend nachgetragen wird.
    scan_page: int = 1


# ---------- Vermögensvergleich mit der Altersgruppe ----------
class BenchmarkBracket(BaseModel):
    key: str
    label: str
    p10: float
    p50: float
    p90: float
    is_own: bool


class BenchmarkOut(BaseModel):
    # Ohne Geburtsjahr kann nicht verglichen werden - dann liefert der Endpunkt
    # nur die Tabelle, damit die Oberfläche trotzdem etwas zeigen kann.
    configured: bool
    birth_year: Optional[int] = None
    age: Optional[int] = None
    own_bracket: Optional[str] = None
    net_worth: float
    percentile: Optional[float] = None
    # False, wenn der Wert ausserhalb der belegten Marken liegt und die
    # Prozentangabe deshalb nur eine Ober-/Untergrenze ist.
    percentile_exact: Optional[bool] = None
    verdict: Optional[str] = None
    brackets: List[BenchmarkBracket]
    overall: BenchmarkBracket
    source: str
    source_url: str
    data_year: int


class BirthYearUpdate(BaseModel):
    birth_year: Optional[int] = None


# ---------- Benachrichtigungen (Telegram) ----------
class NotificationSettingsOut(BaseModel):
    enabled: bool
    telegram_configured: bool
    proactive_assistant_enabled: bool = False
    proactive_assistant_snoozed_until: Optional[datetime] = None
    proactive_assistant_last_text: Optional[str] = None
    ntfy_enabled: bool = False
    ntfy_url: str = "https://ntfy.sh"
    ntfy_topic: Optional[str] = None
    telegram_voice_replies: bool = False
    ha_announce_enabled: bool = False
    ha_announce_service: Optional[str] = None
    ha_announce_target: Optional[str] = None


class NotificationSettingsUpdate(BaseModel):
    enabled: bool
    # None = jeweils unverändert lassen (Feld nicht neu gesendet)
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    proactive_assistant_enabled: Optional[bool] = None
    ntfy_enabled: Optional[bool] = None
    ntfy_url: Optional[str] = None
    ntfy_topic: Optional[str] = None
    telegram_voice_replies: Optional[bool] = None
    ha_announce_enabled: Optional[bool] = None
    ha_announce_service: Optional[str] = None
    ha_announce_target: Optional[str] = None


class NotificationTestResult(BaseModel):
    ok: bool
    message: str


class NotificationLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    text: str
    urgent: bool
    sent: bool


class ProactiveFeedbackIn(BaseModel):
    text: str
    useful: bool


# ---------- Echte Anrufe (Twilio) ----------
class CallSettingsOut(BaseModel):
    enabled: bool
    twilio_configured: bool


class CallSettingsUpdate(BaseModel):
    enabled: bool
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_from_number: Optional[str] = None
    twilio_to_number: Optional[str] = None


# ---------- Ziele ----------
class GoalTriggerIn(BaseModel):
    metric_type: GoalMetricType
    comparison: GoalComparison = GoalComparison.gte
    threshold_value: float
    scope_account_id: Optional[int] = None
    scope_asset_type: Optional[AssetType] = None
    scope_category_id: Optional[int] = None
    scope_debt_id: Optional[int] = None
    evaluation_window_months: Optional[int] = None


class GoalTriggerOut(GoalTriggerIn):
    model_config = ConfigDict(from_attributes=True)
    currency: str = "EUR"


class GoalCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    goal_type: GoalType = GoalType.manual
    target_date: Optional[date] = None
    predecessor_goal_id: Optional[int] = None
    # True = bereichsübergreifend (space_id bleibt NULL)
    all_spaces: bool = False
    trigger: Optional[GoalTriggerIn] = None


class GoalUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    goal_type: Optional[GoalType] = None
    target_date: Optional[date] = None
    predecessor_goal_id: Optional[int] = None
    status: Optional[GoalStatus] = None
    all_spaces: Optional[bool] = None
    trigger: Optional[GoalTriggerIn] = None


class GoalProgressPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    timestamp: datetime
    current_value: float




class GoalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    space_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    goal_type: GoalType
    target_date: Optional[date] = None
    status: GoalStatus
    predecessor_goal_id: Optional[int] = None
    predecessor_title: Optional[str] = None
    completion_seen: bool = True
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    trigger: Optional[GoalTriggerOut] = None
    # Nur bei auto_financial gefüllt: live berechneter Stand.
    current_value: Optional[float] = None
    target_value: Optional[float] = None
    progress_percent: Optional[float] = None
    # "eur" oder "months" - steuert die Formatierung im Frontend
    value_unit: str = "eur"
    # Erklärender Text zur Metrik, z.B. "Kontostand: Girokonto"
    metric_label: Optional[str] = None
    # Meldung, falls die Metrik gerade nicht berechenbar ist (z.B. Konto gelöscht)
    evaluation_error: Optional[str] = None


class GoalCompleteResult(BaseModel):
    ok: bool
    goal: GoalOut
    message: str


# ---------- To-Dos (Radicale/CalDAV) ----------
class RadicaleSettingsUpdate(BaseModel):
    url: str
    username: str
    password: str
    calendar_url: Optional[str] = None


class RadicaleSettingsOut(BaseModel):
    url: Optional[str] = None
    username: Optional[str] = None
    password_set: bool = False
    calendar_url: Optional[str] = None


class CalendarEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    start: datetime
    end: Optional[datetime] = None
    location: Optional[str] = None
    all_day: bool = False
    calendar_url: Optional[str] = None
    travel_minutes: Optional[int] = None
    is_recurring: bool = False
    recurring_master_id: Optional[int] = None


class CalendarEventCreate(BaseModel):
    title: str
    start: datetime
    end: Optional[datetime] = None
    location: Optional[str] = None
    all_day: bool = False
    calendar_url: Optional[str] = None


class CalendarEventUpdate(BaseModel):
    title: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    location: Optional[str] = None
    all_day: Optional[bool] = None


class CalendarSyncResult(BaseModel):
    pushed: int
    pulled: int
    errors: List[str] = []


class CalendarCollectionOut(BaseModel):
    url: str
    name: str


class TravelSettingsOut(BaseModel):
    home_address: Optional[str] = None
    home_geocoded: bool = False
    api_key_set: bool = False


class TravelSettingsUpdate(BaseModel):
    home_address: Optional[str] = None
    api_key: Optional[str] = None


class TodoCreate(BaseModel):
    title: str
    due_date: Optional[date] = None


class TodoUpdate(BaseModel):
    title: Optional[str] = None
    done: Optional[bool] = None
    due_date: Optional[date] = None


class TodoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    done: bool
    due_date: Optional[date] = None
    created_at: datetime


class TodoSyncResult(BaseModel):
    pushed: int
    pulled: int
    errors: List[str] = []




# ---------- E-Mail-Belege ----------
class MailSettingsOut(BaseModel):
    enabled: bool
    host: Optional[str] = None
    port: int = 993
    user: Optional[str] = None
    folder: str = "INBOX"
    # Das Passwort wird nie zurueckgegeben, nur ob eines hinterlegt ist.
    password_set: bool = False
    last_sync_at: Optional[str] = None


class MailSettingsUpdate(BaseModel):
    enabled: bool = False
    host: Optional[str] = None
    port: int = 993
    user: Optional[str] = None
    folder: str = "INBOX"
    # Leer lassen behaelt das bisherige Passwort.
    password: Optional[str] = None


class MailTestResult(BaseModel):
    ok: bool
    folder: Optional[str] = None
    message_count: Optional[int] = None
    error: Optional[str] = None


class MailSyncResult(BaseModel):
    new_attachments: int
    skipped: int
    auto_attached: int


class CreditCardSettingsOut(BaseModel):
    mail_sender: Optional[str] = None
    account_id: Optional[int] = None
    debt_id: Optional[int] = None


class CreditCardSettingsUpdate(BaseModel):
    mail_sender: Optional[str] = None
    account_id: Optional[int] = None
    debt_id: Optional[int] = None


class CreditCardBillOut(BaseModel):
    account_name: str
    due_date: Optional[date] = None
    amount: Optional[float] = None


class MailAttachmentOut(BaseModel):
    id: int
    filename: str
    stored_filename: str
    sender: Optional[str] = None
    subject: Optional[str] = None
    mail_date: Optional[str] = None
    size_bytes: Optional[int] = None
    status: str
    parsed_amount: Optional[float] = None
    parsed_date: Optional[str] = None
    parse_error: Optional[str] = None
    transaction_id: Optional[int] = None
    # Passende Buchungen ohne Beleg, live ermittelt.
    suggestions: List[Dict[str, Any]] = []


class MailAttachRequest(BaseModel):
    transaction_id: int


class MailCreateTransactionRequest(BaseModel):
    account_id: int
    category_id: Optional[int] = None
    # Vorbelegt mit dem ausgelesenen Datum/Betrag, aber überschreibbar - die
    # KI-Erkennung ist eine Vorlage, keine Zwangsvorgabe.
    date: date
    amount: float
    description: Optional[str] = None


# ---------- Business-Projekte (Nebenprojekte, außerhalb der Finanzverwaltung) ----------
class BusinessProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    check_interval_days: Optional[int] = None
    account_id: Optional[int] = None


class BusinessProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    check_interval_days: Optional[int] = None
    account_id: Optional[int] = None
    active: Optional[bool] = None


class BusinessProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str] = None
    check_interval_days: Optional[int] = None
    last_checked_at: Optional[datetime] = None
    created_at: datetime
    active: bool
    open_issue_count: int = 0
    account_id: Optional[int] = None
    account_name: Optional[str] = None
    income_this_month: float = 0.0
    income_total: float = 0.0


class BusinessIssueCreate(BaseModel):
    project_id: int
    title: str
    notes: Optional[str] = None


class BusinessIssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    project_name: Optional[str] = None
    title: str
    notes: Optional[str] = None
    resolved: bool
    created_at: datetime
    resolved_at: Optional[datetime] = None


# ---------- Eingehender Webhook (n8n) ----------
class WebhookSettingsOut(BaseModel):
    secret: Optional[str] = None
    configured: bool = False


class ScalableSettingsOut(BaseModel):
    enabled: bool = False
    last_sync_at: Optional[datetime] = None
    last_sync_status: Optional[str] = None


class ScalableSettingsUpdate(BaseModel):
    enabled: bool


class ScalableSyncResult(BaseModel):
    created: int
    updated: int
    lots_added: int
    error: Optional[str] = None


class WebhookIssueCreate(BaseModel):
    project: str
    title: str
    notes: Optional[str] = None


# ---------- Leben (persönliche Lebensbereiche, außerhalb der Finanzen) ----------
class LifeAreaCreate(BaseModel):
    name: str
    description: Optional[str] = None
    target_date: Optional[date] = None
    progress_percent: Optional[int] = None
    check_interval_days: Optional[int] = None
    target_days_per_week: Optional[int] = None


class LifeAreaUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    target_date: Optional[date] = None
    progress_percent: Optional[int] = None
    check_interval_days: Optional[int] = None
    target_days_per_week: Optional[int] = None
    active: Optional[bool] = None


class LifeAreaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str] = None
    target_date: Optional[date] = None
    progress_percent: Optional[int] = None
    check_interval_days: Optional[int] = None
    target_days_per_week: Optional[int] = None
    last_checked_at: Optional[datetime] = None
    created_at: datetime
    active: bool
    streak_days: int = 0
    checkin_days_30: List[str] = []
    # Mo-So der laufenden Woche, True = an dem Tag mind. ein Check-in - nur
    # gefuellt/relevant, wenn target_days_per_week gesetzt ist (festes
    # Wochenraster statt des freien 30-Tage-Streifens oben).
    week_days: List[bool] = []


class LifeCheckInCreate(BaseModel):
    area_id: int
    note: str
    progress_percent: Optional[int] = None


class LifeCheckInOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    area_id: int
    area_name: Optional[str] = None
    note: str
    created_at: datetime


# ---------- Wunschliste (Deal-Wecker) ----------
class WishlistItemCreate(BaseModel):
    name: str
    category: Optional[str] = None
    target_price: Optional[float] = None
    url: Optional[str] = None
    notes: Optional[str] = None
    check_interval_days: Optional[int] = None
    auto_check_enabled: bool = False


class WishlistItemUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    target_price: Optional[float] = None
    url: Optional[str] = None
    notes: Optional[str] = None
    check_interval_days: Optional[int] = None
    auto_check_enabled: Optional[bool] = None
    purchased: Optional[bool] = None
    active: Optional[bool] = None


class WishlistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    category: Optional[str] = None
    target_price: Optional[float] = None
    url: Optional[str] = None
    notes: Optional[str] = None
    check_interval_days: Optional[int] = None
    last_checked_at: Optional[datetime] = None
    created_at: datetime
    auto_check_enabled: bool = False
    purchased: bool = False
    active: bool


# ---------- Heute-Übersicht (Fokus-Ansicht im Hub) ----------
class TodayEvent(BaseModel):
    """Ein Termin des heutigen Tages. `travel_minutes` nur gefüllt, wenn
    Startadresse + OpenRouteService-Schlüssel hinterlegt sind und der Termin
    einen geokodierten Ort hat (siehe main.list_calendar_events)."""
    id: int
    title: str
    start: datetime
    end: Optional[datetime] = None
    location: Optional[str] = None
    all_day: bool = False
    travel_minutes: Optional[int] = None
    leave_at: Optional[datetime] = None


class TodayTodo(BaseModel):
    id: int
    title: str
    due_date: Optional[date] = None
    overdue: bool = False


class TodayDeadline(BaseModel):
    """Vereinheitlichte Frist-Zeile - Kündigungsfrist (ContractReminder),
    Rückgabefrist (ReturnDeadline) oder fällige Abbuchung. Bewusst ein
    gemeinsamer Typ statt drei getrennter Listen: im Fokus-View interessiert
    „was läuft mir heute weg", nicht die technische Herkunft."""
    kind: str  # "kuendigung" | "ruecksendung" | "zahlung"
    label: str
    date: date
    days_left: int
    amount: Optional[float] = None
    detail: Optional[str] = None


class TodayGoal(BaseModel):
    id: int
    title: str
    target_date: Optional[date] = None
    progress_percent: Optional[float] = None
    days_left: Optional[int] = None


class TodayBalance(BaseModel):
    income: float
    expense: float
    balance: float
    transaction_count: int


class TodayOut(BaseModel):
    date: date
    events: List[TodayEvent]
    todos: List[TodayTodo]
    deadlines: List[TodayDeadline]
    goals: List[TodayGoal]
    balance: TodayBalance
    # Reise-Modus (siehe ROADMAP.md): läuft heute ein Trip (start_date <=
    # heute <= end_date), wird er hier mitgeschickt - None, wenn keiner
    # aktiv ist. Wiederverwendet TripOut (dieselbe Zusammenfassung wie im
    # Reisen-Tab), keine eigene Teilmenge nötig.
    active_trip: Optional[TripOut] = None


# ---------- Kontextbezogene Notizen ----------
NOTE_ENTITY_TYPES = ("goal", "todo", "business_project", "life_area", "schweiz")


class NoteCreate(BaseModel):
    entity_type: str
    entity_id: int
    text: str


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    entity_type: str
    entity_id: int
    text: str
    created_at: datetime
    updated_at: datetime


class NoteSearchResult(NoteOut):
    entity_label: Optional[str] = None


# ---------- Zeiterfassung ----------
class TimeEntryCreate(BaseModel):
    project_id: int
    note: Optional[str] = None
    started_at: Optional[datetime] = None  # None = jetzt (Start-Button)
    stopped_at: Optional[datetime] = None  # gesetzt = manueller, bereits abgeschlossener Eintrag


class TimeEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    note: Optional[str] = None
    started_at: datetime
    stopped_at: Optional[datetime] = None
    minutes: Optional[float] = None


class ProjectTimeSummary(BaseModel):
    project_id: int
    project_name: str
    total_minutes: float
    running_entry_id: Optional[int] = None


# ---------- People / CRM-Light ----------
class ContactCreate(BaseModel):
    name: str
    notes: Optional[str] = None
    last_interaction_at: Optional[date] = None


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    notes: Optional[str] = None
    last_interaction_at: Optional[date] = None


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    notes: Optional[str] = None
    last_interaction_at: Optional[date] = None
    created_at: datetime
    updated_at: datetime


# ---------- Leseliste / Medien-Tracking ----------
class MediaItemCreate(BaseModel):
    title: str
    media_type: str = "buch"
    status: MediaStatus = MediaStatus.offen
    url: Optional[str] = None
    notes: Optional[str] = None
    linked_goal_id: Optional[int] = None
    linked_project_id: Optional[int] = None


class MediaItemUpdate(BaseModel):
    title: Optional[str] = None
    media_type: Optional[str] = None
    status: Optional[MediaStatus] = None
    url: Optional[str] = None
    notes: Optional[str] = None
    linked_goal_id: Optional[int] = None
    linked_project_id: Optional[int] = None


class MediaItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    media_type: str
    status: MediaStatus
    url: Optional[str] = None
    notes: Optional[str] = None
    linked_goal_id: Optional[int] = None
    linked_goal_title: Optional[str] = None
    linked_project_id: Optional[int] = None
    linked_project_name: Optional[str] = None
    finished_at: Optional[date] = None
    created_at: datetime


# ---------- Gesundheits-Grunddaten ----------
class HealthMetricCreate(BaseModel):
    metric_type: HealthMetricType
    date: date
    value: float


class HealthMetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    metric_type: HealthMetricType
    date: date
    value: float


# ---------- KI-Review-Queue (Kategorisierungsvorschläge) ----------
class CategorySuggestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    transaction_id: int
    transaction_description: Optional[str] = None
    transaction_amount: float
    transaction_date: date
    suggested_category_id: int
    suggested_category_name: str
    confidence: float
    created_at: datetime


# ---------- Web-Login (siehe routers/auth_login.py) ----------
class AuthStatusOut(BaseModel):
    setup_required: bool
    authenticated: bool
    totp_required: bool  # True = Passwort war richtig, TOTP-Code fehlt noch
    totp_enabled: bool
    passkeys_enabled: bool  # mind. ein Passkey registriert
    session_idle_timeout_minutes: int
    users_count: int = 1
    display_name: Optional[str] = None  # Name des angemeldeten Nutzers


class SetupIn(BaseModel):
    password: str
    display_name: Optional[str] = None


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


class LoginIn(BaseModel):
    password: str
    name: Optional[str] = None  # noetig, sobald es mehr als ein Konto gibt


class UserCreateIn(BaseModel):
    name: str
    password: str


class UserRenameIn(BaseModel):
    name: str


class LoginOut(BaseModel):
    authenticated: bool
    totp_required: bool


class TotpVerifyIn(BaseModel):
    code: str


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_uri: str
    qr_code_data_uri: str  # data:image/png;base64,... - fertiges <img src>


class TotpConfirmIn(BaseModel):
    code: str


class TotpConfirmOut(BaseModel):
    recovery_code: str  # nur EINMAL im Klartext - danach nur noch der Hash gespeichert


class TotpDisableIn(BaseModel):
    # Verlangt eine erneute Bestätigung (Passwort ODER aktueller TOTP-Code),
    # damit nicht ein gekapertes offenes Browser-Fenster allein reicht, um
    # den zweiten Faktor abzuschalten.
    password: Optional[str] = None
    code: Optional[str] = None


class RecoveryLoginIn(BaseModel):
    recovery_code: str


class SessionTimeoutOut(BaseModel):
    session_idle_timeout_minutes: int


class SessionTimeoutUpdate(BaseModel):
    session_idle_timeout_minutes: int


class PasskeyCredentialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: Optional[str] = None
    transports: Optional[str] = None
    created_at: datetime
    last_used_at: Optional[datetime] = None


class PasskeyRegisterOptionsIn(BaseModel):
    name: Optional[str] = None  # Geräte-Label, z.B. "iPhone" - vom Nutzer vergeben


class WebAuthnOptionsOut(BaseModel):
    # Rohe WebAuthn-Optionen als JSON-Objekt (siehe py_webauthn:
    # options_to_json) - das Frontend reicht es unveraendert an
    # navigator.credentials.create()/.get() durch, kein eigenes Schema fuer
    # jedes Detail der WebAuthn-Spec noetig.
    publicKey: Dict[str, Any]


class WebAuthnCredentialIn(BaseModel):
    # Rohe Antwort von navigator.credentials.create()/.get() (bereits vom
    # Frontend in JSON umgewandelt) - py_webauthn parst/verifiziert sie direkt.
    credential: Dict[str, Any]
    name: Optional[str] = None  # nur bei der Registrierung genutzt


# ---------- Globale Suche ----------
class GlobalSearchResult(BaseModel):
    entity_type: str
    id: int
    label: str
    sublabel: Optional[str] = None
    tab: str


# ---------- Auto-Tab (2026-08-28) ----------
class VehicleOut(BaseModel):
    id: int
    name: str
    model_3d_url: Optional[str] = None

    model_config = ConfigDict(protected_namespaces=())


class VehicleUpdate(BaseModel):
    name: str


class VehicleFuelEntryBase(BaseModel):
    date: date
    odometer_km: float
    liters: Optional[float] = None
    total_cost: float
    full_tank: bool = True
    notes: Optional[str] = None


class VehicleFuelEntryCreate(VehicleFuelEntryBase):
    pass


class VehicleFuelEntryUpdate(BaseModel):
    date: Optional[date] = None
    odometer_km: Optional[float] = None
    liters: Optional[float] = None
    total_cost: Optional[float] = None
    full_tank: Optional[bool] = None
    notes: Optional[str] = None


class VehicleFuelEntryOut(VehicleFuelEntryBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    # Verbrauch seit dem vorherigen VOLLEN Tankvorgang - None, wenn kein
    # vorheriger voller Tankvorgang existiert oder dieser Eintrag selbst
    # kein voller Tankvorgang ist (siehe crud_vehicle._enrich_fuel_entries).
    consumption_l_per_100km: Optional[float] = None
    cost_per_km: Optional[float] = None


class VehicleGoalBase(BaseModel):
    title: str
    notes: Optional[str] = None
    target_date: Optional[date] = None


class VehicleGoalCreate(VehicleGoalBase):
    pass


class VehicleGoalUpdate(BaseModel):
    title: Optional[str] = None
    notes: Optional[str] = None
    target_date: Optional[date] = None
    done: Optional[bool] = None


class VehicleGoalOut(VehicleGoalBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    done: bool


# ---------- Smart Home (Home Assistant + Ollama, siehe smarthome.py) ----------
class SmartHomeSettingsOut(BaseModel):
    url: Optional[str] = None
    token_set: bool = False
    allowed_domains: Optional[str] = None
    allowed_areas: Optional[str] = None
    extra_services: Optional[str] = None
    require_confirmation: bool = True
    dry_run: bool = False
    wake_word: Optional[str] = None
    electricity_price: float = 0.35
    history_entities: Optional[str] = None


class SmartHomeSettingsUpdate(BaseModel):
    url: Optional[str] = None
    # Leer / weggelassen = Token unveraendert lassen. Der String "" loescht ihn.
    token: Optional[str] = None
    allowed_domains: Optional[str] = None
    allowed_areas: Optional[str] = None
    extra_services: Optional[str] = None
    require_confirmation: Optional[bool] = None
    dry_run: Optional[bool] = None
    wake_word: Optional[str] = None
    electricity_price: Optional[float] = None
    history_entities: Optional[str] = None


class SmartHomeCommand(BaseModel):
    text: str
    confirm: bool = False


class SmartHomeAliasCreate(BaseModel):
    phrase: str
    entity_id: str


class SmartHomeAliasOut(BaseModel):
    id: int
    phrase: str
    entity_id: str


class FloorplanRoom(BaseModel):
    id: str
    name: str = ""
    x: float = 0.0
    y: float = 0.0
    w: float = 3.0
    h: float = 3.0
    area: Optional[str] = None


class FloorplanDevice(BaseModel):
    entity_id: str
    x: float = 0.0
    y: float = 0.0
    room_id: Optional[str] = None


class SmartHomeFloorplanIn(BaseModel):
    rooms: List[FloorplanRoom] = []
    devices: List[FloorplanDevice] = []


class AutomationSuggestRequest(BaseModel):
    count: int = 5


class AutomationFreeformRequest(BaseModel):
    text: str


class AutomationYamlUpdate(BaseModel):
    yaml_text: str


class SceneCreate(BaseModel):
    name: str
    entity_ids: List[str] = []


class SceneActivate(BaseModel):
    entity_id: str


class RecipeIn(BaseModel):
    name: str
    ingredients: Optional[str] = ""
    instructions: Optional[str] = ""
    servings: Optional[int] = None
    tags: Optional[str] = ""
    source: Optional[str] = "manuell"


class MealPlanIn(BaseModel):
    date: date
    meal: str
    recipe_id: Optional[int] = None
    note: Optional[str] = ""


class MealSuggestIn(BaseModel):
    count: int = 3
    prompt: Optional[str] = ""


class ShoppingPushIn(BaseModel):
    date_from: date
    date_to: date
    target: str = "wishlist"  # "wishlist" | "todo"

import enum
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime, ForeignKey, Enum, Text, UniqueConstraint, Boolean
)
from sqlalchemy.orm import relationship
from .database import Base


class AccountType(str, enum.Enum):
    girokonto = "girokonto"
    bargeld = "bargeld"
    sparkonto = "sparkonto"
    depot = "depot"
    sonstiges = "sonstiges"


class CategoryType(str, enum.Enum):
    einnahme = "einnahme"
    ausgabe = "ausgabe"


class AssetType(str, enum.Enum):
    aktie = "aktie"
    etf = "etf"
    anleihe = "anleihe"
    krypto = "krypto"
    sonstiges = "sonstiges"


class Space(Base):
    __tablename__ = "spaces"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    icon = Column(String, nullable=False, default="🏠")
    created_at = Column(DateTime, default=datetime.utcnow)

    accounts = relationship("Account", back_populates="space", cascade="all, delete-orphan")
    budgets = relationship("Budget", back_populates="space", cascade="all, delete-orphan")
    trips = relationship("Trip", back_populates="space", cascade="all, delete-orphan")
    holdings = relationship("Holding", back_populates="space", cascade="all, delete-orphan")
    bank_connections = relationship("BankConnection", back_populates="space", cascade="all, delete-orphan")
    bitvavo_connections = relationship("BitvavoConnection", back_populates="space", cascade="all, delete-orphan")
    enablebanking_connections = relationship("EnableBankingConnection", back_populates="space", cascade="all, delete-orphan")
    paypal_connections = relationship("PayPalConnection", back_populates="space", cascade="all, delete-orphan")
    # Bereichsübergreifende Ziele (space_id NULL) hängen an keiner Space-Collection
    # und überleben das Löschen eines Bereichs deshalb bewusst.
    goals = relationship("Goal", back_populates="space", cascade="all, delete-orphan")
    debts = relationship("Debt", back_populates="space", cascade="all, delete-orphan")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    type = Column(Enum(AccountType), nullable=False, default=AccountType.girokonto)
    initial_balance = Column(Float, nullable=False, default=0.0)
    # Steuert den Geschäftlich-Tab (Filter, kein eigener Bereich) - rechtlich bei
    # Einzelunternehmern ohnehin alles Privatvermögen, dient nur der Übersicht.
    is_business = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=False)

    space = relationship("Space", back_populates="accounts")
    transactions = relationship(
        "Transaction", back_populates="account", cascade="all, delete-orphan"
    )


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    type = Column(Enum(CategoryType), nullable=False)
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True)

    parent = relationship("Category", remote_side=[id], backref="children")
    transactions = relationship("Transaction", back_populates="category")


class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, default=1)
    display_name = Column(String, nullable=False, default="Mein Finanztool")
    secret_key = Column(String, nullable=False)
    fints_product_id = Column(String, nullable=True)
    enablebanking_app_id = Column(String, nullable=True)
    enablebanking_private_key_encrypted = Column(Text, nullable=True)
    ollama_url = Column(String, nullable=True)
    ollama_model = Column(String, nullable=True)
    beleg_chat_model = Column(String, nullable=True)
    sync_hour = Column(Integer, nullable=False, default=3)
    auto_backup_enabled = Column(Boolean, nullable=False, default=True)
    backup_hour = Column(Integer, nullable=False, default=2)
    backup_retention = Column(Integer, nullable=False, default=14)
    sparerpauschbetrag = Column(Float, nullable=False, default=1000.0)
    auto_categorize_enabled = Column(Boolean, nullable=False, default=True)
    brave_search_api_key_encrypted = Column(String, nullable=True)
    # Reine Anzeige-Einstellung: gespeichert wird immer in EUR, hier steht nur,
    # in welcher Währung das Frontend umrechnet/anzeigt.
    display_currency = Column(String, nullable=False, default="EUR")
    # --- Benachrichtigungen (Telegram) ---
    notifications_enabled = Column(Boolean, nullable=False, default=True)
    telegram_bot_token_encrypted = Column(String, nullable=True)
    telegram_chat_id = Column(String, nullable=True)
    # Zuletzt verarbeitete Telegram-Update-ID (Long-Polling-Offset) - persistiert,
    # damit ein Neustart nicht die komplette Update-Warteschlange erneut abarbeitet.
    telegram_last_update_id = Column(Integer, nullable=True)
    # --- Echte Anrufe (Twilio) für wirklich zeitkritische Fälle ---
    # Default False (anders als notifications_enabled): eine kostenpflichtige,
    # das Telefon klingelnde Aktion sollte nie ungefragt aktiv sein.
    calls_enabled = Column(Boolean, nullable=False, default=False)
    twilio_account_sid = Column(String, nullable=True)
    twilio_auth_token_encrypted = Column(String, nullable=True)
    twilio_from_number = Column(String, nullable=True)
    twilio_to_number = Column(String, nullable=True)
    # Sperren gegen wiederholte Alarme für denselben Zustand (kein neuer Trigger,
    # solange sich der Tag/Monat nicht ändert - siehe main._check_daily_alerts).
    last_cashflow_alert_date = Column(Date, nullable=True)
    last_budget_alert_month = Column(String, nullable=True)
    # Für den Vermögensvergleich mit der eigenen Altersgruppe. Nur das Jahr.
    birth_year = Column(Integer, nullable=True)
    # --- Immich (Fotobibliothek) ---
    # URL im Klartext (kein Geheimnis), Schlüssel verschlüsselt wie alle anderen.
    immich_url = Column(String, nullable=True)
    immich_api_key_encrypted = Column(String, nullable=True)
    # Standard bleibt bewusst "mit Bestaetigung" (False) - eine Papierkorb-
    # Aktion ohne jede Rueckfrage sollte man aktiv anschalten muessen, nicht
    # aus Versehen schon aktiv haben.
    immich_skip_confirm = Column(Boolean, nullable=False, default=False)
    # Fortlaufender Scan auf unscharfe/leere Fotos: läuft seitenweise im
    # Hintergrund (die Bibliothek ist zu groß für einen einzelnen Durchlauf)
    # und beginnt nach der letzten Seite wieder von vorn, damit auch neu
    # hinzugekommene Fotos irgendwann erfasst werden.
    immich_quality_scan_page = Column(Integer, nullable=False, default=1)
    # --- eBay (Verkäufe als vollwertiges Konto) ---
    # App-Zugangsdaten gelten fuer die ganze Instanz (eine eBay-App), so wie
    # bei Enable Banking - nicht pro Verbindung wie bei PayPal, wo jede
    # Verbindung ihre eigene PayPal-App war.
    ebay_app_id = Column(String, nullable=True)
    ebay_cert_id_encrypted = Column(String, nullable=True)
    # eBays Bezeichnung fuer die registrierte Redirect-Adresse (RuName) - kein
    # gewoehnliches redirect_uri, sondern ein bei eBay hinterlegter Name.
    ebay_ru_name = Column(String, nullable=True)
    # --- Radicale (To-Dos, CalDAV) ---
    # Bewusst die volle Adresse der Todo-Liste (Kalender-Collection) statt nur
    # der Server-URL - eine automatische Kalender-Erkennung wäre für eine
    # einzelne, vom Nutzer selbst benannte Liste unnötiger Aufwand.
    radicale_url = Column(String, nullable=True)
    radicale_username = Column(String, nullable=True)
    radicale_password_encrypted = Column(String, nullable=True)
    # --- Datei-Sortierung (Eingangsordner automatisch einsortieren) ---
    # Pfade wie vom Container aus gesehen (Volume-Mounts) - nicht die
    # Host-Pfade auf TrueNAS.
    file_sort_source_path = Column(String, nullable=True)
    file_sort_target_path = Column(String, nullable=True)
    # Feste Kategorienliste statt KI-erfundener Ordnernamen - verhindert
    # Ordner-Wildwuchs ("Strom" vs. "Stromrechnung" vs. "Energie").
    file_sort_categories = Column(String, nullable=True, default="Behoerde,Bericht,Rechnung,Sonstiges,Vertrag")
    file_sort_enabled = Column(Boolean, nullable=False, default=False)
    # --- E-Mail-Postfach (Belege aus Anhängen) ---
    mail_enabled = Column(Boolean, nullable=False, default=False)
    imap_host = Column(String, nullable=True)
    imap_port = Column(Integer, nullable=False, default=993)
    imap_user = Column(String, nullable=True)
    imap_password_encrypted = Column(String, nullable=True)
    imap_folder = Column(String, nullable=False, default="INBOX")
    mail_last_sync_at = Column(DateTime, nullable=True)


class BasiszinsRate(Base):
    __tablename__ = "basiszins_rates"

    year = Column(Integer, primary_key=True)
    rate_percent = Column(Float, nullable=False)


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("space_id", "category_id", name="uq_budget_space_category"),)

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    monthly_limit = Column(Float, nullable=False)

    space = relationship("Space", back_populates="budgets")
    category = relationship("Category")


class Trip(Base):
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    name = Column(String, nullable=False)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)

    space = relationship("Space", back_populates="trips")
    transactions = relationship("Transaction", back_populates="trip")


class LotType(str, enum.Enum):
    kauf = "kauf"
    verkauf = "verkauf"
    staking = "staking"
    dividende = "dividende"


class Holding(Base):
    __tablename__ = "holdings"

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    asset_type = Column(Enum(AssetType), nullable=False)
    name = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    sector = Column(String, nullable=True)
    country = Column(String, nullable=True)
    currency = Column(String, nullable=True)
    # quantity/purchase_price/purchase_date sind ab dem ersten Kauf-Lot abgeleitete
    # Werte (siehe crud.recompute_holding_from_lots) - hier trotzdem gespeichert,
    # damit Listen/Dashboard/Net-Worth ohne Neuberechnung bei jedem Request auskommen.
    quantity = Column(Float, nullable=False)
    purchase_price = Column(Float, nullable=False)
    purchase_date = Column(Date, nullable=True)
    current_price = Column(Float, nullable=True)
    price_updated_at = Column(DateTime, nullable=True)

    space = relationship("Space", back_populates="holdings")
    lots = relationship("HoldingLot", back_populates="holding", cascade="all, delete-orphan", order_by="HoldingLot.date")


class HoldingLot(Base):
    __tablename__ = "holding_lots"

    id = Column(Integer, primary_key=True, index=True)
    holding_id = Column(Integer, ForeignKey("holdings.id"), nullable=False)
    date = Column(Date, nullable=False, default=date.today)
    type = Column(Enum(LotType), nullable=False, default=LotType.kauf)
    quantity = Column(Float, nullable=False)
    price_per_unit = Column(Float, nullable=False)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    holding = relationship("Holding", back_populates="lots")


class BankConnection(Base):
    __tablename__ = "bank_connections"

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    name = Column(String, nullable=False)
    blz = Column(String, nullable=False)
    fints_url = Column(String, nullable=False)
    login = Column(String, nullable=False)
    pin_encrypted = Column(String, nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    iban = Column(String, nullable=True)
    last_sync_at = Column(DateTime, nullable=True)
    last_sync_status = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    space = relationship("Space", back_populates="bank_connections")
    account = relationship("Account")


class BitvavoConnection(Base):
    __tablename__ = "bitvavo_connections"

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    name = Column(String, nullable=False)
    api_key_encrypted = Column(String, nullable=False)
    api_secret_encrypted = Column(String, nullable=False)
    last_sync_at = Column(DateTime, nullable=True)
    last_sync_status = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    space = relationship("Space", back_populates="bitvavo_connections")


class PayPalConnection(Base):
    __tablename__ = "paypal_connections"

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    name = Column(String, nullable=False)
    client_id_encrypted = Column(String, nullable=False)
    client_secret_encrypted = Column(String, nullable=False)
    last_sync_at = Column(DateTime, nullable=True)
    last_sync_status = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    space = relationship("Space", back_populates="paypal_connections")
    account = relationship("Account")


class EnableBankingConnection(Base):
    __tablename__ = "enablebanking_connections"

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    aspsp_name = Column(String, nullable=False)
    aspsp_country = Column(String, nullable=False)
    state = Column(String, nullable=False, unique=True, index=True)
    session_id = Column(String, nullable=True)
    eb_account_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")
    last_sync_at = Column(DateTime, nullable=True)
    last_sync_status = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    space = relationship("Space", back_populates="enablebanking_connections")
    account = relationship("Account")


class EbayConnection(Base):
    """Eine per OAuth verbundene eBay-Verkäufer-Verbindung, gemappt auf ein
    eigenes Konto - Verkäufe sollen laut Vision-Entscheidung wie ein Konto ins
    Dashboard/Vermögen einfließen, nicht nur als separater Report daneben
    stehen (siehe [[project_finance_app_vision]])."""

    __tablename__ = "ebay_connections"

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    ebay_username = Column(String, nullable=True)
    state = Column(String, nullable=False, unique=True, index=True)
    refresh_token_encrypted = Column(Text, nullable=True)
    # eBay-Refresh-Token gilt ca. 18 Monate - danach muss der Nutzer die
    # Zustimmung erneut erteilen. Wird angezeigt, damit das nicht überrascht.
    refresh_token_expires_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False, default="pending")
    last_sync_at = Column(DateTime, nullable=True)
    last_sync_status = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    space = relationship("Space")
    account = relationship("Account")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, default=date.today)
    amount = Column(Float, nullable=False)  # positiv = Einnahme, negativ = Ausgabe
    description = Column(String, nullable=True)
    notes = Column(Text, nullable=True)

    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=True)

    receipt_filename = Column(String, nullable=True)
    import_hash = Column(String, nullable=True, index=True)
    # True = Umbuchung zwischen zwei eigenen Konten (automatisch per Muster erkannt,
    # siehe crud.detect_and_mark_transfers). Zählt nicht als Einnahme/Ausgabe.
    is_transfer = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account", back_populates="transactions")
    category = relationship("Category", back_populates="transactions")
    trip = relationship("Trip", back_populates="transactions")


class DebtKind(str, enum.Enum):
    annuitaeten = "annuitaeten"   # feste Rate, Zinsanteil sinkt über die Laufzeit
    raten = "raten"               # feste Tilgung, Rate sinkt über die Laufzeit
    endfaellig = "endfaellig"     # nur Zinsen, Tilgung komplett am Ende
    dispo = "dispo"               # Dispo/Kreditlinie, keine feste Laufzeit
    privat = "privat"             # Privatdarlehen, oft ohne Zinsen


class DebtStatus(str, enum.Enum):
    active = "active"
    paid_off = "paid_off"


class Debt(Base):
    """Ein Kredit/eine Schuld. Bewusst eine eigene Entität statt eines Kontos mit
    negativem Saldo: nur so lassen sich Zinssatz, Rate, Laufzeit und die Trennung
    von Zins- und Tilgungsanteil sauber abbilden.

    `current_balance` ist wie Holding.quantity ein aus dem Zahlungs-Ledger
    abgeleiteter Wert (siehe crud.recompute_debt_from_payments) - gespeichert,
    damit Listen und die Vermögensberechnung ohne Neuberechnung auskommen."""

    __tablename__ = "debts"

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    name = Column(String, nullable=False)
    kind = Column(Enum(DebtKind), nullable=False, default=DebtKind.annuitaeten)
    lender = Column(String, nullable=True)
    original_amount = Column(Float, nullable=False)
    current_balance = Column(Float, nullable=False, default=0.0)
    interest_rate_percent = Column(Float, nullable=False, default=0.0)
    monthly_payment = Column(Float, nullable=True)
    start_date = Column(Date, nullable=True)
    planned_end_date = Column(Date, nullable=True)
    # --- Zinsbindung ---
    # Bis hierhin gilt interest_rate_percent garantiert. Danach rechnet die
    # Prognose mit follow_up_interest_rate_percent - das ist eine Annahme des
    # Nutzers, kein zugesagter Satz.
    interest_fixed_until = Column(Date, nullable=True)
    follow_up_interest_rate_percent = Column(Float, nullable=True)
    # --- Bereitstellungszinsen (auf den noch nicht abgerufenen Betrag) ---
    commitment_rate_percent = Column(Float, nullable=True)
    commitment_free_months = Column(Integer, nullable=True)
    undisbursed_amount = Column(Float, nullable=True)
    # --- Nebenkosten: tilgen nichts, erhöhen aber die Belastung ---
    upfront_fees = Column(Float, nullable=True)
    monthly_fee = Column(Float, nullable=True)
    monthly_insurance = Column(Float, nullable=True)
    # Optional: von welchem Konto die Rate abgebucht wird (nur informativ, die
    # Zahlungen selbst hängen am Ledger unten).
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    status = Column(Enum(DebtStatus), nullable=False, default=DebtStatus.active)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    space = relationship("Space", back_populates="debts")
    account = relationship("Account")
    payments = relationship(
        "DebtPayment", back_populates="debt", cascade="all, delete-orphan",
        order_by="DebtPayment.date",
    )


class DebtPayment(Base):
    """Einzelne Zahlung auf einen Kredit (Rate oder Sondertilgung).

    `interest_amount` ist NULL, solange die App den Zinsanteil selbst rechnet
    (Restschuld × Zinssatz ÷ 12). Ein gesetzter Wert ist eine bewusste Korrektur
    des Nutzers und wird nie überschrieben. Die effektive Aufteilung entsteht in
    debts.payment_breakdown() und wird absichtlich nicht doppelt gespeichert."""

    __tablename__ = "debt_payments"

    id = Column(Integer, primary_key=True, index=True)
    debt_id = Column(Integer, ForeignKey("debts.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, default=date.today)
    total_amount = Column(Float, nullable=False)
    interest_amount = Column(Float, nullable=True)
    # Gebühren-/Versicherungsanteil der Zahlung. Geht weder in Zins noch Tilgung
    # ein, mindert die Restschuld also nicht.
    fee_amount = Column(Float, nullable=True)
    is_extra_repayment = Column(Boolean, nullable=False, default=False)
    # Optionale Verknüpfung zu einer echten Buchung, damit dieselbe Zahlung nicht
    # doppelt gezählt wird, wenn sie ohnehin auf einem Konto auftaucht.
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    debt = relationship("Debt", back_populates="payments")
    transaction = relationship("Transaction")


class GoalType(str, enum.Enum):
    auto_financial = "auto_financial"
    manual = "manual"


class GoalStatus(str, enum.Enum):
    open = "open"
    completed = "completed"
    archived = "archived"


class GoalMetricType(str, enum.Enum):
    net_worth = "net_worth"
    account_balance = "account_balance"
    investment_value = "investment_value"
    savings_rate = "savings_rate"
    custom_category_sum = "custom_category_sum"
    debt_balance = "debt_balance"


class GoalComparison(str, enum.Enum):
    gte = "gte"
    lte = "lte"


class Goal(Base):
    """Ziel/Meilenstein. Absichtlich nicht rein finanziell gedacht: `manual`-Ziele
    haben keinerlei Finanzbezug, und `category` ist ein freier String - spätere
    nicht-finanzielle Lebensbereiche brauchen daher kein Schema-Update, sondern
    höchstens neue GoalMetricType-Werte für automatisch messbare Ziele.

    Die Tabellen entstehen wie überall in dieser App über Base.metadata.create_all()
    beim Start (kein Alembic) - siehe main.py."""

    __tablename__ = "goals"

    id = Column(Integer, primary_key=True, index=True)
    # NULL = bereichsübergreifend (in jedem Space sichtbar, Metriken über alle
    # Bereiche gerechnet) - analog dazu, dass Kategorien global sind.
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String, nullable=True)
    goal_type = Column(Enum(GoalType), nullable=False, default=GoalType.manual)
    target_date = Column(Date, nullable=True)
    status = Column(Enum(GoalStatus), nullable=False, default=GoalStatus.open)
    predecessor_goal_id = Column(Integer, ForeignKey("goals.id"), nullable=True)
    # Wird beim automatischen Erreichen auf False gesetzt, damit das Frontend
    # einmalig "Neu erreicht" markieren kann.
    completion_seen = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    space = relationship("Space", back_populates="goals")
    predecessor = relationship("Goal", remote_side=[id])
    trigger = relationship(
        "GoalTrigger", back_populates="goal", uselist=False, cascade="all, delete-orphan"
    )
    progress_points = relationship(
        "GoalProgress", back_populates="goal", cascade="all, delete-orphan",
        order_by="GoalProgress.timestamp",
    )


class GoalTrigger(Base):
    """Auswertungsregel eines `auto_financial`-Ziels (1:1 zum Goal).

    Der Geltungsbereich wird über die scope_*-Spalten abgebildet statt über ein
    JSON-Feld - je Metrik ist höchstens eine davon belegt. Neue Metriken mit
    neuem Scope bekommen später eine weitere nullable Spalte via ensure_columns()."""

    __tablename__ = "goal_triggers"

    id = Column(Integer, primary_key=True, index=True)
    goal_id = Column(Integer, ForeignKey("goals.id"), nullable=False, unique=True)
    metric_type = Column(Enum(GoalMetricType), nullable=False)
    comparison = Column(Enum(GoalComparison), nullable=False, default=GoalComparison.gte)
    threshold_value = Column(Float, nullable=False)
    # Die App rechnet durchgängig in Euro; die Spalte existiert als Platzhalter
    # für eine spätere Mehrwährungsfähigkeit und wird im UI nicht angeboten.
    currency = Column(String, nullable=False, default="EUR")
    scope_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    scope_asset_type = Column(Enum(AssetType), nullable=True)
    scope_category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    scope_debt_id = Column(Integer, ForeignKey("debts.id"), nullable=True)
    # Zeitfenster in Monaten (savings_rate: so viele Monate in Folge;
    # custom_category_sum: Summe der letzten so vielen Monate).
    evaluation_window_months = Column(Integer, nullable=True)

    goal = relationship("Goal", back_populates="trigger")
    scope_account = relationship("Account")
    scope_category = relationship("Category")
    scope_debt = relationship("Debt")


class GoalProgress(Base):
    """Verlaufspunkt eines Ziels - wird vom täglichen Auswertungsjob geschrieben,
    damit ein Fortschrittsgraph möglich ist (Live-Berechnung allein hinterlässt
    keine Historie)."""

    __tablename__ = "goal_progress"

    id = Column(Integer, primary_key=True, index=True)
    goal_id = Column(Integer, ForeignKey("goals.id"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    current_value = Column(Float, nullable=False)

    goal = relationship("Goal", back_populates="progress_points")


class PriceHistoryCache(Base):
    __tablename__ = "price_history_cache"
    __table_args__ = (UniqueConstraint("asset_type", "symbol", "range_key", name="uq_price_cache"),)

    id = Column(Integer, primary_key=True, index=True)
    asset_type = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    range_key = Column(String, nullable=False)
    fetched_at = Column(DateTime, nullable=False)
    data_json = Column(Text, nullable=False)


class MailAttachment(Base):
    """Ein aus einer E-Mail geholter Beleg, bevor er einer Buchung zugeordnet ist.

    Eigene Tabelle statt direkt an eine Buchung zu haengen: Beim Abholen ist
    noch nicht bekannt, zu welcher Buchung ein Anhang gehoert - manches passt
    eindeutig, manches gar nicht, und manches gehoert zu einer Buchung, die es
    noch nicht gibt (Kontoumsatz kommt oft Tage nach der Rechnung). Der Anhang
    muss also zwischengelagert werden koennen, ohne verloren zu gehen.
    """

    __tablename__ = "mail_attachments"
    __table_args__ = (UniqueConstraint("message_id", "filename", name="uq_mail_attachment"),)

    id = Column(Integer, primary_key=True, index=True)
    # message_id + Dateiname verhindern, dass derselbe Anhang bei jedem
    # Abholen erneut angelegt wird (gleiches Prinzip wie bei den Bank-Importen).
    message_id = Column(String, nullable=False, index=True)
    filename = Column(String, nullable=False)
    # Name auf der Platte in data/uploads - der Originalname ist nicht sicher.
    stored_filename = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=True)

    sender = Column(String, nullable=True)
    subject = Column(String, nullable=True)
    mail_date = Column(DateTime, nullable=True)
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # "pending" = liegt zur Sichtung, "attached" = einer Buchung zugeordnet,
    # "ignored" = vom Nutzer als uninteressant abgelegt.
    status = Column(String, nullable=False, default="pending")
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)

    # Aus dem Beleg ausgelesen (Datum/Betrag), fuer die Zuordnung.
    parsed_amount = Column(Float, nullable=True)
    parsed_date = Column(Date, nullable=True)
    parse_error = Column(String, nullable=True)

    transaction = relationship("Transaction")


class ImmichQualityFlag(Base):
    """Ein von der Immich-Bibliothek als 'unnötig' erkanntes Foto (unscharf
    oder leer/einfarbig) - Ergebnis des seitenweisen Hintergrund-Scans.

    Nur AUFFÄLLIGE Fotos werden gespeichert, nicht die ganze Bibliothek -
    bei ~24.000 Aufnahmen wäre ein Zwischenspeicher aller Ergebnisse reiner
    Ballast. Ein erneuter Scan (siehe Settings.immich_quality_scan_page)
    überschreibt bestehende Einträge einfach neu, verschwundene oder
    inzwischen unauffällige Fotos bleiben aber bis zum nächsten Durchlauf
    stehen - das ist hier bewusst in Kauf genommen, denn löschen würde
    bedeuten, den Nutzer-Ausschluss (dismiss) zu verlieren.
    """

    __tablename__ = "immich_quality_flags"

    asset_id = Column(String, primary_key=True)
    file_name = Column(String, nullable=True)
    created_at_immich = Column(String, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    # "blur" oder "blank".
    reason = Column(String, nullable=False)
    score = Column(Float, nullable=True)
    scanned_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # Vom Nutzer bewusst behalten ("ist doch okay") - taucht dann nicht mehr
    # in der Liste auf, auch wenn ein erneuter Scan den Eintrag sonst wieder
    # anlegen würde.
    dismissed = Column(Boolean, nullable=False, default=False)


class FileSortLog(Base):
    """Protokoll jeder automatischen Datei-Einsortierung - vollständige
    Nachvollziehbarkeit ist hier der Ersatz für eine Bestätigung pro Datei:
    bewegt wird automatisch, aber jede Aktion bleibt sichtbar und die
    Originaldatei wird nie überschrieben (siehe file_sort.py)."""

    __tablename__ = "file_sort_log"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    category = Column(String, nullable=True)
    # "moved", "skipped_uncertain", "skipped_unsupported", "error"
    action = Column(String, nullable=False)
    detail = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Todo(Base):
    """To-Do, zweiseitig mit einem Radicale/CalDAV-Server synchronisiert - der
    Nutzer trägt To-Dos oft am Handy in einer CalDAV-App ein und will sie auch
    hier sehen und abhaken, nicht nur andersherum.

    Bewusst KEINE eigene Kalender-/iCal-Bibliothek: die VTODO-Teilmenge, die
    hier gebraucht wird (UID/SUMMARY/STATUS/DUE/LAST-MODIFIED), ist klein genug,
    um sie direkt zu lesen und zu schreiben - passend zum Rest der App, die
    auch bei Immich/PayPal/eBay ohne SDK direkt gegen die HTTP-APIs arbeitet.

    Kein space_id: To-Dos sind persönlich und bereichsübergreifend gemeint,
    genauso wie ein `manual`-Ziel ohne Bereichsbindung.
    """

    __tablename__ = "todos"

    id = Column(Integer, primary_key=True, index=True)
    # Lokal per uuid4 erzeugt (neue Todos) oder vom Server übernommen (von dort
    # gezogene Todos) - eindeutiger Schlüssel für den Abgleich in beide
    # Richtungen, unabhängig vom lokalen href/etag.
    uid = Column(String, nullable=False, unique=True, index=True)
    title = Column(String, nullable=False)
    done = Column(Boolean, nullable=False, default=False)
    # Gesetzt, sobald `done` auf True wechselt - Grundlage für die
    # automatische Aufräumung 2 Tage nach dem Abhaken (siehe main.py).
    completed_at = Column(DateTime, nullable=True)
    due_date = Column(Date, nullable=True)
    # href/etag: Position und Versionsstempel der Ressource auf dem Radicale-
    # Server. NULL, solange das Todo lokal angelegt, aber noch nicht
    # hochgeladen wurde.
    href = Column(String, nullable=True)
    etag = Column(String, nullable=True)
    # Für die Sync-Richtung: wurde seit dem letzten Abgleich lokal geändert,
    # muss das gepusht werden, statt eine ältere Server-Fassung zu übernehmen.
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced_at = Column(DateTime, nullable=True)
    # Löschung erst als Markierung, damit der nächste Sync sie noch zum Server
    # übertragen kann, bevor die Zeile tatsächlich verschwindet.
    pending_delete = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

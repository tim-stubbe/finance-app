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
    tagesgeldkonto = "tagesgeldkonto"
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
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Nettovermögen beim letzten gesendeten Digest (main._scheduled_digest) -
    # Grundlage für den "seit der letzten Nachricht"-Vergleich dort, statt
    # gegen den taeglichen NetWorthSnapshot zu vergleichen (der Digest laeuft
    # mehrmals taeglich, ein Tages-Snapshot waere fuer diesen Vergleich zu grob).
    last_digest_net_worth = Column(Float, nullable=True)

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
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    # True, solange der Saldo negativ ist UND dafür schon einmal per Telegram
    # gewarnt wurde - verhindert taegliche Wiederholmeldungen, waehrend das Konto
    # im Minus bleibt. Wird zurueckgesetzt, sobald der Saldo wieder >= 0 ist, damit
    # ein spaeterer erneuter Dispo-Rutsch wieder frisch meldet (siehe
    # main._check_daily_alerts).
    dispo_alert_sent = Column(Boolean, nullable=False, default=False)

    space = relationship("Space", back_populates="accounts")
    transactions = relationship(
        "Transaction", back_populates="account", cascade="all, delete-orphan"
    )


class AccountBalanceLog(Base):
    """Protokoll jeder manuellen Kontostand-Änderung (Startsaldo) - Nachvollzieh-
    barkeit als Ersatz für eine Bestätigung, ähnlich wie bei FileSortLog frueher:
    per Telegram gesetzte Werte laufen ohne Rückfrage direkt durch, bleiben aber
    immer sichtbar, wer/was den Stand wann geändert hat."""

    __tablename__ = "account_balance_log"

    id = Column(Integer, primary_key=True, index=True)
    # Genau eines von beiden ist gesetzt - seit /saldo auch Schulden (z.B.
    # Kreditkarten als Dispo/Kreditlinie) direkt setzen kann, nicht mehr nur Konten.
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    debt_id = Column(Integer, ForeignKey("debts.id"), nullable=True)
    old_balance = Column(Float, nullable=False)
    new_balance = Column(Float, nullable=False)
    source = Column(String, nullable=False)  # "app" oder "telegram"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("Account")
    debt = relationship("Debt")


class NotifiedAnomaly(Base):
    """Merkt sich, welche Preiserhöhungen/Ausgaben-Ausreißer schon per Telegram
    gemeldet wurden, damit dieselbe Auffälligkeit nicht bei jedem Scheduler-Lauf
    erneut geschickt wird - reine Dedupe-Tabelle, kein fachlicher Wert
    (detect_price_increases/detect_spending_anomalies bleiben die Quelle der
    Wahrheit, hier steht nur "wurde für DIESEN key schon benachrichtigt")."""

    __tablename__ = "notified_anomalies"

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    key = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AlertRuleType(str, enum.Enum):
    category_spend_above = "category_spend_above"   # Ausgaben in Kategorie diesen Monat > Schwelle
    account_balance_below = "account_balance_below"  # Kontostand < Schwelle
    category_deviation = "category_deviation"        # Kategorie weicht > Schwelle% vom 3-Monats-Schnitt ab
    goal_progress_above = "goal_progress_above"      # Ziel zu >= Schwelle% erreicht


class AlertRule(Base):
    """Nutzerdefinierte Schwellwert-Regel, die main._scheduled_alert_rules im
    selben 30-Minuten-Takt wie die eingebauten Sofort-Alarme (Preiserhöhung/
    Ausgaben-Ausreißer/Terminüberschneidung) prüft und bei Auslösung per
    Telegram meldet - bewusst eine Handvoll fester Regeltypen statt einer
    freien Regel-Engine (Nutzerwunsch: "keine komplexe visuelle Regel-Engine
    bauen"). last_triggered_date verhindert Mehrfach-Meldungen am selben Tag,
    erlaubt aber eine erneute taegliche Erinnerung, solange die Regel weiter
    zutrifft (anders als NotifiedAnomaly, das dauerhaft nicht erneut meldet -
    hier soll ein dauerhaft zu niedriger Kontostand nicht nach einem Tag
    verstummen)."""

    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    rule_type = Column(Enum(AlertRuleType), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    goal_id = Column(Integer, ForeignKey("goals.id"), nullable=True)
    threshold = Column(Float, nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    last_triggered_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = relationship("Category")
    account = relationship("Account")
    goal = relationship("Goal")


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    type = Column(Enum(CategoryType), nullable=False)
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    parent = relationship("Category", remote_side=[id], backref="children")
    transactions = relationship("Transaction", back_populates="category")


class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, default=1)
    display_name = Column(String, nullable=False, default="Kies")
    secret_key = Column(String, nullable=False)
    fints_product_id = Column(String, nullable=True)
    enablebanking_app_id = Column(String, nullable=True)
    enablebanking_private_key_encrypted = Column(Text, nullable=True)
    # Überschreibt die automatisch aus der aufgerufenen Adresse abgeleitete
    # Redirect-URL für den OAuth-Rücksprung (z.B. "https://100.72.226.91:8444"
    # bei einem separaten HTTPS-Proxy, da Enable Banking für Live-Apps eine
    # https-Redirect-URL verlangt, die App selbst aber nur über http läuft).
    # Leer = wie bisher aus der aufrufenden Anfrage abgeleitet.
    enablebanking_redirect_base_url = Column(String, nullable=True)
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
    # "brave" (bezahlte API, braucht Key) oder "searxng" (selbst gehostete
    # Instanz, kostenlos, kein Key noetig) - siehe websearch.py. Default
    # bleibt "brave", damit bestehende Installationen mit hinterlegtem Key
    # unveraendert weiterlaufen.
    websearch_provider = Column(String, nullable=False, default="brave")
    searxng_url = Column(String, nullable=True)
    # Reine Anzeige-Einstellung: gespeichert wird immer in EUR, hier steht nur,
    # in welcher Währung das Frontend umrechnet/anzeigt.
    display_currency = Column(String, nullable=False, default="EUR")
    # Wohnsitzland - rein zum Ein-/Ausblenden landesspezifischer Anbindungen
    # in den Einstellungen (z.B. FinTS ist deutschlandspezifisch). Bewusst
    # unabhängig von display_currency: wer in der Schweiz wohnt, will trotzdem
    # in EUR anzeigen können und umgekehrt.
    residence_country = Column(String, nullable=False, default="DE")
    # --- Benachrichtigungen (Telegram) ---
    notifications_enabled = Column(Boolean, nullable=False, default=True)
    telegram_bot_token_encrypted = Column(String, nullable=True)
    telegram_chat_id = Column(String, nullable=True)
    # Zuletzt verarbeitete Telegram-Update-ID (Long-Polling-Offset) - persistiert,
    # damit ein Neustart nicht die komplette Update-Warteschlange erneut abarbeitet.
    telegram_last_update_id = Column(Integer, nullable=True)
    # --- Eingehender Webhook (z.B. n8n meldet E-Mail-Ereignisse als offene
    # Punkte bei einem Business-Projekt) - n8n bleibt fuer die eigentliche
    # E-Mail-Verarbeitung zustaendig (Nutzerentscheidung), Kies nimmt nur das
    # fertige Ergebnis entgegen. Der Secret wird dem Nutzer im Klartext
    # angezeigt (zum Eintragen in n8n), deshalb verschluesselt statt gehasht
    # gespeichert - anders als ein Passwort muss er wieder lesbar sein.
    n8n_webhook_secret_encrypted = Column(String, nullable=True)
    # --- Nativer macOS-Client (Offline-Sync) --- Gleiches Muster wie oben:
    # Klartext einmalig angezeigt zum Eintragen in der nativen App, deshalb
    # verschluesselt statt gehasht gespeichert (muss wieder lesbar sein).
    native_sync_secret_encrypted = Column(String, nullable=True)
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
    # Eigene Collection-URL fuer echte Kalender-Termine (VEVENT) - separat von
    # radicale_url (To-Dos/VTODO), da Radicale Termine und To-Dos typischerweise
    # in zwei verschiedenen Listen fuehrt. Nur lesend synchronisiert (siehe
    # CalendarEvent) - Termine werden im echten Kalender angelegt, nicht hier.
    radicale_calendar_url = Column(String, nullable=True)
    # --- Fahrzeit zu Terminen (siehe travel_time.py) ---
    # lat/lon werden beim Speichern der Adresse einmalig geokodiert und
    # zwischengespeichert, statt bei jedem Digest-Lauf erneut Nominatim zu
    # fragen (Adresse aendert sich praktisch nie, Koordinaten schon).
    home_address = Column(String, nullable=True)
    home_lat = Column(Float, nullable=True)
    home_lon = Column(Float, nullable=True)
    openroute_api_key_encrypted = Column(String, nullable=True)
    # Zeitpunkt des letzten Status-Updates - Grundlage fuer "seit dem letzten
    # Update automatisch erledigt" im Digest (siehe crud.build_digest).
    last_digest_sent_at = Column(DateTime, nullable=True)
    # Laufender Zaehler seit dem letzten Digest, im Digest ausgelesen und dort
    # wieder auf 0 gesetzt - einfacher als ein Zeitstempel pro Buchung, weil
    # eine Umbuchungs-Markierung (anders als eine Kategorie) nicht rueckwirkend
    # nachvollziehbar sein muss.
    transfers_marked_since_digest = Column(Integer, nullable=False, default=0)
    # --- Morgen-Briefing (main._scheduled_morning_briefing) - ergänzt den
    # 3-stündlichen Digest um einen EINEN kompakten Ping am Morgen, siehe
    # crud.build_morning_briefing. send_empty Default False: "still, wenn
    # nichts ist" ist ausdrücklicher Nutzerwunsch, nicht die Ausnahme.
    morning_briefing_enabled = Column(Boolean, nullable=False, default=True)
    morning_briefing_hour = Column(Integer, nullable=False, default=7)
    morning_briefing_minute = Column(Integer, nullable=False, default=30)
    morning_briefing_send_empty = Column(Boolean, nullable=False, default=False)
    # --- Quiet Mode (Ruhezeiten) - zentral in notifications.notify() geprüft,
    # siehe dort. quiet_until ist die manuelle "Ruhe bis HH:MM"-Überschreibung
    # (App + Telegram /ruhe), unabhängig von den festen Ruhezeiten.
    quiet_hours_enabled = Column(Boolean, nullable=False, default=False)
    quiet_hours_start_hour = Column(Integer, nullable=False, default=22)
    quiet_hours_end_hour = Column(Integer, nullable=False, default=7)
    quiet_until = Column(DateTime, nullable=True)
    # --- Mid-Week-Zwischenstand (main._scheduled_midweek_checkin) - Default
    # AUS, siehe dortigen Docstring (Spezifikation wollte selbst "im Zweifel
    # Default aus").
    midweek_checkin_enabled = Column(Boolean, nullable=False, default=False)
    # --- E-Mail-Postfach (Belege aus Anhängen) ---
    mail_enabled = Column(Boolean, nullable=False, default=False)
    imap_host = Column(String, nullable=True)
    imap_port = Column(Integer, nullable=False, default=993)
    imap_user = Column(String, nullable=True)
    imap_password_encrypted = Column(String, nullable=True)
    imap_folder = Column(String, nullable=False, default="INBOX")
    mail_last_sync_at = Column(DateTime, nullable=True)
    # --- Kreditkarten-Rechnung per E-Mail (fuer Karten ohne Enable-Banking-Sync) ---
    # Absender-Teilstring (z.B. "advanzia.com") - ohne diesen Abgleich wuerde
    # jede Rechnungsmail im Postfach faelschlich als Kreditkarten-Abrechnung gelten.
    creditcard_mail_sender = Column(String, nullable=True)
    # Genau eines von beiden ist gesetzt - siehe CreditCardBill.
    creditcard_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    creditcard_debt_id = Column(Integer, ForeignKey("debts.id"), nullable=True)
    # --- Scalable Capital (Investments, ueber das offizielle CLI-Binary "sc") ---
    # Kein API-Key/Secret hier - die Anmeldung laeuft per Device-Code-Flow direkt
    # ueber "sc login" (einmalig, ausserhalb von Kies, siehe scalable_sync.py-
    # Docstring), die Session liegt als Datei unter $XDG_CONFIG_HOME/scalable-cli/.
    scalable_enabled = Column(Boolean, nullable=False, default=False)
    scalable_last_sync_at = Column(DateTime, nullable=True)
    scalable_last_sync_status = Column(String, nullable=True)
    # Ziel-Bereich fuer den automatischen Hintergrund-Sync (siehe
    # sync_all_connections) - dort gibt es keine aktive Session, aus der sich
    # sonst wie beim manuellen Sync ueber auth.get_active_space_id ein Bereich
    # ableiten liesse. NULL faellt auf den ersten Bereich zurueck.
    scalable_space_id = Column(Integer, ForeignKey("spaces.id"), nullable=True)
    # --- Web-Login (siehe auth.py) - ersetzt die bisherige "keine Anmeldung"
    # (README/SECURITY.md, jetzt angepasst). Weiterhin Single-User: eine Zeile
    # reicht, kein User-Table noetig. password_hash bleibt NULL bis zum
    # Ersteinrichtungs-Assistenten (Setup-Wizard) - solange gilt "noch nicht
    # eingerichtet", GET /api/auth/status meldet das als setup_required.
    password_hash = Column(String, nullable=True)
    password_set_at = Column(DateTime, nullable=True)
    setup_completed_at = Column(DateTime, nullable=True)
    # TOTP-Secret verschluesselt wie alle anderen Secrets (encrypt_secret mit
    # secret_key) - erst NACH einer bestaetigten Erst-Verifikation aktiv
    # (totp_enabled=True), damit ein Nutzer, der den QR-Code nicht richtig
    # gescannt hat, sich nicht versehentlich aussperrt.
    totp_secret_encrypted = Column(String, nullable=True)
    totp_enabled = Column(Boolean, nullable=False, default=False)
    totp_confirmed_at = Column(DateTime, nullable=True)
    # Einmaliger Wiederherstellungscode fuer den Fall "TOTP-Geraet weg" -
    # gehasht wie das Passwort (nie im Klartext gespeichert), wird beim
    # Aktivieren von TOTP neu erzeugt und dem Nutzer GENAU EINMAL angezeigt.
    # Bewusst diese Variante statt "Restore aus Backup" als Dokumentations-
    # Empfehlung: ein Recovery-Code ist fuer eine Einzelperson ohne Support-
    # Team der pragmatischere Weg, keinen vollen Datenbank-Restore nur wegen
    # eines verlorenen Zweitfaktors zu brauchen.
    totp_recovery_code_hash = Column(String, nullable=True)
    # Default 5 Minuten (siehe Auftrag) - bewusst kurz, laesst sich in den
    # Einstellungen aendern (require_auth prueft das bei jeder Anfrage).
    session_idle_timeout_minutes = Column(Integer, nullable=False, default=5)
    # --- Brute-Force-Bremse (Login-Passwort UND TOTP-Code teilen sich denselben
    # Zaehler - beides ist "ein Versuch, sich anzumelden") ---
    failed_login_count = Column(Integer, nullable=False, default=0)
    failed_login_locked_until = Column(DateTime, nullable=True)


class PasskeyCredential(Base):
    """Ein registrierter Passkey (WebAuthn) - 1:n, ein Nutzer kann mehrere
    Geraete hinterlegen (z.B. iPhone + MacBook). Kein user_id-Fremdschluessel
    noetig: die App ist Single-User, jeder hier gespeicherte Credential
    gehoert implizit dem einen Nutzer."""

    __tablename__ = "passkey_credentials"

    id = Column(Integer, primary_key=True, index=True)
    # Base64url-kodierte raw Credential-ID vom Authenticator - eindeutig,
    # wird bei jedem Login-Versuch zum Nachschlagen gebraucht.
    credential_id = Column(String, nullable=False, unique=True, index=True)
    # COSE-Public-Key (CBOR-kodierte Bytes) als Base64 gespeichert - SQLite hat
    # zwar einen BLOB-Typ, Base64+String passt aber zum Rest der App (siehe
    # z.B. verschluesselte Secrets, auch als Text gespeichert) und bleibt in
    # jedem DB-Browser lesbar/kopierbar.
    public_key = Column(Text, nullable=False)
    # Anti-Cloning-Zaehler (WebAuthn-Spec) - muss bei jedem Login strikt steigen,
    # sonst deutet das auf einen geklonten Credential hin (siehe webauthn_routes).
    sign_count = Column(Integer, nullable=False, default=0)
    transports = Column(String, nullable=True)  # z.B. "internal,hybrid", nur Anzeige/Hint
    name = Column(String, nullable=True)  # Geraete-Label, z.B. "iPhone"
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)


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
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    space = relationship("Space", back_populates="budgets")
    category = relationship("Category")


class Trip(Base):
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    name = Column(String, nullable=False)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    # Optional - ohne Budget zeigt die App weiterhin nur die Ist-Ausgaben wie
    # bisher, kein erzwungenes Feld.
    budget = Column(Float, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    # Fuer welchen GESCHAETZTEN Dividendentermin schon per Telegram erinnert wurde
    # (siehe crud.upcoming_dividend_estimates) - verhindert taegliche Wiederholungen,
    # solange derselbe Termin noch bevorsteht. Aendert sich der geschaetzte Termin
    # (z.B. nach der naechsten tatsaechlichen Zahlung neu berechnet), wird wieder
    # frisch erinnert.
    next_dividend_notified_for = Column(Date, nullable=True)
    # Woher die Position kommt, falls automatisch synchronisiert (z.B.
    # "scalable", "bitvavo") - NULL bei manuell angelegten Positionen. Rein
    # informativ fuers Frontend (Badge "automatisch synchronisiert"), keine
    # Logik haengt daran.
    import_source = Column(String, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    space = relationship("Space", back_populates="holdings")
    lots = relationship("HoldingLot", back_populates="holding", cascade="all, delete-orphan", order_by="HoldingLot.date")


class SavingsPlan(Base):
    """Konfigurierte Sparpläne (wiederkehrende automatische Käufe), aktuell nur
    von Scalable Capital synchronisiert (siehe scalable_sync.sync_savings_plans)
    - bewusst NICHT als Holding mit quantity=0 modelliert (das war der alte
    Ansatz, hat live dazu geführt, dass Positionen ohne bisherige Ausführung als
    verwirrende "0"-Zeilen in der Holdings-Tabelle auftauchten). Ein Sparplan
    kann noch keine einzige Ausführung gehabt haben und trotzdem hier stehen -
    die zugehörige Holding (falls schon mind. 1x gekauft) existiert getrennt
    davon, verknüpft nur locker über die ISIN (symbol), keine feste Relation."""
    __tablename__ = "savings_plans"
    __table_args__ = (UniqueConstraint("space_id", "isin", name="uq_savings_plan_isin"),)

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    isin = Column(String, nullable=False)
    name = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    frequency = Column(String, nullable=False)
    day_of_month = Column(Integer, nullable=True)
    dynamization_rate = Column(Float, nullable=True)
    next_execution_date = Column(Date, nullable=True)
    security_type = Column(String, nullable=True)
    import_source = Column(String, nullable=False, default="scalable")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    space = relationship("Space")


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
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    # Gesetzt, sobald category_id auf einen Wert wechselt (egal ob durch die KI,
    # Sammel-Zuweisung oder manuell) - Grundlage fuer "was wurde seit dem letzten
    # Digest erledigt" (siehe crud.build_digest). Rein additiv, kein Rueckschluss
    # auf die aktuelle Kategorie moeglich, wenn sie sich seither nochmal aendert.
    categorized_at = Column(DateTime, nullable=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=True)

    receipt_filename = Column(String, nullable=True)
    # Volltext des Belegs für die Beleg-Suche (main._scheduled_receipt_indexing) -
    # bei einem durchsuchbaren PDF direkt der PDF-Text (kein KI-Aufruf nötig),
    # bei einem Foto/gescannten PDF eine Vision-Modell-Abschrift. receipt_indexed_at
    # wird IMMER gesetzt (auch bei leerem Ergebnis), sonst würde ein dauerhaft
    # nicht lesbarer Beleg bei jedem Lauf erneut versucht werden.
    receipt_text = Column(Text, nullable=True)
    receipt_indexed_at = Column(DateTime, nullable=True)
    import_hash = Column(String, nullable=True, index=True)
    # True = Umbuchung zwischen zwei eigenen Konten (automatisch per Muster erkannt,
    # siehe crud.detect_and_mark_transfers). Zählt nicht als Einnahme/Ausgabe.
    is_transfer = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
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
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

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


class CreditCardBill(Base):
    """Erkannte Fälligkeit + Betrag aus einer Kreditkarten-Rechnungsmail.

    Für Karten, die sich nicht per Enable Banking synchronisieren lassen
    (z.B. Advanzia/White-Label-Karten wie "Kreditkarte Gold" bei C24) - die
    einzige verfügbare Quelle für den Kontostand ist dann die monatliche
    Abrechnungsmail. Wird beim E-Mail-Abholen (siehe main._run_mail_sync)
    zusätzlich zur normalen Beleg-Auswertung erzeugt, wenn der Absender auf
    Settings.creditcard_mail_sender passt."""

    __tablename__ = "creditcard_bills"
    __table_args__ = (UniqueConstraint("message_id", name="uq_creditcard_bill_message"),)

    id = Column(Integer, primary_key=True, index=True)
    # Genau eines von beiden ist gesetzt - die meisten Karten dieser Art sind
    # eine eigene Schuld (Dispo/Kreditlinie), keine echte Kontoverbindung mit
    # Saldo-Sync (siehe Debt-Docstring), account_id bleibt fuer den Fall stehen,
    # dass die Karte doch als Konto gefuehrt wird.
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    debt_id = Column(Integer, ForeignKey("debts.id"), nullable=True)
    message_id = Column(String, nullable=False, index=True)
    subject = Column(String, nullable=True)
    due_date = Column(Date, nullable=True)
    amount = Column(Float, nullable=True)
    mail_attachment_id = Column(Integer, ForeignKey("mail_attachments.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    notified = Column(Boolean, nullable=False, default=False)

    account = relationship("Account")
    debt = relationship("Debt")


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


class CalendarEvent(Base):
    """Echter Kalender-Termin (VEVENT), zweiseitig mit Radicale synchronisiert -
    analog zu Todo (siehe dort für die Begründung: kein SDK, kleine iCal-
    Teilmenge direkt gelesen/geschrieben). Anders als Todo aber potenziell
    mehrere Ziel-Kalender (calendar_url), da der Nutzer Termine in getrennte
    Collections einsortiert (z.B. Privat/Arbeit/Urlaub) - Todo kennt nur eine
    Liste. Kein space_id, Termine sind persönlich/bereichsübergreifend."""

    __tablename__ = "calendar_events"

    id = Column(Integer, primary_key=True, index=True)
    uid = Column(String, nullable=False, unique=True, index=True)
    title = Column(String, nullable=False)
    start = Column(DateTime, nullable=False)
    end = Column(DateTime, nullable=True)
    location = Column(String, nullable=True)
    # Einmalig geokodiert (siehe main._geocode_missing_event_locations), damit
    # die Fahrzeit-Berechnung im Digest nicht bei jedem Lauf neu bei Nominatim
    # anfragen muss - NULL, solange die Adresse noch nicht (erfolgreich)
    # geokodiert wurde oder kein Ort hinterlegt ist.
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    all_day = Column(Boolean, nullable=False, default=False)
    # Welche Kalender-Collection dieser Termin gehoert bzw. bekommen soll (bei
    # neu angelegten) - noetig, weil main.py mehrere Kalender-URLs gleichzeitig
    # synct (siehe radicale_sync.sync_calendar), anders als bei Todo mit nur
    # einer Liste muss klar sein, WOHIN ein neuer Termin gepusht wird.
    calendar_url = Column(String, nullable=True)
    href = Column(String, nullable=True)
    etag = Column(String, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced_at = Column(DateTime, nullable=True)
    pending_delete = Column(Boolean, nullable=False, default=False)
    # Einmalig True, sobald main._scheduled_travel_reminder rechtzeitig vor
    # diesem Termin per Telegram zum Losfahren aufgefordert hat - verhindert
    # eine Dauerschleife von Erinnerungen fuer denselben Termin.
    travel_reminder_sent = Column(Boolean, nullable=False, default=False)
    # Rohe RRULE-Zeile (RFC5545) des Master-Termins, falls von Radicale
    # geliefert - None fuer Einzeltermine. Wird nur gelesen/expandiert
    # (siehe radicale_sync.expand_rrule), nicht in Kies selbst erzeugt -
    # das Anlegen wiederkehrender Serien bleibt Aufgabe des Telefon-Clients.
    rrule = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ContractReminder(Base):
    """Kündigungsfrist-Erinnerung für ein erkanntes Abo (siehe
    crud.detect_recurring_transactions). Bewusst eine eigene, schlanke Tabelle
    statt Erweiterung der Buchungen: die Erkennung selbst bleibt eine reine
    Live-Berechnung ohne Identität über die Zeit, hier braucht es aber eine
    stabile Zuordnung (account_id + normalisierte Bezeichnung), an der eine
    vom Nutzer gepflegte Frist/ein Verlängerungsdatum hängen bleibt.

    `renewal_date` rückt automatisch weiter, sobald sie in der Vergangenheit
    liegt und eine Frequenz hinterlegt ist (siehe crud.evaluate_contract_reminders)
    - jährliche/monatliche Verträge müssen so nicht jedes Mal von Hand neu
    gepflegt werden. `last_reminded_for` verhindert, dieselbe Frist mehrfach
    zu melden (Muster wie Settings.last_cashflow_alert_date)."""

    __tablename__ = "contract_reminders"

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    description_key = Column(String, nullable=False)
    label = Column(String, nullable=False)
    notice_period_days = Column(Integer, nullable=False)
    renewal_date = Column(Date, nullable=False)
    auto_advance_frequency = Column(String, nullable=True)
    last_reminded_for = Column(Date, nullable=True)
    # Freitext-Notiz ("eigentlich kündigen", ein Link zum Kündigungsformular,
    # ...) und eine einfache Ja/Nein-Markierung, die die Zeile in der Abo-
    # Übersicht hervorhebt - beides rein informativ, löst nichts automatisch aus.
    notes = Column(Text, nullable=True)
    should_cancel = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("account_id", "description_key", name="uq_contract_reminder_account_desc"),
    )


class IgnoredRecurringPayment(Base):
    """Markiert eine von crud.detect_recurring_transactions erkannte Gruppe
    (account_id + normalisierte Bezeichnung) als Fehlerkennung, die nicht mehr
    in der Abo-Übersicht/Cashflow-Prognose/Überschneidungs-Erkennung auftauchen
    soll. Wie bei ContractReminder gibt es dafür keine eigene Identität in den
    Buchungen selbst - die Erkennung bleibt eine reine Live-Berechnung, hier
    wird nur pro (Konto, Bezeichnung) ein dauerhafter Ausschluss vermerkt.
    `label` ist rein zur Anzeige in der "Ignoriert"-Liste hinterlegt."""

    __tablename__ = "ignored_recurring_payments"

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    description_key = Column(String, nullable=False)
    label = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("account_id", "description_key", name="uq_ignored_recurring_account_desc"),
    )


class ReturnDeadline(Base):
    """Rückgabefrist zu einer einzelnen Buchung (z.B. "auf Probe" gekauft,
    kostenlose Rückgabe nur innerhalb von N Tagen). Bewusst manuell pro Buchung
    gesetzt statt automatisch erkannt - welcher Kauf überhaupt ein Rückgaberecht
    hat und wie lang die Frist ist, kann eine KI nicht zuverlässig aus der
    Buchung allein ableiten (Nutzerwunsch, nach Rückfrage bestätigt).

    `start_date` ist bewusst frei editierbar statt fest an Transaction.date
    gekoppelt - die Frist beginnt bei einer Lieferung oft erst mit Erhalt der
    Ware, nicht mit dem Buchungsdatum. `reminded` ist ein einmaliger Schalter
    (anders als bei ContractReminder gibt es hier keinen wiederkehrenden
    Termin, der zurückgesetzt werden müsste)."""

    __tablename__ = "return_deadlines"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False, unique=True)
    start_date = Column(Date, nullable=False)
    deadline_days = Column(Integer, nullable=False)
    remind_days_before = Column(Integer, nullable=False, default=3)
    reminded = Column(Boolean, nullable=False, default=False)
    returned = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class NetWorthSnapshot(Base):
    """Eine taegliche Momentaufnahme des Nettovermoegens - einzige Quelle fuer
    eine ECHTE Vermoegens-Verlaufskurve. Vorher konnte net_worth() nur den
    aktuellen Stand liefern, keine Historie; die Hub-Sparklines und der
    Jahresrueckblick haben deshalb bewusst auf eine Vermoegenskurve verzichtet
    statt sie aus Buchungen zu erraten. Ein taeglicher Job (siehe main.py)
    schreibt ab jetzt einen Eintrag pro Tag und Bereich - es gibt keine
    rueckwirkende Rekonstruktion, die Historie waechst also erst ab dem
    Einfuehrungsdatum."""

    __tablename__ = "net_worth_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    date = Column(Date, nullable=False)
    accounts_total = Column(Float, nullable=False)
    investments_total = Column(Float, nullable=False)
    debts_total = Column(Float, nullable=False)
    total = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("space_id", "date", name="uq_net_worth_snapshot_space_date"),
    )


class BusinessProject(Base):
    """Ein Nebenprojekt/Geschäft außerhalb der eigentlichen Finanzverwaltung
    (z.B. ein Roblox-Spiel, ein Shop, Kundenservice für ein bestimmtes
    Produkt) - Kies hat dafür keinen direkten Datenzugriff (keine Roblox-API,
    kein Kundensystem angebunden), kann also nicht selbst prüfen, ob dort
    etwas schiefläuft. Was es stattdessen leistet: offene Punkte (siehe
    BusinessIssue) an einem Ort sammeln, statt dass sie zwischen Kopf/Notizen/
    Chats verloren gehen, und per check_interval_days aktiv nachfragen, wenn
    länger nichts eingetragen/bestätigt wurde - eine Art Sekretariat, keine
    automatische Fehlererkennung. Kein space_id, das ist bereichsübergreifend
    persönlich wie Todo/CalendarEvent."""

    __tablename__ = "business_projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    # None = keine automatische Erinnerung, nur die offenen Punkte selbst zaehlen.
    check_interval_days = Column(Integer, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    last_reminded_date = Column(Date, nullable=True)
    # Optionale Verknuepfung zu einem bestehenden Konto - macht sichtbar, was
    # das Nebenprojekt tatsaechlich einbringt (z.B. Roblox-Auszahlungen laufen
    # auf einem PayPal-Konto auf). Bewusst ein ganzes Konto statt einer
    # Kategorie: die App hat schon das Konzept "geschaeftliches Konto" fuer
    # genau diesen Zweck, eine weitere Kategorie-Zuordnung waere doppelt.
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("Account")


class BusinessIssue(Base):
    """Ein offener Punkt/Vorfall zu einem BusinessProject - "beim Roblox-Spiel
    X funktioniert die Zahlung nicht" statt einer verlorenen Chat-Nachricht.
    Wird typischerweise per Telegram-Freitext angelegt (siehe telegram_bot.
    _execute_action, Aktionstyp create_business_issue) und dort auch wieder
    abgehakt."""

    __tablename__ = "business_issues"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("business_projects.id"), nullable=False)
    title = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
    resolved = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    project = relationship("BusinessProject")


class LifeArea(Base):
    """Ein persönlicher Lebensbereich außerhalb der Finanzen (Fitness/Körper,
    Auftreten/Kommunikation, ...) - bewusst getrennt von den finanziellen
    Zielen (models.Goal), weil hier keine automatisch messbare Kennzahl
    dahintersteckt, sondern eine selbst eingeschätzte Fortschrittsangabe plus
    ein lockeres Tagebuch aus Check-ins (siehe LifeCheckIn). check_interval_
    days/last_checked_at/last_reminded_date funktionieren wie bei
    BusinessProject - Nutzerwunsch nach aktivem Nachhaken statt nur
    passivem Anzeigen ("strenger Vater"-Prinzip: nicht vom Kurs abkommen)."""

    __tablename__ = "life_areas"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    target_date = Column(Date, nullable=True)
    progress_percent = Column(Integer, nullable=True)
    check_interval_days = Column(Integer, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    last_reminded_date = Column(Date, nullable=True)
    # Optionales Wochenraster-Ziel (z.B. "3x/Woche") fuer ein festes Habit-
    # Tracking-Muster statt nur des lockeren Tagebuchs - None heisst weiterhin
    # freies Tagebuch ohne festes Ziel (rein additiv, kein Zwang).
    target_days_per_week = Column(Integer, nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class LifeCheckIn(Base):
    """Ein Tagebuch-Eintrag zu einem LifeArea - "heute 5km gelaufen", "bewusst
    langsamer gesprochen heute". Reine Notiz, kein "erledigt/offen"-Zustand
    wie bei BusinessIssue, da es hier nicht um abzuarbeitende Punkte geht,
    sondern um einen fortlaufenden Verlauf."""

    __tablename__ = "life_checkins"

    id = Column(Integer, primary_key=True, index=True)
    area_id = Column(Integer, ForeignKey("life_areas.id"), nullable=False)
    note = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    area = relationship("LifeArea")


class TimeEntry(Base):
    """Ein Zeit-Eintrag für ein Nebenprojekt (siehe BusinessProject) - bewusst
    sehr schlank: Start/Stop ODER direkte manuelle Eingabe von Minuten, keine
    Unterprojekte/Tags/Abrechnung. `stopped_at=None` heißt "läuft gerade" -
    es kann höchstens einen laufenden Eintrag pro Projekt geben (siehe
    main.start_time_entry), sonst würde die Summe pro Projekt doppelt zählen."""

    __tablename__ = "time_entries"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("business_projects.id"), nullable=False)
    note = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=False)
    stopped_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("BusinessProject")


class Contact(Base):
    """Leichtes Adressbuch ("People/CRM-Light") - ein Kontakt mit optionaler
    Notiz und dem Datum der letzten Interaktion, bewusst ohne Firmen/Deals/
    Pipelines o.ä. wie ein echtes CRM. `last_interaction_at` wird ausschließlich
    manuell gesetzt (siehe main.touch_contact) - anders als bei BusinessProject/
    LifeArea gibt es hier keine automatische Erinnerung, das wäre für ein
    reines Adressbuch zu aufdringlich."""

    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
    last_interaction_at = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class MediaStatus(str, enum.Enum):
    offen = "offen"
    laeuft = "läuft"
    fertig = "fertig"
    abgebrochen = "abgebrochen"


class MediaItem(Base):
    """Leseliste/Medien-Tracking - Bücher, Artikel, Videos etc. mit einem
    einfachen Status statt eines vollen Bewertungs-/Rezensions-Systems.
    Optional an ein Ziel oder Projekt gehängt (lose, ohne Foreign-Key-Zwang -
    dieselbe entity_type/entity_id-Idee wie bei Note, hier aber nur EIN
    optionales Ziel statt vieler, deshalb kein eigenes generisches System)."""

    __tablename__ = "media_items"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    media_type = Column(String, nullable=False, default="buch")
    status = Column(Enum(MediaStatus), nullable=False, default=MediaStatus.offen)
    url = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    linked_goal_id = Column(Integer, ForeignKey("goals.id"), nullable=True)
    linked_project_id = Column(Integer, ForeignKey("business_projects.id"), nullable=True)
    finished_at = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    linked_goal = relationship("Goal")
    linked_project = relationship("BusinessProject")


class HealthMetricType(str, enum.Enum):
    gewicht = "gewicht"
    schlaf = "schlaf"


class HealthMetric(Base):
    """Sehr minimaler Gesundheits-Verlauf (Gewicht in kg, Schlaf in Stunden) -
    bewusst nur ein Zahlenwert pro Eintrag und Tag, kein Ernährungstagebuch,
    keine Trainingspläne. Fügt sich als weitere Kennzahl neben LifeCheckIn in
    die bestehenden Lebensbereiche ein, ohne eine eigene Health-App nachzubauen.
    Ein Eintrag pro (Typ, Tag) - ein zweiter Eintrag am selben Tag überschreibt
    (siehe main.create_health_metric), damit die Verlaufskurve nicht durch
    mehrfache Tageseinträge verzerrt wird."""

    __tablename__ = "health_metrics"

    id = Column(Integer, primary_key=True, index=True)
    metric_type = Column(Enum(HealthMetricType), nullable=False)
    date = Column(Date, nullable=False)
    value = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("metric_type", "date", name="uq_health_metric_type_date"),
    )


class WishlistItem(Base):
    """Ein Wunsch (Flug, Produkt, ...), den der Nutzer kaufen will, sobald er
    günstig ist - "jeder hat dieselben 24 Stunden", das manuelle Nachschauen
    soll Kies abnehmen. Zwei Ebenen, die unabhängig voneinander funktionieren:
    1) check_interval_days/last_checked_at/last_reminded_date - zuverlässige
       Erinnerung, selbst nachzuschauen (wie bei BusinessProject/LifeArea).
    2) auto_check_enabled - EXPERIMENTELL: main._scheduled_wishlist_auto_check
       nutzt die ohnehin vorhandene Brave-Suche + Ollama, um einzuschätzen, ob
       gerade ein Deal vorliegt. Keine echten Preisdaten (keine Flug-/Preis-
       API angebunden, dafür gibt's keine freie/generische Lösung) - kann
       Deals verpassen oder fälschlich Alarm schlagen. Bewusst standardmäßig
       AUS (nutzerentscheidung erst beim Anlegen), jede Meldung sagt klar
       dazu, dass es eine KI-Einschätzung ist, kein verifizierter Preis."""

    __tablename__ = "wishlist_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=True)
    target_price = Column(Float, nullable=True)
    url = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    check_interval_days = Column(Integer, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    last_reminded_date = Column(Date, nullable=True)
    auto_check_enabled = Column(Boolean, nullable=False, default=False)
    last_auto_check_at = Column(DateTime, nullable=True)
    purchased = Column(Boolean, nullable=False, default=False)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class CategorySuggestionStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"


class CategorySuggestion(Base):
    """Wartende KI-Kategorisierungsvorschläge - ai_auto.auto_categorize wendet
    einen Vorschlag nur automatisch an, wenn die KI-Konfidenz über
    CONFIDENCE_THRESHOLD liegt (siehe dortigen Docstring); alles darunter
    landete bisher als "skipped" im Nichts, ohne dass der Nutzer die
    Einschätzung der KI je zu sehen bekam, selbst wenn sie oft richtig lag.
    Diese Tabelle macht daraus eine echte Warteschlange zum manuellen
    Bestätigen/Ablehnen statt eines stillen Verwerfens.

    Kein Update bestehender Zeilen bei einem erneuten Lauf mit derselben
    (Transaction, Kategorie)-Kombination - ein zweiter Vorschlag mit
    UNIQUE-Konflikt wird beim Anlegen übersprungen (siehe
    ai_auto._apply_confidence_suggestions), damit ein einmal abgelehnter
    Vorschlag nicht beim nächsten stündlichen Lauf kommentarlos wieder
    auftaucht. Ein GEÄNDERTER Vorschlag (andere Kategorie) ist dagegen eine
    neue Zeile, kein Update - bewusst kein Verlust der Ablehnungshistorie."""

    __tablename__ = "category_suggestions"
    __table_args__ = (
        UniqueConstraint("transaction_id", "suggested_category_id", name="uq_category_suggestion_tx_cat"),
    )

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    suggested_category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    confidence = Column(Float, nullable=False)
    status = Column(Enum(CategorySuggestionStatus), nullable=False, default=CategorySuggestionStatus.pending)
    created_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)

    transaction = relationship("Transaction")
    suggested_category = relationship("Category")


class AssistantSuggestionStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    snoozed = "snoozed"


class AssistantSuggestion(Base):
    """Generische Warteschlange für proaktive Jarvis-Vorschläge, die eine
    Bestätigung brauchen (siehe main._scheduled_suggestion_check,
    telegram_bot._handle_suggestion_reply) - bewusst NICHT category_suggestions
    wiederverwendet: das dortige Schema ist fest an (Transaction, Kategorie)
    gebunden, hier braucht es beliebige Vorschlagsarten (aktuell nur
    "todo_no_date", weitere `kind`-Werte können später dazukommen, ohne
    Schema-Änderung). Gleiches Grundprinzip wie category_suggestions:
    UNIQUE(kind, ref_id) verhindert, dass ein einmal entschiedener Vorschlag
    beim nächsten Lauf kommentarlos wieder auftaucht - "snoozed" ist die
    einzige Ausnahme, die nach snoozed_until absichtlich erneut auftaucht
    (siehe _scheduled_suggestion_check).

    Verdoppelt zugleich als schlanke "Was Jarvis getan hat"-Aktivitätsspur
    (Punkt J der Spezifikation) - kein separates Log-System nötig, Status +
    Zeitstempel dieser Tabelle reichen für eine Anzeige der letzten Einträge."""

    __tablename__ = "assistant_suggestions"
    __table_args__ = (
        UniqueConstraint("kind", "ref_id", name="uq_assistant_suggestion_kind_ref"),
    )

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String, nullable=False)
    ref_id = Column(Integer, nullable=True)
    title = Column(String, nullable=False)
    status = Column(Enum(AssistantSuggestionStatus), nullable=False, default=AssistantSuggestionStatus.pending)
    created_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)
    snoozed_until = Column(Date, nullable=True)


class Routine(Base):
    """Wiederkehrende Jarvis-Checkliste (Spezifikation Abschnitt G) - bewusst
    schlank: nur Wochentage + eine feste Uhrzeit, keine vollen Kalender-RRULEs
    wie bei CalendarEvent (dafür gibt es den echten Kalender). Checklist-Items
    als einfache, newline-getrennte Textliste statt einer eigenen Tabelle -
    bei typischerweise wenigen kurzen Einträgen (siehe Nutzerbeispiele:
    Wochenrückblick-Vorbereitung, Müll, Fitness) unnötiger Aufwand, eine
    eigene Item-Tabelle mit fester Reihenfolge zu pflegen.

    Nutzerseitig frei benannt und befüllt, keine hardcodierten Rituale -
    reine Infrastruktur."""

    __tablename__ = "routines"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    # Komma-getrennt, z.B. "mon,wed,fri" (python date.strftime("%a").lower()-
    # kompatible Kürzel: mon/tue/wed/thu/fri/sat/sun).
    weekdays = Column(String, nullable=False)
    hour = Column(Integer, nullable=False, default=9)
    minute = Column(Integer, nullable=False, default=0)
    items_text = Column(Text, nullable=False)  # ein Item pro Zeile
    active = Column(Boolean, nullable=False, default=True)
    # Verhindert Mehrfachversand am selben Tag (Muster wie Settings.
    # last_cashflow_alert_date) - der Scheduler prüft alle 15 Minuten, ohne
    # das würde ein Routine-Fenster von mehreren Prüfläufen mehrfach treffen.
    last_sent_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class RoutineRun(Base):
    """Der heutige Abhak-Stand einer Routine (siehe models.Routine) - eine
    Zeile pro (Routine, Datum), erst bei der ersten Interaktion angelegt
    (nicht schon beim Versand). checked_items als JSON-Liste der abgehakten
    Item-TEXTE (nicht Indizes) - robust gegen eine spätere Änderung der
    Item-Liste in Routine.items_text, ein Index würde dann auf ein anderes
    Item zeigen."""

    __tablename__ = "routine_runs"
    __table_args__ = (UniqueConstraint("routine_id", "date", name="uq_routine_run_date"),)

    id = Column(Integer, primary_key=True, index=True)
    routine_id = Column(Integer, ForeignKey("routines.id"), nullable=False)
    date = Column(Date, nullable=False, default=date.today)
    checked_items_json = Column(Text, nullable=False, default="[]")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    routine = relationship("Routine")


class Note(Base):
    """Freie, durchsuchbare Notiz, die an ein beliebiges anderes Objekt gehängt
    ist (Ziel, To-Do, Business-Projekt, den Schweiz-Tab, ...) - bewusst EINE
    generische Tabelle statt eines eigenen Notizfelds pro Modell: die Objekte,
    an denen Notizen sinnvoll sind, kommen laufend dazu (Nutzerwunsch nennt
    fünf verschiedene), ein Notizfeld pro Modell würde bei jedem neuen Ort
    eine Migration brauchen UND ließe sich nicht gemeinsam durchsuchen.

    `entity_type` + `entity_id` sind bewusst ein loser Verweis ohne Foreign
    Key (kein Objekt, an dem Notizen hängen sollen, hat eine gemeinsame
    Basistabelle) - beim Laden filtert das Frontend/Backend gezielt nach
    diesem Paar. Für Objekte ohne echte ID (Schweiz-Tab als Ganzes) wird
    `entity_id=0` als feste Konvention verwendet, analog zur einzigen Space
    dieser App.

    KEIN Ersatz für Transaction.notes/ContractReminder.notes/BusinessIssue.notes
    - dort ist die Notiz Teil des fachlichen Datensatzes selbst (ein einzelnes
    Feld reicht), hier geht es um ein offenes Tagebuch mit mehreren Einträgen
    über die Zeit."""

    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String, nullable=False, index=True)
    entity_id = Column(Integer, nullable=False, index=True)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SyncTombstone(Base):
    """Lösch-Protokoll für den Offline-Sync des nativen Clients - fast alle
    Löschungen in dieser App sind Hard Deletes (siehe crud.py), ohne dieses
    Protokoll wäre eine Löschung für einen zweiten Client zwischen zwei
    Sync-Läufen unsichtbar. Wird ausschließlich automatisch über den
    SQLAlchemy-Session-Event in sync_tombstones.py befüllt, nie manuell."""

    __tablename__ = "sync_tombstones"

    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String, nullable=False, index=True)
    entity_id = Column(Integer, nullable=False)
    space_id = Column(Integer, nullable=True, index=True)
    deleted_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

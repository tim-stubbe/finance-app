import Foundation
import GRDB

/// Kleine, wiederverwendbare Abfragen über die geteilte lokale Datenbank -
/// reine Lesehilfen (keine Business-Logik, die von main.py abweichen dürfte),
/// analog zu crud.account_balance/day_balance im Backend. In KiesCore statt
/// direkt in einer View, damit sowohl die iOS- als auch eine spätere
/// erweiterte macOS-Oberfläche dieselbe Berechnung nutzen.
public enum Queries {
    /// Saldo = Startsaldo + Summe aller Buchungen dieses Kontos (wie
    /// crud.account_balance im Backend - Umbuchungen zählen mit, weil sie
    /// echte Bewegungen auf DIESEM Konto sind, auch wenn sie backend-seitig
    /// nicht als Einnahme/Ausgabe gezählt werden).
    public static func accountBalance(_ db: Database, accountID: Int64) throws -> Double {
        guard let account = try Account.fetchOne(db, key: accountID) else { return 0 }
        let sum = try Double.fetchOne(
            db, sql: "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_id = ?",
            arguments: [accountID]
        ) ?? 0
        return account.initial_balance + sum
    }

    /// Einnahmen/Ausgaben des heutigen Tages (lokales Datum) - grobe
    /// Tagesbilanz für die "Heute"-Ansicht, ohne Umbuchungen (is_transfer)
    /// mitzuzählen, analog zur Web-App.
    public static func todayBalance(_ db: Database) throws -> (income: Double, expense: Double) {
        let today = DateFormatter.isoDate.string(from: Date())
        let income = try Double.fetchOne(
            db, sql: """
                SELECT COALESCE(SUM(amount), 0) FROM transactions
                WHERE date = ? AND amount > 0 AND is_transfer = 0
                """, arguments: [today]
        ) ?? 0
        let expense = try Double.fetchOne(
            db, sql: """
                SELECT COALESCE(SUM(amount), 0) FROM transactions
                WHERE date = ? AND amount < 0 AND is_transfer = 0
                """, arguments: [today]
        ) ?? 0
        return (income, expense)
    }

    /// Offene Ziele mit nahem Zieldatum (oder ganz ohne Datum, ans Ende
    /// sortiert) - fuer die "Heute"-Ansicht. Kein numerischer Fortschritt
    /// verfuegbar (progress_percent/GoalProgress sind serverseitig berechnet,
    /// nicht Teil der hier synchronisierten Rohspalten, siehe Models.swift).
    public static func goalsNearTarget(_ db: Database, limit: Int = 5) throws -> [Goal] {
        try Goal
            .filter(Column("status") == "open")
            .order(sql: "target_date IS NULL, target_date ASC")
            .limit(limit)
            .fetchAll(db)
    }

    /// Kündigungsfristen, deren Kündigungsstichtag (renewal_date -
    /// notice_period_days) innerhalb der nächsten `withinDays` Tage liegt.
    public static func contractRemindersDueSoon(_ db: Database, withinDays: Int = 30) throws -> [ContractReminder] {
        try ContractReminder.fetchAll(db, sql: """
            SELECT * FROM contract_reminders
            WHERE date(renewal_date, '-' || notice_period_days || ' days') <= date('now', ? )
            ORDER BY renewal_date
            """, arguments: ["+\(withinDays) days"])
    }

    /// Noch nicht zurückgegebene Rückgabefristen (start_date + deadline_days),
    /// die innerhalb der nächsten `withinDays` Tage ablaufen.
    public static func returnDeadlinesDueSoon(_ db: Database, withinDays: Int = 14) throws -> [ReturnDeadline] {
        try ReturnDeadline.fetchAll(db, sql: """
            SELECT * FROM return_deadlines
            WHERE returned = 0 AND date(start_date, '+' || deadline_days || ' days') <= date('now', ? )
            ORDER BY start_date
            """, arguments: ["+\(withinDays) days"])
    }

    /// Alle Positionen, nach Namen sortiert.
    public static func allHoldings(_ db: Database) throws -> [Holding] {
        try Holding.order(Column("name")).fetchAll(db)
    }

    /// Aktive, noch nicht gekaufte Wünsche.
    public static func openWishlistItems(_ db: Database) throws -> [WishlistItem] {
        try WishlistItem
            .filter(Column("active") == true && Column("purchased") == false)
            .order(Column("name"))
            .fetchAll(db)
    }

    /// Aktive Lebensbereiche, zu denen heute noch kein Check-in vorliegt.
    public static func lifeAreasWithoutCheckinToday(_ db: Database) throws -> [LifeArea] {
        let today = DateFormatter.isoDate.string(from: Date())
        let checkedInAreaIDs = try Int64.fetchSet(db, sql: """
            SELECT DISTINCT area_id FROM life_checkins WHERE substr(created_at, 1, 10) = ?
            """, arguments: [today])
        let areas = try LifeArea.filter(Column("active") == true).order(Column("name")).fetchAll(db)
        return areas.filter { !checkedInAreaIDs.contains($0.id) }
    }

    /// Nächster anstehender Termin (start in der Zukunft), fürs Widget - siehe
    /// TodayView.reload() für dieselbe Grundabfrage inkl. Formatierung.
    public static func nextUpcomingEvent(_ db: Database) throws -> CalendarEvent? {
        let now = ISO8601DateFormatter().string(from: Date())
        return try CalendarEvent
            .filter(Column("start") >= now)
            .order(Column("start"))
            .fetchOne(db)
    }

    /// Nächstes fälliges (oder terminloses) offenes Todo, fürs Widget - grobe
    /// Sortierung wie in TodosView (kein due_date landet zuletzt).
    public static func nextOpenTodo(_ db: Database) throws -> Todo? {
        try Todo
            .filter(Column("done") == false)
            .order(sql: "due_date IS NULL, due_date ASC")
            .fetchOne(db)
    }

    /// Ein einzelnes Suchergebnis über alle lokal vorhandenen Entitäten hinweg
    /// - für SearchView (native iOS-Suche, siehe dort). `tabKey` ist bewusst
    /// ein roher String statt eines Enums: KiesCore ist plattformneutral (auch
    /// macOS/KiesCLI), das iOS-spezifische Tab-Konzept (siehe TabRouter/AppTab
    /// in KiesiOS) gehört nicht hierher - SearchView mappt den String per
    /// `AppTab(rawValue:)` zurück. Die Werte entsprechen absichtlich AppTabs
    /// rawValues. Die App hat aktuell keine Detail-Screens für einzelne
    /// Zeilen, "richtigen Tab öffnen" ist der bestehende Detailgrad überall
    /// sonst in der App.
    public struct SearchResult: Identifiable {
        public var id: String { "\(kind)-\(entityID)" }
        public let kind: String       // deutsches Label fürs Gruppieren, z.B. "Buchung"
        public let icon: String       // SF-Symbol-Name
        public let title: String
        public let subtitle: String?
        public let tabKey: String
        public let entityID: Int64
    }

    /// Durchsucht alle lokal gespeicherten, textsuchbaren Entitäten per
    /// LIKE-Vergleich (case-insensitive über COLLATE NOCASE, wie SQLite es für
    /// ASCII ohnehin automatisch macht) - kein FTS5-Index nötig bei der hier
    /// üblichen Datenmenge eines Einzelnutzers, analog zur Begründung in
    /// backend/app/main.py für die Web-Suche. `limitPerKind` hält die Liste
    /// übersichtlich, ähnlich limit_per_type bei GET /search der Web-App.
    public static func globalSearch(_ db: Database, query: String, limitPerKind: Int = 8) throws -> [SearchResult] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard q.count >= 2 else { return [] }
        let like = "%\(q)%"
        var results: [SearchResult] = []

        let accounts = try Account.filter(Column("name").like(like)).limit(limitPerKind).fetchAll(db)
        results += accounts.map { SearchResult(kind: "Konto", icon: "banknote", title: $0.name, subtitle: $0.type, tabKey: "accounts", entityID: $0.id) }

        let transactions = try TransactionRecord
            .filter(Column("description").like(like) || Column("notes").like(like))
            .order(Column("date").desc)
            .limit(limitPerKind)
            .fetchAll(db)
        results += transactions.map {
            SearchResult(kind: "Buchung", icon: "list.bullet.rectangle", title: $0.description ?? "Ohne Beschreibung",
                         subtitle: "\($0.date) · \(String(format: "%.2f", $0.amount))", tabKey: "transactions", entityID: $0.id)
        }

        let todos = try Todo.filter(Column("title").like(like)).limit(limitPerKind).fetchAll(db)
        results += todos.map { SearchResult(kind: "Todo", icon: "checklist", title: $0.title, subtitle: $0.due_date, tabKey: "todos", entityID: $0.id) }

        let goals = try Goal
            .filter(Column("title").like(like) || Column("description").like(like))
            .limit(limitPerKind)
            .fetchAll(db)
        results += goals.map { SearchResult(kind: "Ziel", icon: "target", title: $0.title, subtitle: $0.category, tabKey: "goals", entityID: $0.id) }

        let events = try CalendarEvent
            .filter(Column("title").like(like) || Column("location").like(like))
            .order(Column("start"))
            .limit(limitPerKind)
            .fetchAll(db)
        results += events.map { SearchResult(kind: "Termin", icon: "calendar", title: $0.title, subtitle: $0.location, tabKey: "today", entityID: $0.id) }

        let wishes = try WishlistItem.filter(Column("name").like(like)).limit(limitPerKind).fetchAll(db)
        results += wishes.map { SearchResult(kind: "Wunsch", icon: "heart", title: $0.name, subtitle: $0.category, tabKey: "wishlist", entityID: $0.id) }

        let lifeAreas = try LifeArea
            .filter(Column("name").like(like) || Column("description").like(like))
            .limit(limitPerKind)
            .fetchAll(db)
        results += lifeAreas.map { SearchResult(kind: "Lebensbereich", icon: "heart.text.square", title: $0.name, subtitle: $0.description, tabKey: "life", entityID: $0.id) }

        let categories = try Category.filter(Column("name").like(like)).limit(limitPerKind).fetchAll(db)
        results += categories.map { SearchResult(kind: "Kategorie", icon: "tag", title: $0.name, subtitle: $0.type, tabKey: "categories", entityID: $0.id) }

        let holdings = try Holding
            .filter(Column("name").like(like) || Column("symbol").like(like))
            .limit(limitPerKind)
            .fetchAll(db)
        results += holdings.map { SearchResult(kind: "Investment", icon: "chart.line.uptrend.xyaxis", title: $0.name, subtitle: $0.symbol, tabKey: "investments", entityID: $0.id) }

        return results
    }
}

extension DateFormatter {
    /// "yyyy-MM-dd" im lokalen Kalender - passend zum Format, in dem
    /// Transaction.date vom Server ankommt (siehe backend/app/models.py:
    /// `date = Column(Date, ...)`, JSON-serialisiert als ISO-Datum).
    public static let isoDate: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.locale = Locale(identifier: "en_US_POSIX")
        return f
    }()

    /// Parst CalendarEvent.start/end - kommt vom Server als naives
    /// `datetime.isoformat()` (siehe backend/app/sync.py: `_serialize_row`),
    /// also ohne Zeitzone und mit Mikrosekunden nur, wenn sie ungleich null
    /// sind ("2026-08-27T14:00:00" bzw. "2026-08-27T14:00:00.123456").
    /// Zwei Formatter statt einem, weil DateFormatter keine optionalen
    /// Sekundenbruchteile kann - erst ohne versuchen, dann mit.
    private static let isoDateTimeNoFraction: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        f.locale = Locale(identifier: "en_US_POSIX")
        return f
    }()
    private static let isoDateTimeWithFraction: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"
        f.locale = Locale(identifier: "en_US_POSIX")
        return f
    }()
    public static func parseServerDateTime(_ value: String) -> Date? {
        isoDateTimeNoFraction.date(from: value) ?? isoDateTimeWithFraction.date(from: value)
    }

    /// Anzeige für Termine in der "Heute"-Übersicht - Wochentag+Datum+Zeit
    /// statt des rohen ISO-Strings (siehe TodayView.eventSubtitle).
    public static let eventDisplay: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "EEE, d.M. HH:mm"
        f.locale = Locale(identifier: "de_DE")
        return f
    }()
}

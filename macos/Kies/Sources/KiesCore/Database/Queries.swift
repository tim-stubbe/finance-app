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
}

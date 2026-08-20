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

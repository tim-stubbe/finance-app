import Foundation
import GRDB

/// Modelle für die erste vertikale Scheibe. Eigenschaften heißen bewusst wie
/// die Server-Spalten (snake_case), nicht idiomatisch camelCase - vermeidet
/// jedes Mapping-Risiko zwischen JSON/DB/Swift in diesem ersten Durchgang,
/// den ich (anders als bei der Web-App) nicht mit einer Testsuite absichern
/// kann. `public`, weil Kies (GUI) und KiesCLI (Test-Tool) beide gegen
/// KiesCore als eigenes Modul bauen.

public struct Space: Codable, FetchableRecord, PersistableRecord {
    public static let databaseTableName = "spaces"
    public var id: Int64
    public var name: String
    public var icon: String
    public var created_at: String?
    public var updated_at: String?
}

public struct Account: Codable, FetchableRecord, PersistableRecord, Identifiable {
    public static let databaseTableName = "accounts"
    public var id: Int64
    public var name: String
    public var type: String
    public var initial_balance: Double
    public var is_business: Bool
    public var space_id: Int64
    public var created_at: String?
    public var updated_at: String?
}

public struct Category: Codable, FetchableRecord, PersistableRecord, Identifiable {
    public static let databaseTableName = "categories"
    public var id: Int64
    public var name: String
    public var type: String
    public var parent_id: Int64?
    public var updated_at: String?
}

// "Transaction" kollidiert mit SwiftUI.Transaction (Animations-Kontext) -
// deshalb TransactionRecord statt des naheliegenderen Namens.
public struct TransactionRecord: Codable, FetchableRecord, PersistableRecord, Identifiable {
    public static let databaseTableName = "transactions"
    public var id: Int64
    public var date: String
    public var amount: Double
    public var description: String?
    public var notes: String?
    public var account_id: Int64
    public var category_id: Int64?
    public var is_transfer: Bool
    public var created_at: String?
    public var updated_at: String?
    public var pending_client_id: String?
}

public struct Todo: Codable, FetchableRecord, PersistableRecord, Identifiable {
    public static let databaseTableName = "todos"
    public var id: Int64
    public var uid: String?
    public var title: String
    public var done: Bool
    public var due_date: String?
    public var created_at: String?
    public var updated_at: String?
    public var pending_client_id: String?
}

/// Termin, pull-only (siehe AppDatabase-Migration v2_calendarEvents) - für
/// die "Heute"-Ansicht der iOS-App. Kein pending_client_id, weil diese erste
/// Scheibe keine Termine lokal anlegt.
public struct CalendarEvent: Codable, FetchableRecord, PersistableRecord, Identifiable {
    public static let databaseTableName = "calendar_events"
    public var id: Int64
    public var uid: String?
    public var title: String
    public var start: String
    public var end: String?
    public var location: String?
    public var all_day: Bool
    public var created_at: String?
    public var updated_at: String?
}

/// Ziel, pull-only in dieser Scheibe (keine Anlage/Bearbeitung in der iOS-App -
/// server-seitig deutlich reichhaltiger, siehe AppDatabase-Migration
/// v3_goalsAndLife-Kommentar zur bewussten Spaltenauswahl).
public struct Goal: Codable, FetchableRecord, PersistableRecord, Identifiable {
    public static let databaseTableName = "goals"
    public var id: Int64
    public var space_id: Int64?
    public var title: String
    public var description: String?
    public var category: String?
    public var goal_type: String
    public var target_date: String?
    public var status: String
    public var created_at: String?
    public var updated_at: String?
}

/// Lebensbereich, pull-only (kein Anlegen/Bearbeiten in der iOS-App, nur
/// Check-ins darauf, siehe LifeCheckIn) - progress_percent/streak/Heatmap sind
/// serverseitig berechnete Werte, keine echten Spalten (siehe Migration).
public struct LifeArea: Codable, FetchableRecord, PersistableRecord, Identifiable {
    public static let databaseTableName = "life_areas"
    public var id: Int64
    public var name: String
    public var description: String?
    public var target_date: String?
    public var check_interval_days: Int64?
    public var target_days_per_week: Int64?
    public var active: Bool
    public var created_at: String?
    public var updated_at: String?
}

/// Check-in-Eintrag zu einem LifeArea - create-only (server hat kein
/// update/delete_fn dafuer, siehe sync_registry.py), pending_client_id analog
/// zu Todo/Transaction fuer den Offline-Anlege-Fall.
public struct LifeCheckIn: Codable, FetchableRecord, PersistableRecord, Identifiable {
    public static let databaseTableName = "life_checkins"
    public var id: Int64
    public var area_id: Int64
    public var note: String
    public var created_at: String?
    public var updated_at: String?
    public var pending_client_id: String?
}

/// Lokal-only: Sync-Cursor (Singleton-Zeile, id fest auf 1).
public struct SyncState: Codable, FetchableRecord, PersistableRecord {
    public static let databaseTableName = "sync_state"
    public var id: Int64 = 1
    public var cursor: String?
}

/// Lokal-only: ausstehende Schreibvorgänge, die per Push an den Server gehen,
/// sobald wieder eine Verbindung besteht.
public struct SyncOutboxEntry: Codable, FetchableRecord, PersistableRecord, Identifiable {
    public static let databaseTableName = "sync_outbox"
    public var id: Int64?
    public var entity_type: String
    public var op: String  // "create" | "update" | "delete"
    public var client_id: String?
    public var server_id: Int64?
    public var base_updated_at: String?
    public var data_json: String
    public var created_at: String

    public mutating func didInsert(_ inserted: InsertionSuccess) {
        id = inserted.rowID
    }
}

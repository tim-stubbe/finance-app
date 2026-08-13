import Foundation
import GRDB

/// Modelle für die erste vertikale Scheibe. Eigenschaften heißen bewusst wie
/// die Server-Spalten (snake_case), nicht idiomatisch camelCase - vermeidet
/// jedes Mapping-Risiko zwischen JSON/DB/Swift in diesem ersten Durchgang,
/// den ich (anders als bei der Web-App) nicht mit einer Testsuite absichern
/// kann.

struct Space: Codable, FetchableRecord, PersistableRecord {
    static let databaseTableName = "spaces"
    var id: Int64
    var name: String
    var icon: String
    var created_at: String?
    var updated_at: String?
}

struct Account: Codable, FetchableRecord, PersistableRecord, Identifiable {
    static let databaseTableName = "accounts"
    var id: Int64
    var name: String
    var type: String
    var initial_balance: Double
    var is_business: Bool
    var space_id: Int64
    var created_at: String?
    var updated_at: String?
}

struct Category: Codable, FetchableRecord, PersistableRecord, Identifiable {
    static let databaseTableName = "categories"
    var id: Int64
    var name: String
    var type: String
    var parent_id: Int64?
    var updated_at: String?
}

// "Transaction" kollidiert mit SwiftUI.Transaction (Animations-Kontext) -
// deshalb TransactionRecord statt des naheliegenderen Namens.
struct TransactionRecord: Codable, FetchableRecord, PersistableRecord, Identifiable {
    static let databaseTableName = "transactions"
    var id: Int64
    var date: String
    var amount: Double
    var description: String?
    var notes: String?
    var account_id: Int64
    var category_id: Int64?
    var is_transfer: Bool
    var created_at: String?
    var updated_at: String?
    var pending_client_id: String?
}

struct Todo: Codable, FetchableRecord, PersistableRecord, Identifiable {
    static let databaseTableName = "todos"
    var id: Int64
    var uid: String?
    var title: String
    var done: Bool
    var due_date: String?
    var created_at: String?
    var updated_at: String?
    var pending_client_id: String?
}

/// Lokal-only: Sync-Cursor (Singleton-Zeile, id fest auf 1).
struct SyncState: Codable, FetchableRecord, PersistableRecord {
    static let databaseTableName = "sync_state"
    var id: Int64 = 1
    var cursor: String?
}

/// Lokal-only: ausstehende Schreibvorgänge, die per Push an den Server gehen,
/// sobald wieder eine Verbindung besteht.
struct SyncOutboxEntry: Codable, FetchableRecord, PersistableRecord, Identifiable {
    static let databaseTableName = "sync_outbox"
    var id: Int64?
    var entity_type: String
    var op: String  // "create" | "update" | "delete"
    var client_id: String?
    var server_id: Int64?
    var base_updated_at: String?
    var data_json: String
    var created_at: String

    mutating func didInsert(_ inserted: InsertionSuccess) {
        id = inserted.rowID
    }
}

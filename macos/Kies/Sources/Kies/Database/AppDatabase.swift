import Foundation
import GRDB

/// Lokaler Speicher für die erste vertikale Scheibe (Konten/Buchungen/Todos) -
/// GRDB statt Core Data, weil das additive Migrations-Muster hier (jede
/// Version fügt nur Spalten/Tabellen hinzu, nie ein Reset) genau dem
/// `ensure_columns`-Stil des Backends entspricht (siehe backend/app/database.py).
enum AppDatabase {
    static let shared = try! makeShared()

    static func makeShared() throws -> DatabaseQueue {
        let appSupport = try FileManager.default.url(
            for: .applicationSupportDirectory, in: .userDomainMask,
            appropriateFor: nil, create: true
        )
        let dir = appSupport.appendingPathComponent("Kies", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let dbURL = dir.appendingPathComponent("kies.sqlite")
        let dbQueue = try DatabaseQueue(path: dbURL.path)
        try migrator.migrate(dbQueue)
        return dbQueue
    }

    static var migrator: DatabaseMigrator {
        var migrator = DatabaseMigrator()

        migrator.registerMigration("v1_syncedTables") { db in
            try db.create(table: "spaces") { t in
                t.column("id", .integer).primaryKey()
                t.column("name", .text).notNull()
                t.column("icon", .text).notNull()
                t.column("created_at", .text)
                t.column("updated_at", .text)
            }
            try db.create(table: "accounts") { t in
                t.column("id", .integer).primaryKey()
                t.column("name", .text).notNull()
                t.column("type", .text).notNull()
                t.column("initial_balance", .double).notNull().defaults(to: 0)
                t.column("is_business", .boolean).notNull().defaults(to: false)
                t.column("space_id", .integer).notNull()
                t.column("created_at", .text)
                t.column("updated_at", .text)
            }
            try db.create(table: "categories") { t in
                t.column("id", .integer).primaryKey()
                t.column("name", .text).notNull()
                t.column("type", .text).notNull()
                t.column("parent_id", .integer)
                t.column("updated_at", .text)
            }
            // pending_client_id: gesetzt, solange die Zeile offline angelegt
            // und noch nicht vom Server bestaetigt wurde - die "id" ist dann
            // ein lokaler Platzhalter (siehe SyncEngine.localPlaceholderID).
            try db.create(table: "transactions") { t in
                t.column("id", .integer).primaryKey()
                t.column("date", .text).notNull()
                t.column("amount", .double).notNull()
                t.column("description", .text)
                t.column("notes", .text)
                t.column("account_id", .integer).notNull()
                t.column("category_id", .integer)
                t.column("is_transfer", .boolean).notNull().defaults(to: false)
                t.column("created_at", .text)
                t.column("updated_at", .text)
                t.column("pending_client_id", .text)
            }
            try db.create(table: "todos") { t in
                t.column("id", .integer).primaryKey()
                t.column("uid", .text)
                t.column("title", .text).notNull()
                t.column("done", .boolean).notNull().defaults(to: false)
                t.column("due_date", .text)
                t.column("created_at", .text)
                t.column("updated_at", .text)
                t.column("pending_client_id", .text)
            }

            // --- lokal-only: Sync-Zustand ---
            try db.create(table: "sync_state") { t in
                t.column("id", .integer).primaryKey().check { $0 == 1 }
                t.column("cursor", .text)
            }
            try db.create(table: "sync_outbox") { t in
                t.column("id", .integer).primaryKey(autoincrement: true)
                t.column("entity_type", .text).notNull()
                t.column("op", .text).notNull()
                t.column("client_id", .text)
                t.column("server_id", .integer)
                t.column("base_updated_at", .text)
                t.column("data_json", .text).notNull()
                t.column("created_at", .text).notNull()
            }
        }

        return migrator
    }
}

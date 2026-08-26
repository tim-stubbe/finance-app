import Foundation
import GRDB

/// Lokaler Speicher für die erste vertikale Scheibe (Konten/Buchungen/Todos) -
/// GRDB statt Core Data, weil das additive Migrations-Muster hier (jede
/// Version fügt nur Spalten/Tabellen hinzu, nie ein Reset) genau dem
/// `ensure_columns`-Stil des Backends entspricht (siehe backend/app/database.py).
public enum AppDatabase {
    /// App-Group-ID für den gemeinsamen Container von KiesiOS, der Widget-
    /// Extension (KiesWidget) und der Share-Extension (KiesShare) - siehe
    /// project.yml (xcodegen) für die Entitlements. Ohne gemeinsamen
    /// Container sähe das Widget nie die Daten der App (jede App-Extension
    /// läuft in ihrem eigenen Sandbox-Prozess mit eigenem Application-
    /// Support-Verzeichnis).
    public static let appGroupID = "group.app.kies"

    public static let shared = try! makeShared()

    /// Ermittelt den DB-Pfad und migriert bei Bedarf einmalig von der alten
    /// (Vor-Widget-Ära) Application-Support-Lage in den App-Group-Container -
    /// reines Kopieren, nicht Verschieben, damit ein Fehlschlag beim ersten
    /// Start nach einem Update nie zu Datenverlust führt. Ist die App-Group
    /// nicht verfügbar (z.B. Kies/KiesCLI auf macOS ohne dieses Entitlement,
    /// oder ein Build ohne Code-Signing-Kontext), bleibt es wie bisher bei
    /// Application Support - funktional identisch, nur ohne Widget-Zugriff.
    static func resolveDatabaseURL() throws -> URL {
        let fm = FileManager.default
        let legacyDir = try fm.url(
            for: .applicationSupportDirectory, in: .userDomainMask,
            appropriateFor: nil, create: true
        ).appendingPathComponent("Kies", isDirectory: true)
        try fm.createDirectory(at: legacyDir, withIntermediateDirectories: true)
        let legacyURL = legacyDir.appendingPathComponent("kies.sqlite")

        // WICHTIG (live verifiziert, siehe Kommentar oben): containerURL(...)
        // liefert auch OHNE das Entitlement einen Pfad zurück statt nil (macOS
        // löst ihn rein syntaktisch auf) - erst der eigentliche Dateizugriff
        // scheitert dann mit "Operation not permitted". Ein simples
        // `guard let` reicht deshalb NICHT als Test, ob die App-Group wirklich
        // nutzbar ist; stattdessen den Verzeichnis-Zugriff selbst probieren
        // und bei jedem Fehler (nicht nur nil) auf den alten Pfad zurückfallen -
        // sonst stürzt z.B. KiesCLI/die macOS-App (kein App-Group-Entitlement)
        // beim Start hart ab.
        guard let groupContainer = fm.containerURL(forSecurityApplicationGroupIdentifier: appGroupID) else {
            return legacyURL
        }
        let groupDir = groupContainer.appendingPathComponent("Database", isDirectory: true)
        do {
            try fm.createDirectory(at: groupDir, withIntermediateDirectories: true)
        } catch {
            return legacyURL
        }
        let groupURL = groupDir.appendingPathComponent("kies.sqlite")

        if !fm.fileExists(atPath: groupURL.path), fm.fileExists(atPath: legacyURL.path) {
            do {
                try fm.copyItem(at: legacyURL, to: groupURL)
            } catch {
                return legacyURL
            }
            // SQLite-WAL/SHM-Begleitdateien gehören zur selben Datenbank -
            // fehlen sie beim Kopieren (z.B. sauber geschlossene DB ohne
            // offenes WAL), ist das kein Fehler, nur nichts zu kopieren.
            for suffix in ["-wal", "-shm"] {
                let src = URL(fileURLWithPath: legacyURL.path + suffix)
                let dst = URL(fileURLWithPath: groupURL.path + suffix)
                if fm.fileExists(atPath: src.path) {
                    try? fm.copyItem(at: src, to: dst)
                }
            }
        }
        return groupURL
    }

    static func makeShared() throws -> DatabaseQueue {
        let dbURL = try resolveDatabaseURL()
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

        // Neu für die iOS-"Heute"-Ansicht: heutige/nächste Termine. Pull-only
        // lokal (kein Anlegen/Bearbeiten von Terminen in dieser ersten iOS-
        // Scheibe) - server-seitig ist CalendarEvent längst voll sync-fähig
        // (siehe sync_registry.py), hier fehlte bisher nur die lokale Tabelle.
        // Bewusst nur die für die Anzeige nötigen Spalten, nicht 1:1 alle
        // Server-Spalten (z.B. href/etag/lat/lon fehlen) - applyRow liest
        // aus der Pull-Antwort ohnehin nur, was hier definiert ist.
        migrator.registerMigration("v2_calendarEvents") { db in
            try db.create(table: "calendar_events") { t in
                t.column("id", .integer).primaryKey()
                t.column("uid", .text)
                t.column("title", .text).notNull()
                t.column("start", .text).notNull()
                t.column("end", .text)
                t.column("location", .text)
                t.column("all_day", .boolean).notNull().defaults(to: false)
                t.column("created_at", .text)
                t.column("updated_at", .text)
            }
        }

        // Neu fuer die ausgebaute iOS-"Heute"-Ansicht + neue Tabs (Ziele/Leben):
        // Goal/LifeArea/LifeCheckIn sind serverseitig laengst in sync_registry.py
        // voll sync-faehig, hier fehlten bisher nur die lokalen Tabellen. Wie bei
        // CalendarEvent bewusst nur die fuer Anzeige/Check-in noetigen Spalten,
        // nicht 1:1 alle Server-Spalten - `progress_percent`/`streak_days`/
        // `checkin_days_30` bei LifeArea sind serverseitig vom Pydantic-Schema
        // bolted-on berechnete Werte, KEINE echten DB-Spalten (sync.py serialisiert
        // nur rohe Tabellenspalten), deshalb hier absichtlich nicht nachgebildet -
        // "ohne Check-in heute" wird stattdessen lokal aus life_checkins berechnet
        // (siehe Queries.lifeAreasWithoutCheckinToday).
        migrator.registerMigration("v3_goalsAndLife") { db in
            try db.create(table: "goals") { t in
                t.column("id", .integer).primaryKey()
                t.column("space_id", .integer)
                t.column("title", .text).notNull()
                t.column("description", .text)
                t.column("category", .text)
                t.column("goal_type", .text).notNull()
                t.column("target_date", .text)
                t.column("status", .text).notNull()
                t.column("created_at", .text)
                t.column("updated_at", .text)
            }
            try db.create(table: "life_areas") { t in
                t.column("id", .integer).primaryKey()
                t.column("name", .text).notNull()
                t.column("description", .text)
                t.column("target_date", .text)
                t.column("check_interval_days", .integer)
                t.column("target_days_per_week", .integer)
                t.column("active", .boolean).notNull().defaults(to: true)
                t.column("created_at", .text)
                t.column("updated_at", .text)
            }
            // LifeCheckIn ist serverseitig create-only (kein update/delete_fn,
            // reines Tagebuch, siehe sync_registry.py) - pending_client_id analog
            // zu Todo/Transaction fuer den Offline-Anlege-Fall.
            try db.create(table: "life_checkins") { t in
                t.column("id", .integer).primaryKey()
                t.column("area_id", .integer).notNull()
                t.column("note", .text).notNull()
                t.column("created_at", .text)
                t.column("updated_at", .text)
                t.column("pending_client_id", .text)
            }
        }

        // Naechste Ausbaustufe (siehe iOS-Ausbau-Zusammenfassung): Wunschliste
        // (lesend + "gekauft" markieren, deshalb WishlistItem push-faehig wie
        // Todo) sowie Fristen (Kuendigung/Ruecksendung) fuer die "Heute"-
        // Ansicht - beide serverseitig laengst in sync_registry.py registriert,
        // hier nur die lokalen Tabellen nachgezogen. ContractReminder/
        // ReturnDeadline bleiben bewusst pull-only (kein Anlegen/Bearbeiten
        // in dieser iOS-Scheibe, dafuer bleibt die Web-App der Ort).
        migrator.registerMigration("v4_wishlistAndDeadlines") { db in
            try db.create(table: "wishlist_items") { t in
                t.column("id", .integer).primaryKey()
                t.column("name", .text).notNull()
                t.column("category", .text)
                t.column("target_price", .double)
                t.column("url", .text)
                t.column("purchased", .boolean).notNull().defaults(to: false)
                t.column("active", .boolean).notNull().defaults(to: true)
                t.column("created_at", .text)
                t.column("updated_at", .text)
            }
            try db.create(table: "contract_reminders") { t in
                t.column("id", .integer).primaryKey()
                t.column("space_id", .integer)
                t.column("account_id", .integer)
                t.column("label", .text).notNull()
                t.column("notice_period_days", .integer).notNull()
                t.column("renewal_date", .text).notNull()
                t.column("created_at", .text)
                t.column("updated_at", .text)
            }
            try db.create(table: "return_deadlines") { t in
                t.column("id", .integer).primaryKey()
                t.column("transaction_id", .integer)
                t.column("start_date", .text).notNull()
                t.column("deadline_days", .integer).notNull()
                t.column("returned", .boolean).notNull().defaults(to: false)
                t.column("created_at", .text)
                t.column("updated_at", .text)
            }
        }

        // Investments, pull-only (kein Anlegen/Bearbeiten von Positionen/Lots
        // in dieser Scheibe - Kauf/Verkauf-Buchführung bleibt der Web-App
        // vorbehalten, hier nur Anzeige). asset_type/type sind serverseitig
        // str-Enums (siehe models.AssetType/LotType), hier bewusst als reiner
        // Text gespeichert statt eines Swift-Enums - vermeidet Absturz/Verlust
        // bei einem künftigen neuen Server-Wert, den der Client noch nicht kennt.
        migrator.registerMigration("v5_investments") { db in
            try db.create(table: "holdings") { t in
                t.column("id", .integer).primaryKey()
                t.column("space_id", .integer)
                t.column("asset_type", .text).notNull()
                t.column("name", .text).notNull()
                t.column("symbol", .text).notNull()
                t.column("sector", .text)
                t.column("currency", .text)
                t.column("quantity", .double).notNull().defaults(to: 0)
                t.column("purchase_price", .double).notNull().defaults(to: 0)
                t.column("current_price", .double)
                t.column("created_at", .text)
                t.column("updated_at", .text)
            }
            try db.create(table: "holding_lots") { t in
                t.column("id", .integer).primaryKey()
                t.column("holding_id", .integer).notNull()
                t.column("date", .text).notNull()
                t.column("type", .text).notNull()
                t.column("quantity", .double).notNull()
                t.column("price_per_unit", .double).notNull()
                t.column("created_at", .text)
                t.column("updated_at", .text)
            }
        }

        // Lokal-only: sichtbares Sync-Konflikt-Feedback (siehe SyncEngine.
        // pushOutbox) - vorher blieb ein Konflikt (Server hat denselben
        // Datensatz zwischenzeitlich auch geändert) stillschweigend in der
        // Outbox stehen und wurde bei jedem Sync erneut versucht, ohne dass
        // der Nutzer je davon erfuhr. Bewusst kein Merge/CRDT: pro Konflikt
        // wird hier nur festgehalten, was passiert ist (`reason`) und - falls
        // vom Server mitgeschickt (siehe backend/app/sync.py: "server_data"
        // bei reason=="server_newer") - roh dessen aktuelle Version, damit
        // der Nutzer bewusst "Server behalten" oder "meine Version erneut
        // versuchen" wählen kann (siehe SyncEngine.resolveConflict*).
        migrator.registerMigration("v6_syncConflicts") { db in
            try db.create(table: "sync_conflicts") { t in
                t.column("id", .integer).primaryKey(autoincrement: true)
                t.column("entity_type", .text).notNull()
                t.column("server_id", .integer)
                t.column("reason", .text).notNull()
                t.column("server_data_json", .text)
                t.column("detected_at", .text).notNull()
            }
        }

        return migrator
    }
}

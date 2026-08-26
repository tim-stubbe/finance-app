import Foundation
import GRDB

/// Orchestriert Pull -> Anwenden -> Push (Outbox) -> id_map auflösen ->
/// Cursor fortschreiben. Cursor wird NUR nach einem vollständig
/// erfolgreichen Push+Pull-Zyklus weitergeschoben (siehe run()), nie bei
/// Teilfehlern - sonst könnten unsynchronisierte lokale Änderungen beim
/// nächsten Pull verloren gehen (der Server würde sie nicht erneut senden).
@MainActor
public final class SyncEngine: ObservableObject {
    public static let shared = SyncEngine()

    @Published public var isSyncing = false
    @Published public var lastError: String?
    @Published public var lastSyncedAt: Date?
    /// Offen stehende Sync-Konflikte (siehe pushOutbox/resolveConflict*) -
    /// nach jedem Sync neu geladen, damit beide nativen Clients (iOS/macOS)
    /// ein Banner/eine Liste zeigen können, statt Konflikte stillschweigend
    /// endlos zu wiederholen.
    @Published public var conflicts: [SyncConflict] = []

    private let client = SyncClient()
    private let db = AppDatabase.shared

    // Nur diese Entitäten hat die erste vertikale Scheibe lokal - alle
    // anderen Server-Entitäten aus der Pull-Antwort werden ignoriert.
    private nonisolated static let localEntityTypes: Set<String> = [
        "Account", "Category", "Transaction", "Todo", "Space", "CalendarEvent",
        "Goal", "LifeArea", "LifeCheckIn",
        "WishlistItem", "ContractReminder", "ReturnDeadline",
        "Holding", "HoldingLot",
    ]

    public func run() async {
        guard PairingStore.shared.isPaired, !isSyncing else { return }
        isSyncing = true
        defer { isSyncing = false }
        do {
            try await pushOutbox()
            try await pullAndApply()
            lastError = nil
            lastSyncedAt = Date()
        } catch {
            lastError = "\(error)"
        }
        await loadConflicts()
    }

    /// Lädt die aktuell offenen Konflikte neu - separat von run() aufrufbar
    /// (z.B. beim Öffnen einer Konflikte-Ansicht), damit sie nicht erst
    /// einen vollen Sync-Zyklus abwarten muss.
    public func loadConflicts() async {
        conflicts = (try? await db.read { db in
            try SyncConflict.order(Column("detected_at").desc).fetchAll(db)
        }) ?? []
    }

    // MARK: - Pull

    private func pullAndApply() async throws {
        let cursor = try await db.read { db in try SyncState.fetchOne(db, key: 1)?.cursor }
        let response = try await client.pull(since: cursor)

        try await db.write { db in
            for (entityType, rows) in response.entities where Self.localEntityTypes.contains(entityType) {
                for row in rows {
                    try Self.applyRow(db, entityType: entityType, row: row)
                }
            }
            for tombstone in response.tombstones where Self.localEntityTypes.contains(tombstone.entity_type) {
                try Self.applyTombstone(db, tombstone: tombstone)
            }
            var state = try SyncState.fetchOne(db, key: 1) ?? SyncState(cursor: nil)
            state.cursor = response.server_time
            try state.save(db)
        }
    }

    private nonisolated static func applyRow(_ db: Database, entityType: String, row: [String: AnyCodable]) throws {
        guard let id = row["id"]?.int64Value else { return }
        switch entityType {
        case "Space":
            try Space(
                id: id, name: row["name"]?.stringValue ?? "", icon: row["icon"]?.stringValue ?? "",
                created_at: row["created_at"]?.stringValue, updated_at: row["updated_at"]?.stringValue
            ).save(db)
        case "Account":
            try Account(
                id: id, name: row["name"]?.stringValue ?? "", type: row["type"]?.stringValue ?? "",
                initial_balance: row["initial_balance"]?.doubleValue ?? 0,
                is_business: row["is_business"]?.boolValue ?? false,
                space_id: row["space_id"]?.int64Value ?? 0,
                created_at: row["created_at"]?.stringValue, updated_at: row["updated_at"]?.stringValue
            ).save(db)
        case "Category":
            try Category(
                id: id, name: row["name"]?.stringValue ?? "", type: row["type"]?.stringValue ?? "",
                parent_id: row["parent_id"]?.int64Value, updated_at: row["updated_at"]?.stringValue
            ).save(db)
        case "Transaction":
            try TransactionRecord(
                id: id, date: row["date"]?.stringValue ?? "", amount: row["amount"]?.doubleValue ?? 0,
                description: row["description"]?.stringValue, notes: row["notes"]?.stringValue,
                account_id: row["account_id"]?.int64Value ?? 0, category_id: row["category_id"]?.int64Value,
                is_transfer: row["is_transfer"]?.boolValue ?? false,
                created_at: row["created_at"]?.stringValue, updated_at: row["updated_at"]?.stringValue,
                pending_client_id: nil
            ).save(db)
        case "Todo":
            try Todo(
                id: id, uid: row["uid"]?.stringValue, title: row["title"]?.stringValue ?? "",
                done: row["done"]?.boolValue ?? false, due_date: row["due_date"]?.stringValue,
                created_at: row["created_at"]?.stringValue, updated_at: row["updated_at"]?.stringValue,
                pending_client_id: nil
            ).save(db)
        case "CalendarEvent":
            try CalendarEvent(
                id: id, uid: row["uid"]?.stringValue, title: row["title"]?.stringValue ?? "",
                start: row["start"]?.stringValue ?? "", end: row["end"]?.stringValue,
                location: row["location"]?.stringValue, all_day: row["all_day"]?.boolValue ?? false,
                created_at: row["created_at"]?.stringValue, updated_at: row["updated_at"]?.stringValue
            ).save(db)
        case "Goal":
            try Goal(
                id: id, space_id: row["space_id"]?.int64Value, title: row["title"]?.stringValue ?? "",
                description: row["description"]?.stringValue, category: row["category"]?.stringValue,
                goal_type: row["goal_type"]?.stringValue ?? "", target_date: row["target_date"]?.stringValue,
                status: row["status"]?.stringValue ?? "",
                created_at: row["created_at"]?.stringValue, updated_at: row["updated_at"]?.stringValue
            ).save(db)
        case "LifeArea":
            try LifeArea(
                id: id, name: row["name"]?.stringValue ?? "", description: row["description"]?.stringValue,
                target_date: row["target_date"]?.stringValue,
                check_interval_days: row["check_interval_days"]?.int64Value,
                target_days_per_week: row["target_days_per_week"]?.int64Value,
                active: row["active"]?.boolValue ?? true,
                created_at: row["created_at"]?.stringValue, updated_at: row["updated_at"]?.stringValue
            ).save(db)
        case "LifeCheckIn":
            try LifeCheckIn(
                id: id, area_id: row["area_id"]?.int64Value ?? 0, note: row["note"]?.stringValue ?? "",
                created_at: row["created_at"]?.stringValue, updated_at: row["updated_at"]?.stringValue,
                pending_client_id: nil
            ).save(db)
        case "WishlistItem":
            try WishlistItem(
                id: id, name: row["name"]?.stringValue ?? "", category: row["category"]?.stringValue,
                target_price: row["target_price"]?.doubleValue, url: row["url"]?.stringValue,
                purchased: row["purchased"]?.boolValue ?? false, active: row["active"]?.boolValue ?? true,
                created_at: row["created_at"]?.stringValue, updated_at: row["updated_at"]?.stringValue
            ).save(db)
        case "ContractReminder":
            try ContractReminder(
                id: id, space_id: row["space_id"]?.int64Value, account_id: row["account_id"]?.int64Value,
                label: row["label"]?.stringValue ?? "", notice_period_days: row["notice_period_days"]?.int64Value ?? 0,
                renewal_date: row["renewal_date"]?.stringValue ?? "",
                created_at: row["created_at"]?.stringValue, updated_at: row["updated_at"]?.stringValue
            ).save(db)
        case "ReturnDeadline":
            try ReturnDeadline(
                id: id, transaction_id: row["transaction_id"]?.int64Value,
                start_date: row["start_date"]?.stringValue ?? "", deadline_days: row["deadline_days"]?.int64Value ?? 0,
                returned: row["returned"]?.boolValue ?? false,
                created_at: row["created_at"]?.stringValue, updated_at: row["updated_at"]?.stringValue
            ).save(db)
        case "Holding":
            try Holding(
                id: id, space_id: row["space_id"]?.int64Value, asset_type: row["asset_type"]?.stringValue ?? "",
                name: row["name"]?.stringValue ?? "", symbol: row["symbol"]?.stringValue ?? "",
                sector: row["sector"]?.stringValue, currency: row["currency"]?.stringValue,
                quantity: row["quantity"]?.doubleValue ?? 0, purchase_price: row["purchase_price"]?.doubleValue ?? 0,
                current_price: row["current_price"]?.doubleValue,
                created_at: row["created_at"]?.stringValue, updated_at: row["updated_at"]?.stringValue
            ).save(db)
        case "HoldingLot":
            try HoldingLot(
                id: id, holding_id: row["holding_id"]?.int64Value ?? 0, date: row["date"]?.stringValue ?? "",
                type: row["type"]?.stringValue ?? "", quantity: row["quantity"]?.doubleValue ?? 0,
                price_per_unit: row["price_per_unit"]?.doubleValue ?? 0,
                created_at: row["created_at"]?.stringValue, updated_at: row["updated_at"]?.stringValue
            ).save(db)
        default:
            break
        }
    }

    private nonisolated static func applyTombstone(_ db: Database, tombstone: SyncPullResponse.Tombstone) throws {
        switch tombstone.entity_type {
        case "Space": try Space.deleteOne(db, key: tombstone.entity_id)
        case "Account": try Account.deleteOne(db, key: tombstone.entity_id)
        case "Category": try Category.deleteOne(db, key: tombstone.entity_id)
        case "Transaction": try TransactionRecord.deleteOne(db, key: tombstone.entity_id)
        case "Todo": try Todo.deleteOne(db, key: tombstone.entity_id)
        case "CalendarEvent": try CalendarEvent.deleteOne(db, key: tombstone.entity_id)
        case "Goal": try Goal.deleteOne(db, key: tombstone.entity_id)
        case "LifeArea": try LifeArea.deleteOne(db, key: tombstone.entity_id)
        case "LifeCheckIn": try LifeCheckIn.deleteOne(db, key: tombstone.entity_id)
        case "WishlistItem": try WishlistItem.deleteOne(db, key: tombstone.entity_id)
        case "ContractReminder": try ContractReminder.deleteOne(db, key: tombstone.entity_id)
        case "ReturnDeadline": try ReturnDeadline.deleteOne(db, key: tombstone.entity_id)
        case "Holding": try Holding.deleteOne(db, key: tombstone.entity_id)
        case "HoldingLot": try HoldingLot.deleteOne(db, key: tombstone.entity_id)
        default: break
        }
    }

    // MARK: - Push

    private func pushOutbox() async throws {
        let entries = try await db.read { db in try SyncOutboxEntry.order(Column("id")).fetchAll(db) }
        guard !entries.isEmpty else { return }

        let ops: [[String: Any]] = entries.compactMap { entry in
            guard let data = try? JSONSerialization.jsonObject(with: Data(entry.data_json.utf8)) as? [String: Any] else {
                return nil
            }
            var op: [String: Any] = ["op": entry.op, "entity_type": entry.entity_type, "data": data]
            if let clientID = entry.client_id { op["client_id"] = clientID }
            if let serverID = entry.server_id { op["server_id"] = serverID }
            if let base = entry.base_updated_at { op["base_updated_at"] = base }
            return op
        }

        let response = try await client.push(ops: ops, spaceID: nil)

        try await db.write { db in
            // Temp-IDs auf echte Server-IDs migrieren (Delete+Reinsert, siehe
            // Models.swift-Kommentar: bewusst kein FK-Remapping über mehrere
            // Ebenen offline erzeugter Objekte in diesem ersten Durchgang).
            for (clientID, serverID) in response.id_map {
                try Self.migrateTempID(db, clientID: clientID, serverID: serverID)
            }
            // Erfolgreich übertragene Outbox-Einträge entfernen. Konflikte
            // bleiben in der Outbox stehen (werden beim nächsten Sync erneut
            // versucht, es sei denn der Nutzer löst sie über
            // resolveConflictKeepServer/-RetryMine auf) - zusätzlich als
            // SyncConflict-Zeile sichtbar gemacht statt sie nur stillschweigend
            // zu wiederholen (siehe Models.swift-Kommentar).
            let appliedIDs = Set(entries.compactMap { $0.id })
            let conflictedEntityIDs = Set(response.conflicts.compactMap { $0.server_id })
            for entry in entries {
                if let serverID = entry.server_id, conflictedEntityIDs.contains(serverID) { continue }
                if let id = entry.id, appliedIDs.contains(id) {
                    try SyncOutboxEntry.deleteOne(db, key: id)
                }
            }
            try Self.recordConflicts(db, conflicts: response.conflicts)
        }
    }

    /// Ersetzt den bisherigen SyncConflict-Eintrag für dieselbe (entity_type,
    /// server_id) durch den neuesten Stand statt Duplikate anzuhäufen - ein
    /// Konflikt, der bei jedem Sync erneut auftritt (Outbox-Eintrag noch
    /// nicht aufgelöst), soll nur einmal in der Liste stehen, mit dem
    /// aktuellsten `reason`/`server_data`.
    private nonisolated static func recordConflicts(_ db: Database, conflicts: [SyncPushResponse.ConflictEntry]) throws {
        guard !conflicts.isEmpty else { return }
        let now = ISO8601DateFormatter().string(from: Date())
        for c in conflicts {
            if let serverID = c.server_id {
                try SyncConflict
                    .filter(Column("entity_type") == c.entity_type && Column("server_id") == serverID)
                    .deleteAll(db)
            }
            var serverDataJSON: String?
            if let serverData = c.server_data, let encoded = try? JSONEncoder().encode(serverData) {
                serverDataJSON = String(data: encoded, encoding: .utf8)
            }
            var row = SyncConflict(
                id: nil, entity_type: c.entity_type, server_id: c.server_id, reason: c.reason,
                server_data_json: serverDataJSON, detected_at: now
            )
            try row.insert(db)
        }
    }

    // MARK: - Konflikte auflösen

    /// "Server behalten": übernimmt die vom Server mitgeschickte Version
    /// direkt in die lokale Tabelle (per applyRow, derselbe Weg wie ein
    /// normaler Pull) und verwirft die eigene(n) noch ausstehende(n)
    /// Outbox-Änderung(en) für diese Zeile - ist kein `server_data_json`
    /// vorhanden (z.B. bei einem reinen Validierungsfehler ohne
    /// "server_newer"), wird nur die Outbox-Änderung verworfen, ohne lokal
    /// etwas zu überschreiben (es gäbe nichts Neues zu übernehmen).
    public func resolveConflictKeepServer(_ conflict: SyncConflict) async throws {
        try await db.write { db in
            if let serverID = conflict.server_id {
                try SyncOutboxEntry
                    .filter(Column("entity_type") == conflict.entity_type && Column("server_id") == serverID)
                    .deleteAll(db)
            }
            if let json = conflict.server_data_json, let data = json.data(using: .utf8),
               let row = try? JSONDecoder().decode([String: AnyCodable].self, from: data) {
                try Self.applyRow(db, entityType: conflict.entity_type, row: row)
            }
            if let id = conflict.id {
                try SyncConflict.deleteOne(db, key: id)
            }
        }
        await loadConflicts()
    }

    /// "Meine Version erneut versuchen": löscht `base_updated_at` auf der/den
    /// betroffenen Outbox-Eintrag/-Einträgen, sodass der nächste Push die
    /// Server-Prüfung überspringt (siehe backend/app/sync.py: `if op.
    /// base_updated_at:`) und die eigene Version unbedingt durchsetzt - kein
    /// stiller Automatismus, sondern eine bewusste Nutzer-Entscheidung.
    public func resolveConflictRetryMine(_ conflict: SyncConflict) async throws {
        try await db.write { db in
            if let serverID = conflict.server_id {
                let entries = try SyncOutboxEntry
                    .filter(Column("entity_type") == conflict.entity_type && Column("server_id") == serverID)
                    .fetchAll(db)
                for var entry in entries {
                    entry.base_updated_at = nil
                    try entry.update(db)
                }
            }
            if let id = conflict.id {
                try SyncConflict.deleteOne(db, key: id)
            }
        }
        await loadConflicts()
    }

    private nonisolated static func migrateTempID(_ db: Database, clientID: String, serverID: Int64) throws {
        if var t = try TransactionRecord.filter(Column("pending_client_id") == clientID).fetchOne(db) {
            try TransactionRecord.deleteOne(db, key: t.id)
            t.id = serverID
            t.pending_client_id = nil
            try t.insert(db)
        }
        if var todo = try Todo.filter(Column("pending_client_id") == clientID).fetchOne(db) {
            try Todo.deleteOne(db, key: todo.id)
            todo.id = serverID
            todo.pending_client_id = nil
            try todo.insert(db)
        }
        if var checkin = try LifeCheckIn.filter(Column("pending_client_id") == clientID).fetchOne(db) {
            try LifeCheckIn.deleteOne(db, key: checkin.id)
            checkin.id = serverID
            checkin.pending_client_id = nil
            try checkin.insert(db)
        }
    }

    // MARK: - Lokale Schreib-Hilfsfunktionen (offline-fähig)

    /// Legt eine Buchung lokal an (Platzhalter-ID, negativ - Server-IDs sind
    /// immer positiv) und reiht sie in die Outbox ein.
    public func createTransactionOffline(accountID: Int64, date: String, amount: Double, description: String?) throws {
        try db.write { db in
            let clientID = UUID().uuidString
            let placeholderID = -Int64(Date().timeIntervalSince1970 * 1000)
            let tx = TransactionRecord(
                id: placeholderID, date: date, amount: amount, description: description, notes: nil,
                account_id: accountID, category_id: nil, is_transfer: false,
                created_at: ISO8601DateFormatter().string(from: Date()), updated_at: nil,
                pending_client_id: clientID
            )
            try tx.insert(db)

            let data: [String: Any] = ["account_id": accountID, "date": date, "amount": amount, "description": description as Any]
            let jsonData = try JSONSerialization.data(withJSONObject: data)
            let entry = SyncOutboxEntry(
                id: nil, entity_type: "Transaction", op: "create", client_id: clientID, server_id: nil,
                base_updated_at: nil, data_json: String(data: jsonData, encoding: .utf8)!,
                created_at: ISO8601DateFormatter().string(from: Date())
            )
            try entry.insert(db)
        }
    }

    /// Legt ein Todo lokal an (Platzhalter-ID) und reiht es in die Outbox ein.
    public func createTodoOffline(title: String, dueDate: String?) throws {
        try db.write { db in
            let clientID = UUID().uuidString
            let placeholderID = -Int64(Date().timeIntervalSince1970 * 1000)
            let todo = Todo(
                id: placeholderID, uid: nil, title: title, done: false, due_date: dueDate,
                created_at: ISO8601DateFormatter().string(from: Date()), updated_at: nil,
                pending_client_id: clientID
            )
            try todo.insert(db)
            let data: [String: Any] = ["title": title, "due_date": dueDate as Any]
            try Self.enqueueOutbox(db, entityType: "Todo", op: "create", clientID: clientID, serverID: nil, baseUpdatedAt: nil, data: data)
        }
    }

    /// Bearbeitet Betrag/Beschreibung einer bereits synchronisierten Buchung
    /// grob - analog zu setTodoDoneOffline (nur id > 0, kein Update auf eine
    /// noch ausstehende Outbox-Create-Operation).
    public func updateTransactionOffline(id: Int64, amount: Double, description: String?) throws {
        guard id > 0 else { return }
        try db.write { db in
            guard var tx = try TransactionRecord.fetchOne(db, key: id) else { return }
            let baseUpdatedAt = tx.updated_at
            tx.amount = amount
            tx.description = description
            try tx.save(db)
            let data: [String: Any] = ["amount": amount, "description": description as Any]
            try Self.enqueueOutbox(db, entityType: "Transaction", op: "update", clientID: nil, serverID: id, baseUpdatedAt: baseUpdatedAt, data: data)
        }
    }

    /// Hakt ein bereits synchronisiertes Todo ab/wieder auf - nur für Todos
    /// mit echter Server-ID (positive id), noch nicht synchronisierte (Pending)
    /// Todos werden bewusst nicht editierbar angeboten (siehe UI), das würde
    /// einen zweiten, komplizierteren Fall (Update auf eine noch ausstehende
    /// Outbox-Create-Operation) nötig machen.
    public func setTodoDoneOffline(id: Int64, done: Bool) throws {
        guard id > 0 else { return }
        try db.write { db in
            guard var todo = try Todo.fetchOne(db, key: id) else { return }
            let baseUpdatedAt = todo.updated_at
            todo.done = done
            try todo.save(db)
            let data: [String: Any] = ["done": done]
            try Self.enqueueOutbox(db, entityType: "Todo", op: "update", clientID: nil, serverID: id, baseUpdatedAt: baseUpdatedAt, data: data)
        }
    }

    /// Markiert einen Wunsch als (nicht mehr) gekauft - analog zu
    /// setTodoDoneOffline, nur fuer bereits synchronisierte Einträge (positive id).
    public func setWishlistPurchasedOffline(id: Int64, purchased: Bool) throws {
        guard id > 0 else { return }
        try db.write { db in
            guard var item = try WishlistItem.fetchOne(db, key: id) else { return }
            let baseUpdatedAt = item.updated_at
            item.purchased = purchased
            try item.save(db)
            let data: [String: Any] = ["purchased": purchased]
            try Self.enqueueOutbox(db, entityType: "WishlistItem", op: "update", clientID: nil, serverID: id, baseUpdatedAt: baseUpdatedAt, data: data)
        }
    }

    /// Benennt eine Kategorie um - analog zu setWishlistPurchasedOffline, nur
    /// der Name (kein Anlegen/Löschen/Typ-Ändern in dieser Scheibe, dafür
    /// bleibt die Web-App der Ort).
    public func renameCategoryOffline(id: Int64, name: String) throws {
        guard id > 0 else { return }
        try db.write { db in
            guard var category = try Category.fetchOne(db, key: id) else { return }
            let baseUpdatedAt = category.updated_at
            category.name = name
            try category.save(db)
            let data: [String: Any] = ["name": name]
            try Self.enqueueOutbox(db, entityType: "Category", op: "update", clientID: nil, serverID: id, baseUpdatedAt: baseUpdatedAt, data: data)
        }
    }

    /// Legt einen Check-in lokal an (Platzhalter-ID) und reiht ihn in die
    /// Outbox ein - analog zu createTodoOffline, LifeCheckIn ist serverseitig
    /// ebenfalls nur "create" (siehe sync_registry.py).
    public func createLifeCheckInOffline(areaID: Int64, note: String) throws {
        try db.write { db in
            let clientID = UUID().uuidString
            let placeholderID = -Int64(Date().timeIntervalSince1970 * 1000)
            let checkin = LifeCheckIn(
                id: placeholderID, area_id: areaID, note: note,
                created_at: ISO8601DateFormatter().string(from: Date()), updated_at: nil,
                pending_client_id: clientID
            )
            try checkin.insert(db)
            let data: [String: Any] = ["area_id": areaID, "note": note]
            try Self.enqueueOutbox(db, entityType: "LifeCheckIn", op: "create", clientID: clientID, serverID: nil, baseUpdatedAt: nil, data: data)
        }
    }

    /// Anzahl noch nicht übertragener Outbox-Einträge - für "X Änderungen
    /// warten auf Upload" in der Sync-Status-Anzeige.
    public func pendingOutboxCount() async -> Int {
        (try? await db.read { db in try SyncOutboxEntry.fetchCount(db) }) ?? 0
    }

    private nonisolated static func enqueueOutbox(
        _ db: Database, entityType: String, op: String, clientID: String?, serverID: Int64?,
        baseUpdatedAt: String?, data: [String: Any]
    ) throws {
        let jsonData = try JSONSerialization.data(withJSONObject: data)
        var entry = SyncOutboxEntry(
            id: nil, entity_type: entityType, op: op, client_id: clientID, server_id: serverID,
            base_updated_at: baseUpdatedAt, data_json: String(data: jsonData, encoding: .utf8)!,
            created_at: ISO8601DateFormatter().string(from: Date())
        )
        try entry.insert(db)
    }
}

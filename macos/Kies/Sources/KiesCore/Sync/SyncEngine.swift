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

    private let client = SyncClient()
    private let db = AppDatabase.shared

    // Nur diese Entitäten hat die erste vertikale Scheibe lokal - alle
    // anderen Server-Entitäten aus der Pull-Antwort werden ignoriert.
    private nonisolated static let localEntityTypes: Set<String> = ["Account", "Category", "Transaction", "Todo", "Space", "CalendarEvent"]

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
            // bleiben in der Outbox stehen (werden dem Nutzer nicht in
            // dieser ersten Scheibe angezeigt - bekannte Lücke, siehe Plan).
            let appliedIDs = Set(entries.compactMap { $0.id })
            let conflictedEntityIDs = Set(response.conflicts.compactMap { $0.server_id })
            for entry in entries {
                if let serverID = entry.server_id, conflictedEntityIDs.contains(serverID) { continue }
                if let id = entry.id, appliedIDs.contains(id) {
                    try SyncOutboxEntry.deleteOne(db, key: id)
                }
            }
        }
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

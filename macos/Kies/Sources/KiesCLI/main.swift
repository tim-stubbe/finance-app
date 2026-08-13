import Foundation
import KiesCore
import GRDB

/// Kommandozeilen-Testwerkzeug für die Sync-Engine - läuft OHNE
/// NSApplication/Fenster, deshalb unbetroffen von der App-Nap/Display-
/// Session-Drosselung, die die GUI-App (Kies) bei gesperrtem Bildschirm
/// erleidet. Nutzt dieselbe KiesCore-Bibliothek wie die GUI-App, testet
/// also den echten Sync-Code, nicht eine Kopie davon.
///
/// Aufruf: KIES_BASE_URL=... KIES_SYNC_SECRET=... .build/debug/KiesCLI pull
///         KIES_BASE_URL=... KIES_SYNC_SECRET=... .build/debug/KiesCLI create-tx <accountID>

guard await MainActor.run(body: { PairingStore.shared.isPaired }) else {
    print("KIES_BASE_URL und KIES_SYNC_SECRET müssen gesetzt sein.")
    exit(1)
}

func printAccounts() throws {
    let accounts = try AppDatabase.shared.read { db in try Account.fetchAll(db) }
    print("Konten (\(accounts.count)):")
    for a in accounts { print("  \(a.id)\t\(a.name)\t\(a.type)") }
}

func printTransactions() throws {
    let txs = try AppDatabase.shared.read { db in try TransactionRecord.order(Column("date").desc).fetchAll(db) }
    print("Buchungen (\(txs.count)):")
    for t in txs.prefix(10) {
        let pending = t.pending_client_id != nil ? " [PENDING]" : ""
        print("  \(t.id)\t\(t.date)\t\(t.amount)\t\(t.description ?? "-")\(pending)")
    }
}

func printOutbox() throws {
    let entries = try AppDatabase.shared.read { db in try SyncOutboxEntry.fetchAll(db) }
    print("Outbox (\(entries.count) ausstehend):")
    for e in entries { print("  \(e.id ?? -1)\t\(e.op)\t\(e.entity_type)\t\(e.client_id ?? "-")") }
}

let args = CommandLine.arguments
let command = args.count > 1 ? args[1] : "pull"

switch command {
case "pull":
    await SyncEngine.shared.run()
    let error = SyncEngine.shared.lastError
    print("Sync-Fehler: \(error ?? "keiner")")
    try? printAccounts()
    try? printTransactions()

case "create-tx":
    guard args.count > 2, let accountID = Int64(args[2]) else {
        print("Verwendung: create-tx <accountID>")
        exit(1)
    }
    do {
        try await MainActor.run {
            try SyncEngine.shared.createTransactionOffline(
                accountID: accountID, date: "2026-08-13", amount: -7.77,
                description: "__CLI_TEST_TX__"
            )
        }
        print("Lokal angelegt.")
        try printOutbox()
        await SyncEngine.shared.run()
        let error = SyncEngine.shared.lastError
        print("Sync-Fehler: \(error ?? "keiner")")
        try printOutbox()
        try printTransactions()
    } catch {
        print("Fehler: \(error)")
    }

default:
    print("Unbekannter Befehl: \(command)")
}

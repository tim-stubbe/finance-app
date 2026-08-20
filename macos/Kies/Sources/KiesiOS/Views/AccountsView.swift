import SwiftUI
import KiesCore
import GRDB

/// Kontenliste mit Saldo - anders als die (schlankere) macOS-Variante zeigt
/// diese Version direkt den Kontostand (Startsaldo + Summe aller Buchungen,
/// siehe Queries.accountBalance), weil das für eine mobile Kurzübersicht der
/// naheliegendste erste Blick ist.
struct AccountsView: View {
    @ObservedObject var engine = SyncEngine.shared
    @ObservedObject private var rows = Box<[(account: Account, balance: Double)]>([])

    var body: some View {
        List(rows.value, id: \.account.id) { row in
            HStack {
                VStack(alignment: .leading) {
                    Text(row.account.name).font(.headline)
                    Text(row.account.type).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Text(row.balance, format: .currency(code: "EUR"))
                    .foregroundStyle(row.balance < 0 ? Color.red : Color.primary)
                    .fontWeight(.medium)
            }
        }
        .navigationTitle("Konten")
        .toolbar { SyncStatusToolbarItem() }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
        .overlay {
            if rows.value.isEmpty {
                ContentUnavailableView("Noch keine Konten", systemImage: "banknote", description: Text("Wird beim nächsten Sync geladen."))
            }
        }
    }

    private func reload() {
        rows.value = (try? AppDatabase.shared.read { db in
            try Account.order(Column("name")).fetchAll(db).map { account in
                (account, try Queries.accountBalance(db, accountID: account.id))
            }
        }) ?? []
    }
}

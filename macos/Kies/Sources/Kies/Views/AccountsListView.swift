import SwiftUI
import GRDB

struct AccountsListView: View {
    @ObservedObject var engine = SyncEngine.shared
    @ObservedObject private var accounts = Box<[Account]>([])

    var body: some View {
        List(accounts.value) { account in
            VStack(alignment: .leading) {
                Text(account.name).font(.headline)
                Text(account.type).font(.caption).foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Konten")
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .toolbar {
            ToolbarItem {
                Button {
                    Task { await engine.run() }
                } label: {
                    if engine.isSyncing {
                        ProgressView().controlSize(.small)
                    } else {
                        Label("Sync", systemImage: "arrow.triangle.2.circlepath")
                    }
                }
                .disabled(engine.isSyncing)
            }
        }
    }

    private func reload() {
        accounts.value = (try? AppDatabase.shared.read { db in
            try Account.order(Column("name")).fetchAll(db)
        }) ?? []
    }
}

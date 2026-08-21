import SwiftUI
import GRDB
import KiesCore

/// Wunschliste: lesend + "gekauft" markieren (kein Anlegen/Bearbeiten von
/// Wünschen selbst - dafür bleibt die Web-App der Ort, siehe ROADMAP.md).
struct WishlistView: View {
    @ObservedObject var engine = SyncEngine.shared
    @ObservedObject private var items = Box<[WishlistItem]>([])

    var body: some View {
        List {
            if items.value.isEmpty {
                ContentUnavailableView("Nichts auf der Liste", systemImage: "heart", description: Text("Wird beim nächsten Sync geladen."))
            }
            ForEach(items.value) { item in
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(item.name).font(.headline)
                        if let category = item.category, !category.isEmpty {
                            Text(category).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    if let price = item.target_price {
                        Text(price, format: .currency(code: "EUR")).font(.subheadline)
                    }
                }
                .swipeActions(edge: .trailing) {
                    Button {
                        markPurchased(item)
                    } label: {
                        Label("Gekauft", systemImage: "checkmark")
                    }
                    .tint(.green)
                    .disabled(item.id < 0)
                }
            }
        }
        .navigationTitle("Wunschliste")
        .toolbar { SyncStatusToolbarItem() }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
    }

    private func reload() {
        items.value = (try? AppDatabase.shared.read { db in try Queries.openWishlistItems(db) }) ?? []
    }

    private func markPurchased(_ item: WishlistItem) {
        try? SyncEngine.shared.setWishlistPurchasedOffline(id: item.id, purchased: true)
        reload()
        Task { await SyncEngine.shared.run() }
    }
}

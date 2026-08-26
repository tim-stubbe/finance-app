import SwiftUI
import KiesCore
import GRDB

/// Wunschliste fürs macOS-Detail-Pane - macOS-Gegenstück zu
/// KiesiOS/Views/WishlistView.swift. Lesend + "gekauft" markieren, kein
/// Anlegen/Bearbeiten (dafür bleibt die Web-App der Ort).
struct WishlistListView: View {
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
                    Button {
                        markPurchased(item)
                    } label: {
                        Label("Gekauft", systemImage: "checkmark")
                    }
                    .disabled(item.id < 0)
                }
            }
        }
        .navigationTitle("Wunschliste")
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
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
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

import SwiftUI
import KiesCore
import GRDB

/// Investment-Positionen, rein lesend - analog zu
/// KiesiOS/Views/InvestmentsView.swift.
struct InvestmentsListView: View {
    @ObservedObject var engine = SyncEngine.shared
    @ObservedObject private var holdings = Box<[Holding]>([])

    var body: some View {
        List(holdings.value) { (holding: Holding) in
            HStack {
                VStack(alignment: .leading) {
                    Text(holding.name).font(.headline)
                    Text("\(holding.symbol) · \(holding.asset_type)").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                VStack(alignment: .trailing) {
                    Text(currentValue(holding), format: .currency(code: "EUR"))
                    if let gain = gainPercent(holding) {
                        Text(String(format: "%+.1f %%", gain))
                            .font(.caption)
                            .foregroundStyle(gain >= 0 ? .green : .red)
                    }
                }
            }
        }
        .navigationTitle("Investments")
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

    private func currentValue(_ h: Holding) -> Double {
        (h.current_price ?? h.purchase_price) * h.quantity
    }

    private func gainPercent(_ h: Holding) -> Double? {
        guard h.purchase_price > 0, let current = h.current_price else { return nil }
        return (current - h.purchase_price) / h.purchase_price * 100
    }

    private func reload() {
        holdings.value = (try? AppDatabase.shared.read { db in try Queries.allHoldings(db) }) ?? []
    }
}

import SwiftUI
import GRDB
import KiesCore

/// Investment-Positionen, rein lesend (kein Anlegen/Bearbeiten von
/// Positionen/Lots in dieser Scheibe, dafür bleibt die Web-App der Ort -
/// Kauf-/Verkauf-Buchführung ist zu komplex für diese Runde).
struct InvestmentsView: View {
    @ObservedObject var engine = SyncEngine.shared
    @ObservedObject private var holdings = Box<[Holding]>([])

    var body: some View {
        List {
            if holdings.value.isEmpty {
                ContentUnavailableView("Keine Positionen", systemImage: "chart.line.uptrend.xyaxis", description: Text("Wird beim nächsten Sync geladen."))
            }
            ForEach(holdings.value) { holding in
                VStack(alignment: .leading, spacing: 4) {
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
            }
        }
        .navigationTitle("Investments")
        .toolbar { SyncStatusToolbarItem() }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
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

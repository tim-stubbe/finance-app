import SwiftUI
import Charts
import GRDB
import KiesCore

/// Investments, rein lesend (Kauf-/Verkauf-Buchführung bleibt der Web-App
/// vorbehalten). Oben Depotwert + Gewinn als Kacheln und ein Ring der
/// Aufteilung nach Anlageart, darunter die Positionen als Karten.
struct InvestmentsView: View {
    @ObservedObject var engine = SyncEngine.shared
    @StateObject private var holdings = Box<[Holding]>([])
    @StateObject private var allocation = Box<[Queries.AllocationSlice]>([])
    @StateObject private var totals = Box(Queries.InvestmentTotals(value: 0, cost: 0))

    var body: some View {
        KScreen {
            if holdings.value.isEmpty {
                ContentUnavailableView("Keine Positionen", systemImage: "chart.line.uptrend.xyaxis",
                                       description: Text("Wird beim nächsten Sync geladen."))
                    .kCard()
            } else {
                HStack(spacing: KTheme.gap) {
                    KStatTile(label: "Depotwert", value: kEUR(totals.value.value))
                    KStatTile(
                        label: "Gewinn",
                        value: kEUR(totals.value.gain),
                        tint: totals.value.gain >= 0 ? KTheme.positive : KTheme.negative,
                        caption: String(format: "%+.1f %%", totals.value.gainPct)
                    )
                }

                if allocation.value.count > 1 {
                    KSection(title: "Aufteilung", systemImage: "chart.pie") {
                        HStack(alignment: .center, spacing: 16) {
                            Chart(Array(allocation.value.enumerated()), id: \.element.id) { idx, slice in
                                SectorMark(angle: .value("Wert", slice.value),
                                           innerRadius: .ratio(0.62),
                                           angularInset: 1.5)
                                    .cornerRadius(3)
                                    .foregroundStyle(KTheme.chartPalette[idx % KTheme.chartPalette.count])
                            }
                            .frame(width: 120, height: 120)

                            VStack(alignment: .leading, spacing: 6) {
                                ForEach(Array(allocation.value.enumerated()), id: \.element.id) { idx, slice in
                                    HStack(spacing: 6) {
                                        Circle()
                                            .fill(KTheme.chartPalette[idx % KTheme.chartPalette.count])
                                            .frame(width: 8, height: 8)
                                        Text(label(for: slice.label)).font(.caption)
                                        Spacer(minLength: 4)
                                        Text(kEUR(slice.value)).font(.caption).foregroundStyle(.secondary)
                                    }
                                }
                            }
                        }
                    }
                }

                KSection(title: "Positionen", systemImage: "list.bullet") {
                    VStack(spacing: 12) {
                        ForEach(holdings.value) { holding in
                            holdingRow(holding)
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

    private func holdingRow(_ h: Holding) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 1) {
                Text(h.name).font(.callout.weight(.medium))
                Text("\(h.symbol) · \(label(for: h.asset_type))")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 2) {
                Text(kEUR(currentValue(h), fraction: 2)).font(.callout.weight(.semibold))
                if let gain = gainPercent(h) {
                    Text(String(format: "%+.1f %%", gain))
                        .font(.caption2.weight(.semibold))
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background((gain >= 0 ? KTheme.positive : KTheme.negative).opacity(0.15),
                                   in: Capsule())
                        .foregroundStyle(gain >= 0 ? KTheme.positive : KTheme.negative)
                }
            }
        }
    }

    private func currentValue(_ h: Holding) -> Double { (h.current_price ?? h.purchase_price) * h.quantity }

    private func gainPercent(_ h: Holding) -> Double? {
        guard h.purchase_price > 0, let current = h.current_price else { return nil }
        return (current - h.purchase_price) / h.purchase_price * 100
    }

    private func label(for assetType: String) -> String {
        switch assetType.lowercased() {
        case "stock", "aktie": return "Aktie"
        case "etf": return "ETF"
        case "crypto", "krypto": return "Krypto"
        case "fund", "fonds": return "Fonds"
        case "bond", "anleihe": return "Anleihe"
        case "cash": return "Cash"
        default: return assetType.capitalized
        }
    }

    private func reload() {
        let db = AppDatabase.shared
        holdings.value = (try? db.read { db in try Queries.allHoldings(db) }) ?? []
        allocation.value = (try? db.read { db in try Queries.holdingsAllocation(db) }) ?? []
        totals.value = (try? db.read { db in try Queries.investmentTotals(db) }) ?? Queries.InvestmentTotals(value: 0, cost: 0)
    }
}

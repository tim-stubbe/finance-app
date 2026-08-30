import SwiftUI
import Charts
import GRDB
import KiesCore

/// Premium investment view: one portfolio hero, one allocation visualization,
/// then an open position list. No nested card grid.
struct PremiumInvestmentsView: View {
    @ObservedObject var engine = SyncEngine.shared
    @StateObject private var holdings = Box<[Holding]>([])
    @StateObject private var allocation = Box<[Queries.AllocationSlice]>([])
    @StateObject private var totals = Box(Queries.InvestmentTotals(value: 0, cost: 0))

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 26) {
                portfolioHero
                allocationSection
                positionsSection
            }
            .padding(.horizontal, 20)
            .padding(.top, 12)
            .padding(.bottom, 110)
        }
        .background(KColor.background.ignoresSafeArea())
        .scrollIndicators(.hidden)
        .navigationTitle("Investments")
        .toolbar { SyncStatusToolbarItem() }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
    }

    private var portfolioHero: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Depotwert")
                .font(.subheadline)
                .foregroundStyle(KColor.secondary)
            Text(kEUR(totals.value.value))
                .font(.system(size: 42, weight: .bold, design: .rounded).monospacedDigit())
                .foregroundStyle(KColor.primary)

            HStack(spacing: 8) {
                Text("Gewinn")
                    .foregroundStyle(KColor.secondary)
                Text(kEUR(totals.value.gain))
                    .fontWeight(.semibold)
                    .foregroundStyle(totals.value.gain >= 0 ? KColor.positive : KColor.negative)
                Text(String(format: "%+.1f %%", totals.value.gainPct))
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background((totals.value.gain >= 0 ? KColor.positive : KColor.negative).opacity(0.12), in: Capsule())
                    .foregroundStyle(totals.value.gain >= 0 ? KColor.positive : KColor.negative)
            }
        }
    }

    @ViewBuilder
    private var allocationSection: some View {
        if !allocation.value.isEmpty {
            VStack(alignment: .leading, spacing: 14) {
                Text("Portfolio")
                    .font(.headline)
                    .foregroundStyle(KColor.primary)

                HStack(spacing: 22) {
                    Chart(Array(allocation.value.enumerated()), id: \.element.id) { index, slice in
                        SectorMark(angle: .value("Wert", slice.value), innerRadius: .ratio(0.66), angularInset: 2)
                            .cornerRadius(3)
                            .foregroundStyle(KColor.chartPalette[index % KColor.chartPalette.count])
                    }
                    .frame(width: 132, height: 132)

                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(Array(allocation.value.enumerated()), id: \.element.id) { index, slice in
                            HStack(spacing: 8) {
                                Circle()
                                    .fill(KColor.chartPalette[index % KColor.chartPalette.count])
                                    .frame(width: 8, height: 8)
                                Text(label(for: slice.label))
                                    .font(.subheadline)
                                    .foregroundStyle(KColor.primary)
                                Spacer(minLength: 6)
                                Text(kEUR(slice.value))
                                    .font(.subheadline.monospacedDigit())
                                    .foregroundStyle(KColor.secondary)
                            }
                        }
                    }
                }
            }
        }
    }

    private var positionsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Positionen")
                .font(.headline)
                .foregroundStyle(KColor.primary)

            VStack(spacing: 0) {
                ForEach(holdings.value) { holding in
                    HStack(spacing: 12) {
                        Image(systemName: assetIcon(holding.asset_type))
                            .font(.caption)
                            .foregroundStyle(KColor.accent)
                            .frame(width: 34, height: 34)
                            .background(KColor.accent.opacity(0.10), in: RoundedRectangle(cornerRadius: 10, style: .continuous))

                        VStack(alignment: .leading, spacing: 2) {
                            Text(holding.name)
                                .font(.body.weight(.medium))
                                .foregroundStyle(KColor.primary)
                                .lineLimit(1)
                            Text("\(holding.symbol) · \(label(for: holding.asset_type))")
                                .font(.caption)
                                .foregroundStyle(KColor.secondary)
                        }
                        Spacer(minLength: 8)
                        VStack(alignment: .trailing, spacing: 4) {
                            Text(kEUR(currentValue(holding), fraction: 2))
                                .font(.subheadline.weight(.semibold).monospacedDigit())
                                .foregroundStyle(KColor.primary)
                            if let gain = gainPercent(holding) {
                                Text(String(format: "%+.1f %%", gain))
                                    .font(.caption2.weight(.semibold))
                                    .foregroundStyle(gain >= 0 ? KColor.positive : KColor.negative)
                            }
                        }
                    }
                    .padding(.vertical, 12)
                    if holding.id != holdings.value.last?.id {
                        Divider().overlay(KColor.divider)
                    }
                }
            }
        }
    }

    private func currentValue(_ h: Holding) -> Double { (h.current_price ?? h.purchase_price) * h.quantity }
    private func gainPercent(_ h: Holding) -> Double? {
        guard h.purchase_price > 0, let current = h.current_price else { return nil }
        return (current - h.purchase_price) / h.purchase_price * 100
    }
    private func label(for type: String) -> String {
        switch type.lowercased() {
        case "stock", "aktie": return "Aktie"
        case "etf": return "ETF"
        case "crypto", "krypto": return "Krypto"
        case "fund", "fonds": return "Fonds"
        case "bond", "anleihe": return "Anleihe"
        case "cash": return "Cash"
        default: return type.capitalized
        }
    }
    private func assetIcon(_ type: String) -> String {
        switch type.lowercased() {
        case "crypto", "krypto": return "bitcoinsign.circle"
        case "etf", "fund", "fonds": return "chart.pie"
        default: return "chart.line.uptrend.xyaxis"
        }
    }
    private func reload() {
        let db = AppDatabase.shared
        holdings.value = (try? db.read { try Queries.allHoldings($0) }) ?? []
        allocation.value = (try? db.read { try Queries.holdingsAllocation($0) }) ?? []
        totals.value = (try? db.read { try Queries.investmentTotals($0) }) ?? Queries.InvestmentTotals(value: 0, cost: 0)
    }
}

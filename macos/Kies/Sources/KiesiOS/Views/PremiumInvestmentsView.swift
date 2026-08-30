import SwiftUI
import Charts
import GRDB
import KiesCore

/// Premium portfolio screen: a focused wealth header, interactive allocation,
/// compact performance controls and an uncluttered positions feed.
struct PremiumInvestmentsView: View {
    @ObservedObject private var engine = SyncEngine.shared
    @StateObject private var holdings = Box<[Holding]>([])
    @StateObject private var allocation = Box<[Queries.AllocationSlice]>([])
    @StateObject private var totals = Box(Queries.InvestmentTotals(value: 0, cost: 0))
    @State private var selectedAllocation: String?
    @State private var selectedPeriod = "1M"

    private let periods = ["1W", "1M", "3M", "1J"]

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(alignment: .leading, spacing: 28) {
                portfolioHeader
                performancePlaceholder
                allocationSection
                positionsSection
            }
            .padding(.horizontal, 20)
            .padding(.top, 12)
            .padding(.bottom, 110)
        }
        .background(KColor.background.ignoresSafeArea())
        .navigationTitle("Investments")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { SyncStatusToolbarItem() }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
    }

    private var portfolioHeader: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("PORTFOLIO")
                .font(.system(size: 10, weight: .bold))
                .tracking(1.3)
                .foregroundStyle(KColor.secondary)
            HStack(alignment: .firstTextBaseline) {
                Text(kEUR(totals.value.value, fraction: 2))
                    .font(.system(size: 40, weight: .bold, design: .rounded).monospacedDigit())
                    .foregroundStyle(KColor.primary)
                Spacer()
                Text(String(format: "%+.1f %%", totals.value.gainPct))
                    .font(.caption.weight(.bold))
                    .foregroundStyle(totals.value.gain >= 0 ? KColor.positive : KColor.negative)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .background((totals.value.gain >= 0 ? KColor.positive : KColor.negative).opacity(0.10), in: Capsule())
            }
            HStack(spacing: 6) {
                Image(systemName: totals.value.gain >= 0 ? "arrow.up.right" : "arrow.down.right")
                Text("\(kEUR(totals.value.gain, fraction: 2)) seit Einstand")
            }
            .font(.subheadline.weight(.medium))
            .foregroundStyle(totals.value.gain >= 0 ? KColor.positive : KColor.negative)
        }
    }

    private var performancePlaceholder: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Entwicklung")
                    .font(.headline.weight(.semibold))
                    .foregroundStyle(KColor.primary)
                Spacer()
                HStack(spacing: 3) {
                    ForEach(periods, id: \.self) { period in
                        Button(period) { withAnimation(.easeOut(duration: 0.18)) { selectedPeriod = period } }
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(selectedPeriod == period ? .white : KColor.secondary)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 6)
                            .background(selectedPeriod == period ? KColor.accent : KColor.surfaceSecondary, in: Capsule())
                    }
                }
            }
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(KColor.surfaceSecondary.opacity(0.55))
                .frame(height: 92)
                .overlay(alignment: .center) {
                    HStack(spacing: 7) {
                        Image(systemName: "chart.line.uptrend.xyaxis")
                        Text("Performance-Daten werden mit dem gewählten Zeitraum synchronisiert")
                    }
                    .font(.caption)
                    .foregroundStyle(KColor.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 24)
                }
        }
    }

    @ViewBuilder
    private var allocationSection: some View {
        if !allocation.value.isEmpty {
            VStack(alignment: .leading, spacing: 15) {
                HStack {
                    Text("Aufteilung")
                        .font(.headline.weight(.semibold))
                        .foregroundStyle(KColor.primary)
                    Spacer()
                    if selectedAllocation != nil {
                        Button("Zurück") { withAnimation { selectedAllocation = nil } }
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(KColor.accent)
                    }
                }

                HStack(spacing: 22) {
                    Chart(Array(allocation.value.enumerated()), id: \.element.id) { index, slice in
                        SectorMark(
                            angle: .value("Wert", slice.value),
                            innerRadius: .ratio(selectedAllocation == nil ? 0.66 : 0.58),
                            angularInset: 2
                        )
                        .cornerRadius(4)
                        .foregroundStyle(KColor.chartPalette[index % KColor.chartPalette.count])
                        .opacity(selectedAllocation == nil || selectedAllocation == slice.label ? 1 : 0.25)
                    }
                    .frame(width: 136, height: 136)
                    .chartOverlay { _ in
                        VStack(spacing: 2) {
                            if let selected = selectedAllocation,
                               let slice = allocation.value.first(where: { $0.label == selected }) {
                                Text(kEUR(slice.value, fraction: 0))
                                    .font(.subheadline.weight(.bold).monospacedDigit())
                                Text(label(for: selected))
                                    .font(.caption2)
                                    .foregroundStyle(KColor.secondary)
                            } else {
                                Text("100 %")
                                    .font(.subheadline.weight(.bold))
                                Text("Portfolio")
                                    .font(.caption2)
                                    .foregroundStyle(KColor.secondary)
                            }
                        }
                    }

                    VStack(alignment: .leading, spacing: 11) {
                        ForEach(Array(allocation.value.enumerated()), id: \.element.id) { index, slice in
                            Button {
                                withAnimation(.easeOut(duration: 0.18)) { selectedAllocation = selectedAllocation == slice.label ? nil : slice.label }
                            } label: {
                                HStack(spacing: 8) {
                                    Circle()
                                        .fill(KColor.chartPalette[index % KColor.chartPalette.count])
                                        .frame(width: 8, height: 8)
                                    Text(label(for: slice.label))
                                        .font(.subheadline)
                                        .foregroundStyle(KColor.primary)
                                    Spacer(minLength: 5)
                                    Text(kEUR(slice.value, fraction: 0))
                                        .font(.caption.monospacedDigit())
                                        .foregroundStyle(KColor.secondary)
                                }
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
        }
    }

    private var positionsSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Positionen")
                    .font(.headline.weight(.semibold))
                    .foregroundStyle(KColor.primary)
                Spacer()
                Text("\(holdings.value.count)")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(KColor.secondary)
            }
            VStack(spacing: 0) {
                ForEach(holdings.value) { holding in
                    HStack(spacing: 12) {
                        Image(systemName: assetIcon(holding.asset_type))
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(KColor.accent)
                            .frame(width: 36, height: 36)
                            .background(KColor.accent.opacity(0.10), in: RoundedRectangle(cornerRadius: 11, style: .continuous))
                        VStack(alignment: .leading, spacing: 3) {
                            Text(holding.name)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(KColor.primary)
                                .lineLimit(1)
                            Text("\(holding.symbol) · \(label(for: holding.asset_type))")
                                .font(.caption)
                                .foregroundStyle(KColor.secondary)
                                .lineLimit(1)
                        }
                        Spacer(minLength: 8)
                        VStack(alignment: .trailing, spacing: 4) {
                            Text(kEUR(currentValue(holding), fraction: 2))
                                .font(.subheadline.weight(.semibold).monospacedDigit())
                                .foregroundStyle(KColor.primary)
                            if let gain = gainPercent(holding) {
                                Text(String(format: "%+.1f %%", gain))
                                    .font(.caption2.weight(.bold))
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

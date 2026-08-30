import SwiftUI
import Charts
import GRDB
import KiesCore

/// Premium light investment dashboard with neon accent interactions.
struct InvestmentsView: View {
    @ObservedObject var engine = SyncEngine.shared
    @StateObject private var holdings = Box<[Holding]>([])
    @StateObject private var allocation = Box<[Queries.AllocationSlice]>([])
    @StateObject private var totals = Box(Queries.InvestmentTotals(value: 0, cost: 0))
    @State private var selectedAllocation: String?

    var body: some View {
        KScreen(spacing: KSpacing.xl) {
            header
            portfolioHero
            allocationView
            positions
        }
        .toolbar { SyncStatusToolbarItem() }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            KKicker(text: "Vermögen")
            Text("Investments").font(KFont.title).foregroundStyle(KColor.primary)
            Text("Dein Portfolio, ohne unnötige Komplexität.").font(.subheadline).foregroundStyle(KColor.secondary)
        }
    }

    private var portfolioHero: some View {
        VStack(alignment: .leading, spacing: KSpacing.md) {
            Text("Portfolio-Wert").font(.footnote.weight(.bold)).foregroundStyle(KColor.secondary)
            Text(kEUR(totals.value.value)).font(KFont.hero).foregroundStyle(KColor.primary).minimumScaleFactor(0.55).lineLimit(1)
            HStack(spacing: 8) {
                Text(String(format: "%+.2f €", totals.value.gain)).font(.footnote.weight(.bold)).foregroundStyle(totals.value.gain >= 0 ? KColor.positive : KColor.negative)
                Text(String(format: "%+.1f %%", totals.value.gainPct)).font(.footnote.weight(.bold)).foregroundStyle(totals.value.gain >= 0 ? KColor.positive : KColor.negative)
                Spacer()
                Image(systemName: "chart.line.uptrend.xyaxis").foregroundStyle(KColor.accentStrong)
            }
            RoundedRectangle(cornerRadius: 3).fill(KColor.accent).frame(height: 6)
                .overlay(alignment: .leading) { RoundedRectangle(cornerRadius: 3).fill(KColor.accentStrong).frame(width: max(20, min(180, CGFloat(abs(totals.value.gainPct) * 12)))) }
        }
        .kCard(KSpacing.lg)
    }

    private var allocationView: some View {
        VStack(alignment: .leading, spacing: KSpacing.md) {
            HStack { Text("Aufteilung").font(KFont.sectionH); Spacer(); Text("Antippen zum Filtern").font(.caption.weight(.semibold)).foregroundStyle(KColor.secondary) }
            if allocation.value.isEmpty {
                Text("Noch keine Aufteilung verfügbar.").font(.callout).foregroundStyle(KColor.secondary)
            } else {
                HStack(spacing: KSpacing.lg) {
                    Chart(Array(allocation.value.enumerated()), id: \.element.id) { index, slice in
                        SectorMark(angle: .value("Wert", slice.value), innerRadius: .ratio(0.68), angularInset: 2)
                            .cornerRadius(4)
                            .foregroundStyle(KColor.chartPalette[index % KColor.chartPalette.count])
                            .opacity(selectedAllocation == nil || selectedAllocation == slice.label ? 1 : 0.25)
                    }
                    .frame(width: 135, height: 135)
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(Array(allocation.value.enumerated()), id: \.element.id) { index, slice in
                            Button {
                                withAnimation(.easeOut(duration: 0.18)) { selectedAllocation = selectedAllocation == slice.label ? nil : slice.label }
                            } label: {
                                HStack(spacing: 8) {
                                    Circle().fill(KColor.chartPalette[index % KColor.chartPalette.count]).frame(width: 9, height: 9)
                                    Text(label(for: slice.label)).font(.caption.weight(.bold)).foregroundStyle(KColor.primary)
                                    Spacer(minLength: 3)
                                    Text(kEUR(slice.value)).font(.caption.weight(.semibold)).foregroundStyle(KColor.secondary)
                                }
                            }.buttonStyle(.plain)
                        }
                    }
                }
            }
        }
        .kCard(KSpacing.md)
    }

    private var positions: some View {
        VStack(alignment: .leading, spacing: KSpacing.md) {
            HStack { Text("Positionen").font(KFont.sectionH); Spacer(); Text("\(holdings.value.count)").font(.caption.weight(.bold)).foregroundStyle(KColor.secondary) }
            VStack(spacing: 0) {
                ForEach(filteredHoldings) { holding in
                    HStack(spacing: KSpacing.md) {
                        RoundedRectangle(cornerRadius: 11).fill(KColor.surfaceSoft).frame(width: 42, height: 42)
                            .overlay(Text(String(holding.symbol.prefix(1))).font(.footnote.weight(.bold)).foregroundStyle(KColor.primary))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(holding.name).font(.body.weight(.bold)).foregroundStyle(KColor.primary).lineLimit(1)
                            Text("\(holding.symbol) · \(label(for: holding.asset_type))").font(.caption).foregroundStyle(KColor.secondary)
                        }
                        Spacer(minLength: 8)
                        VStack(alignment: .trailing, spacing: 3) {
                            Text(kEUR(currentValue(holding), fraction: 2)).font(.body.weight(.bold)).monospacedDigit().foregroundStyle(KColor.primary)
                            if let gain = gainPercent(holding) { Text(String(format: "%+.1f %%", gain)).font(.caption2.weight(.bold)).foregroundStyle(gain >= 0 ? KColor.positive : KColor.negative) }
                        }
                    }
                    .padding(.vertical, 13)
                    if holding.id != filteredHoldings.last?.id { Divider().overlay(KColor.divider) }
                }
            }
            .padding(.horizontal, KSpacing.md)
            .background(KColor.surface.opacity(0.96), in: RoundedRectangle(cornerRadius: KRadius.md, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: KRadius.md, style: .continuous).stroke(KColor.divider, lineWidth: 1))
        }
    }

    private var filteredHoldings: [Holding] {
        guard let selected = selectedAllocation else { return holdings.value }
        return holdings.value.filter { label(for: $0.asset_type) == label(for: selected) }
    }

    private func currentValue(_ h: Holding) -> Double { (h.current_price ?? h.purchase_price) * h.quantity }
    private func gainPercent(_ h: Holding) -> Double? { guard h.purchase_price > 0, let current = h.current_price else { return nil }; return (current - h.purchase_price) / h.purchase_price * 100 }
    private func label(for type: String) -> String {
        switch type.lowercased() { case "stock", "aktie": return "Aktie"; case "etf": return "ETF"; case "crypto", "krypto": return "Krypto"; case "fund", "fonds": return "Fonds"; case "bond", "anleihe": return "Anleihe"; case "cash": return "Cash"; default: return type.capitalized }
    }
    private func reload() {
        let db = AppDatabase.shared
        holdings.value = (try? db.read { db in try Queries.allHoldings(db) }) ?? []
        allocation.value = (try? db.read { db in try Queries.holdingsAllocation(db) }) ?? []
        totals.value = (try? db.read { db in try Queries.investmentTotals(db) }) ?? Queries.InvestmentTotals(value: 0, cost: 0)
    }
}

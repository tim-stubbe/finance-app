import SwiftUI
import Charts
import KiesCore
import GRDB

/// Clean account hub: one strong balance, a simple trend and interactive account rows.
struct AccountsView: View {
    @ObservedObject var engine = SyncEngine.shared
    @StateObject private var rows = Box<[(account: Account, balance: Double)]>([])
    @StateObject private var netSeries = Box<[Queries.DayValue]>([])
    @State private var selectedAccountID: Int64?

    private var netWorth: Double { rows.value.reduce(0) { $0 + $1.balance } }

    var body: some View {
        KScreen(spacing: KSpacing.xl) {
            header
            balanceHero
            accountList
        }
        .toolbar { SyncStatusToolbarItem() }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
        .sheet(item: Binding(get: { selectedAccountID.map(AccountSelection.init) }, set: { selectedAccountID = $0?.id })) { selection in
            if let row = rows.value.first(where: { $0.account.id == selection.id }) {
                AccountQuickDetail(account: row.account, balance: row.balance)
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            KKicker(text: "Geld")
            Text("Konten").font(KFont.title).foregroundStyle(KColor.primary)
            Text("Alles an einem Ort. Klar, schnell und ohne Banking-Overload.")
                .font(.subheadline).foregroundStyle(KColor.secondary)
        }
    }

    private var balanceHero: some View {
        VStack(alignment: .leading, spacing: KSpacing.md) {
            Text("Gesamt").font(.footnote.weight(.bold)).foregroundStyle(KColor.secondary)
            Text(kEUR(netWorth)).font(KFont.hero).foregroundStyle(KColor.primary).minimumScaleFactor(0.55).lineLimit(1)
            if netSeries.value.count > 1 {
                Chart(netSeries.value) { point in
                    AreaMark(x: .value("Tag", point.date), y: .value("Wert", point.value))
                        .foregroundStyle(.linearGradient(colors: [KColor.accent.opacity(0.52), KColor.accent.opacity(0.02)], startPoint: .top, endPoint: .bottom))
                    LineMark(x: .value("Tag", point.date), y: .value("Wert", point.value))
                        .foregroundStyle(KColor.accentStrong).lineStyle(.init(lineWidth: 3, lineCap: .round))
                }
                .chartXAxis(.hidden).chartYAxis(.hidden).frame(height: 90)
            }
            Text("90 Tage").font(.caption.weight(.semibold)).foregroundStyle(KColor.tertiary)
        }
        .kCard(KSpacing.lg)
    }

    private var accountList: some View {
        VStack(alignment: .leading, spacing: KSpacing.md) {
            HStack { Text("Deine Konten").font(KFont.sectionH); Spacer(); Text("\(rows.value.count)").font(.caption.weight(.bold)).foregroundStyle(KColor.secondary) }
            VStack(spacing: 0) {
                ForEach(rows.value, id: \.account.id) { row in
                    Button { selectedAccountID = row.account.id } label: {
                        HStack(spacing: KSpacing.md) {
                            Image(systemName: icon(for: row.account.type))
                                .font(.headline.weight(.bold)).foregroundStyle(KColor.accentInk)
                                .frame(width: 42, height: 42).background(KColor.accent, in: RoundedRectangle(cornerRadius: 13, style: .continuous))
                            VStack(alignment: .leading, spacing: 3) {
                                Text(row.account.name).font(.body.weight(.bold)).foregroundStyle(KColor.primary).lineLimit(1)
                                Text(row.account.type.capitalized).font(.caption).foregroundStyle(KColor.secondary)
                            }
                            Spacer()
                            VStack(alignment: .trailing, spacing: 3) {
                                Text(kEUR(row.balance, fraction: 2)).font(.body.weight(.bold)).monospacedDigit().foregroundStyle(row.balance < 0 ? KColor.negative : KColor.primary)
                                Image(systemName: "chevron.right").font(.caption.weight(.bold)).foregroundStyle(KColor.tertiary)
                            }
                        }
                        .padding(.vertical, 13)
                    }
                    .buttonStyle(.plain)
                    if row.account.id != rows.value.last?.account.id { Divider().overlay(KColor.divider) }
                }
            }
            .padding(.horizontal, KSpacing.md)
            .background(KColor.surface.opacity(0.96), in: RoundedRectangle(cornerRadius: KRadius.md, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: KRadius.md, style: .continuous).stroke(KColor.divider, lineWidth: 1))
        }
        if rows.value.isEmpty {
            KEmptyState(icon: "creditcard", title: "Noch keine Konten", message: "Synchronisiere Kies mit deinem Server, um deine Konten zu sehen.", actionTitle: "Jetzt synchronisieren", action: { Task { await engine.run() } })
        }
    }

    private func icon(for type: String) -> String {
        switch type.lowercased() { case let t where t.contains("spar"): return "banknote"; case let t where t.contains("kredit") || t.contains("credit"): return "creditcard"; case let t where t.contains("bar") || t.contains("cash"): return "wallet.pass"; case let t where t.contains("depot") || t.contains("invest"): return "chart.line.uptrend.xyaxis"; default: return "building.columns" }
    }

    private func reload() {
        let db = AppDatabase.shared
        rows.value = (try? db.read { db in try Account.order(Column("name")).fetchAll(db).map { ($0, try Queries.accountBalance(db, accountID: $0.id)) } }) ?? []
        netSeries.value = (try? db.read { db in try Queries.netWorthSeries(db, days: 90) }) ?? []
    }
}

private struct AccountSelection: Identifiable { let id: Int64 }

private struct AccountQuickDetail: View {
    let account: Account
    let balance: Double
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: KSpacing.lg) {
                Image(systemName: "building.columns").font(.title2.weight(.bold)).foregroundStyle(KColor.accentInk)
                    .frame(width: 56, height: 56).background(KColor.accent, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                Text(account.name).font(KFont.title)
                Text(kEUR(balance, fraction: 2)).font(KFont.hero).foregroundStyle(KColor.primary)
                Text(account.type.capitalized).font(.subheadline).foregroundStyle(KColor.secondary)
                Spacer()
            }
            .padding(KSpacing.lg)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(NeonBackdrop(opacity: 0.12))
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Schließen") { dismiss() } } }
        }
    }
}

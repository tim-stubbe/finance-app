import SwiftUI
import Charts
import KiesCore
import GRDB

/// Konten-Übersicht: Nettovermögen mit 90-Tage-Verlauf oben, darunter die
/// Konten als Karten mit Kontostand und relativem Balken. Verlauf wird lokal
/// aus den Buchungen zurückgerechnet (siehe Queries.netWorthSeries) - es gibt
/// keine synchronisierten net_worth_snapshots.
struct AccountsView: View {
    @ObservedObject var engine = SyncEngine.shared
    @StateObject private var rows = Box<[(account: Account, balance: Double)]>([])
    @StateObject private var netSeries = Box<[Queries.DayValue]>([])

    private var netWorth: Double { rows.value.reduce(0) { $0 + $1.balance } }

    var body: some View {
        KScreen {
            netWorthCard

            if rows.value.isEmpty {
                KEmptyState(icon: "creditcard",
                            title: "Noch keine Konten",
                            message: "Synchronisiere Kies mit deinem Server, um deine Konten hier zu sehen.",
                            actionTitle: "Jetzt synchronisieren",
                            action: { Task { await engine.run() } })
            } else {
                VStack(alignment: .leading, spacing: KSpacing.sm) {
                    KSectionHeader(title: "Konten")
                    VStack(spacing: 0) {
                        ForEach(rows.value, id: \.account.id) { row in
                            KAccountRow(icon: icon(for: row.account.type),
                                        name: row.account.name,
                                        subtitle: row.account.type.capitalized,
                                        amount: row.balance)
                            if row.account.id != rows.value.last?.account.id {
                                Divider().overlay(KColor.divider)
                            }
                        }
                    }
                    .kCard(KSpacing.md)
                }
            }
        }
        .navigationTitle("Konten")
        .toolbar { SyncStatusToolbarItem() }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
    }

    private var netWorthCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Nettovermögen").font(.footnote).foregroundStyle(KColor.secondary)
            Text(kEUR(netWorth))
                .font(KFont.hero)
                .foregroundStyle(netWorth < 0 ? KColor.negative : KColor.primary)
                .minimumScaleFactor(0.55).lineLimit(1)

            if netSeries.value.count > 1 {
                Chart(netSeries.value) { point in
                    AreaMark(x: .value("Tag", point.date), y: .value("Wert", point.value))
                        .foregroundStyle(.linearGradient(
                            colors: [Color.accentColor.opacity(0.28), Color.accentColor.opacity(0.02)],
                            startPoint: .top, endPoint: .bottom))
                        .interpolationMethod(.monotone)
                    LineMark(x: .value("Tag", point.date), y: .value("Wert", point.value))
                        .foregroundStyle(Color.accentColor)
                        .interpolationMethod(.monotone)
                }
                .chartXAxis { AxisMarks(values: .stride(by: .month)) { AxisGridLine(); AxisValueLabel(format: .dateTime.month(.abbreviated)) } }
                .chartYAxis { AxisMarks { AxisValueLabel() } }
                .frame(height: 140)
                Text("Verlauf 90 Tage").font(.caption2).foregroundStyle(.secondary)
            }
        }
        .kCard()
    }


    private func icon(for type: String) -> String {
        switch type.lowercased() {
        case let t where t.contains("spar"): return "banknote"
        case let t where t.contains("kredit") || t.contains("credit"): return "creditcard"
        case let t where t.contains("bar") || t.contains("cash"): return "wallet.pass"
        case let t where t.contains("depot") || t.contains("invest"): return "chart.line.uptrend.xyaxis"
        default: return "building.columns"
        }
    }

    private func reload() {
        let db = AppDatabase.shared
        rows.value = (try? db.read { db in
            try Account.order(Column("name")).fetchAll(db).map { account in
                (account, try Queries.accountBalance(db, accountID: account.id))
            }
        }) ?? []
        netSeries.value = (try? db.read { db in try Queries.netWorthSeries(db, days: 90) }) ?? []
    }
}

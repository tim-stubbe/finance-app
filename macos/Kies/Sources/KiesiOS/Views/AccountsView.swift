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
    private var maxAbsBalance: Double { max(rows.value.map { abs($0.balance) }.max() ?? 1, 1) }

    var body: some View {
        KScreen {
            netWorthCard

            if rows.value.isEmpty {
                ContentUnavailableView("Noch keine Konten", systemImage: "banknote",
                                       description: Text("Wird beim nächsten Sync geladen."))
                    .kCard()
            } else {
                KSection(title: "Konten", systemImage: "banknote") {
                    VStack(spacing: 14) {
                        ForEach(rows.value, id: \.account.id) { row in
                            accountRow(row.account, balance: row.balance)
                        }
                    }
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
            Text("NETTOVERMÖGEN")
                .font(.caption2.weight(.semibold)).foregroundStyle(.secondary)
            Text(kEUR(netWorth))
                .font(.system(size: 34, weight: .bold, design: .rounded))
                .foregroundStyle(netWorth < 0 ? KTheme.negative : .primary)
                .minimumScaleFactor(0.6).lineLimit(1)

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

    private func accountRow(_ account: Account, balance: Double) -> some View {
        VStack(spacing: 6) {
            HStack {
                Image(systemName: icon(for: account.type))
                    .foregroundStyle(Color.accentColor)
                    .frame(width: 26)
                VStack(alignment: .leading, spacing: 1) {
                    Text(account.name).font(.callout.weight(.medium))
                    Text(account.type.capitalized).font(.caption2).foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
                Text(kEUR(balance, fraction: 2))
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(balance < 0 ? KTheme.negative : .primary)
            }
            GeometryReader { geo in
                Capsule()
                    .fill(Color.secondary.opacity(0.12))
                    .overlay(alignment: .leading) {
                        Capsule()
                            .fill(balance < 0 ? KTheme.negative : Color.accentColor)
                            .frame(width: max(4, geo.size.width * abs(balance) / maxAbsBalance))
                    }
            }
            .frame(height: 4)
        }
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

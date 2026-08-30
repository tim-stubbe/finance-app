import SwiftUI
import Charts
import KiesCore
import GRDB

/// Clean, finance-first dashboard. This view intentionally uses open list rows
/// instead of wrapping every section in a card.
struct PremiumTodayView: View {
    @ObservedObject var engine = SyncEngine.shared
    @StateObject private var netWorth = Box(0.0)
    @StateObject private var netSeries = Box<[Queries.DayValue]>([])
    @StateObject private var accounts = Box<[(account: Account, balance: Double)]>([])
    @StateObject private var transactions = Box<[TransactionRecord]>([])
    @StateObject private var monthIncome = Box(0.0)
    @StateObject private var monthExpense = Box(0.0)
    @StateObject private var cashflow = Box<[Queries.MonthFlow]>([])

    private var monthNet: Double { monthIncome.value - monthExpense.value }
    private var netDelta: Double {
        guard let first = netSeries.value.first?.value,
              let last = netSeries.value.last?.value else { return 0 }
        return last - first
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                greeting
                hero
                accountsSection
                transactionsSection
                monthSummary
                cashflowSection
            }
            .padding(.horizontal, 20)
            .padding(.top, 12)
            .padding(.bottom, 110)
        }
        .background(KColor.background.ignoresSafeArea())
        .scrollIndicators(.hidden)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                NavigationLink { SettingsView() } label: {
                    Image(systemName: "gearshape")
                }
            }
            SyncStatusToolbarItem()
        }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
    }

    private var greeting: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(greetingText)
                .font(.system(size: 32, weight: .bold, design: .rounded))
                .foregroundStyle(KColor.primary)
            Text(Date().formatted(.dateTime.weekday(.wide).day().month(.wide)))
                .font(.subheadline)
                .foregroundStyle(KColor.secondary)
        }
    }

    private var hero: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Gesamtvermögen")
                .font(.subheadline)
                .foregroundStyle(KColor.secondary)

            Text(kEUR(netWorth.value))
                .font(.system(size: 44, weight: .bold, design: .rounded).monospacedDigit())
                .foregroundStyle(KColor.primary)
                .minimumScaleFactor(0.65)
                .lineLimit(1)

            if abs(netDelta) > 0.5 {
                HStack(spacing: 5) {
                    Image(systemName: netDelta >= 0 ? "arrow.up.right" : "arrow.down.right")
                    Text("\(netDelta >= 0 ? "+" : "")\(kEUR(netDelta))")
                    Text("· 30 Tage")
                        .foregroundStyle(KColor.secondary)
                }
                .font(.subheadline.weight(.medium))
                .foregroundStyle(netDelta >= 0 ? KColor.positive : KColor.negative)
            }

            if netSeries.value.count > 1 {
                Chart(netSeries.value) { point in
                    AreaMark(x: .value("Tag", point.date), y: .value("Wert", point.value))
                        .foregroundStyle(
                            .linearGradient(
                                colors: [KColor.accent.opacity(0.18), KColor.accent.opacity(0)],
                                startPoint: .top,
                                endPoint: .bottom
                            )
                        )
                    LineMark(x: .value("Tag", point.date), y: .value("Wert", point.value))
                        .foregroundStyle(KColor.accent)
                        .lineStyle(.init(lineWidth: 2))
                }
                .chartXAxis(.hidden)
                .chartYAxis(.hidden)
                .frame(height: 72)
            }
        }
        .padding(22)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(KColor.surface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    private var accountsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionHeader("Konten") {
                TabRouter.shared.selection = .accounts
            }

            VStack(spacing: 0) {
                ForEach(Array(accounts.value.prefix(5)), id: \.account.id) { row in
                    Button {
                        TabRouter.shared.selection = .accounts
                    } label: {
                        HStack(spacing: 14) {
                            Image(systemName: icon(for: row.account.type))
                                .font(.callout)
                                .foregroundStyle(KColor.accent)
                                .frame(width: 34, height: 34)
                                .background(KColor.accent.opacity(0.10), in: RoundedRectangle(cornerRadius: 10, style: .continuous))

                            VStack(alignment: .leading, spacing: 2) {
                                Text(row.account.name)
                                    .font(.body.weight(.medium))
                                    .foregroundStyle(KColor.primary)
                                Text(row.account.type.capitalized)
                                    .font(.caption)
                                    .foregroundStyle(KColor.secondary)
                            }
                            Spacer()
                            Text(kEUR(row.balance, fraction: 2))
                                .font(.body.weight(.semibold).monospacedDigit())
                                .foregroundStyle(row.balance < 0 ? KColor.negative : KColor.primary)
                            Image(systemName: "chevron.right")
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(KColor.secondary.opacity(0.55))
                        }
                        .padding(.vertical, 11)
                    }
                    .buttonStyle(.plain)

                    if row.account.id != accounts.value.prefix(5).last?.account.id {
                        Divider().overlay(KColor.divider)
                    }
                }
            }
        }
    }

    private var transactionsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionHeader("Letzte Transaktionen") {
                TabRouter.shared.selection = .transactions
            }

            VStack(spacing: 0) {
                ForEach(Array(transactions.value.prefix(6))) { tx in
                    Button {
                        TabRouter.shared.selection = .transactions
                    } label: {
                        HStack(spacing: 14) {
                            Image(systemName: transactionIcon(tx.description ?? ""))
                                .font(.caption)
                                .foregroundStyle(KColor.secondary)
                                .frame(width: 34, height: 34)
                                .background(KColor.surfaceSecondary, in: Circle())

                            Text(tx.description ?? "Buchung")
                                .font(.body)
                                .foregroundStyle(KColor.primary)
                                .lineLimit(1)

                            Spacer(minLength: 8)
                            Text(kEUR(tx.amount, fraction: 2))
                                .font(.body.weight(.medium).monospacedDigit())
                                .foregroundStyle(tx.amount > 0 ? KColor.positive : KColor.primary)
                        }
                        .padding(.vertical, 10)
                    }
                    .buttonStyle(.plain)
                    if tx.id != transactions.value.prefix(6).last?.id {
                        Divider().overlay(KColor.divider)
                    }
                }
            }
        }
    }

    private var monthSummary: some View {
        Button {
            TabRouter.shared.selection = .more
        } label: {
            HStack(alignment: .top, spacing: 14) {
                Image(systemName: "chart.line.uptrend.xyaxis")
                    .foregroundStyle(KColor.accent)
                    .frame(width: 36, height: 36)
                    .background(KColor.accent.opacity(0.10), in: RoundedRectangle(cornerRadius: 10, style: .continuous))

                VStack(alignment: .leading, spacing: 5) {
                    Text("Diesen Monat")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(KColor.primary)
                    Text("Einnahmen \(kEUR(monthIncome.value)) · Ausgaben \(kEUR(monthExpense.value))")
                        .font(.subheadline)
                        .foregroundStyle(KColor.secondary)
                    Text("Netto \(kEUR(monthNet))")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(monthNet >= 0 ? KColor.positive : KColor.negative)
                }
                Spacer()
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(KColor.surfaceSecondary, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .buttonStyle(.plain)
    }

    private var cashflowSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Cashflow")
                    .font(.headline)
                    .foregroundStyle(KColor.primary)
                Spacer()
                Text("6 Monate")
                    .font(.caption)
                    .foregroundStyle(KColor.secondary)
            }

            if cashflow.value.contains(where: { $0.income > 0 || $0.expense > 0 }) {
                Chart {
                    ForEach(cashflow.value) { month in
                        BarMark(x: .value("Monat", month.label), y: .value("Betrag", month.income))
                            .foregroundStyle(KColor.positive)
                            .position(by: .value("Art", "Einnahmen"))
                        BarMark(x: .value("Monat", month.label), y: .value("Betrag", month.expense))
                            .foregroundStyle(KColor.negative)
                            .position(by: .value("Art", "Ausgaben"))
                    }
                }
                .chartXAxis { AxisMarks { AxisValueLabel() } }
                .chartYAxis(.hidden)
                .chartLegend(.hidden)
                .frame(height: 150)
            }
        }
    }

    private func sectionHeader(_ title: String, action: @escaping () -> Void) -> some View {
        HStack {
            Text(title)
                .font(.headline)
                .foregroundStyle(KColor.primary)
            Spacer()
            Button("Alle", action: action)
                .font(.subheadline.weight(.medium))
                .foregroundStyle(KColor.accent)
        }
    }

    private var greetingText: String {
        switch Calendar.current.component(.hour, from: Date()) {
        case 5..<11: return "Guten Morgen"
        case 11..<18: return "Guten Tag"
        default: return "Guten Abend"
        }
    }

    private func icon(for type: String) -> String {
        switch type.lowercased() {
        case let value where value.contains("spar"): return "banknote"
        case let value where value.contains("kredit") || value.contains("credit"): return "creditcard"
        case let value where value.contains("bar") || value.contains("cash"): return "wallet.pass"
        case let value where value.contains("depot") || value.contains("invest"): return "chart.line.uptrend.xyaxis"
        default: return "building.columns"
        }
    }

    private func transactionIcon(_ title: String) -> String {
        let value = title.lowercased()
        if value.contains("rewe") || value.contains("edeka") || value.contains("aldi") || value.contains("lidl") { return "cart.fill" }
        if value.contains("amazon") || value.contains("paypal") { return "bag.fill" }
        if value.contains("tank") || value.contains("oil") || value.contains("shell") || value.contains("aral") { return "fuelpump.fill" }
        if value.contains("gehalt") || value.contains("lohn") { return "arrow.down.circle.fill" }
        return "arrow.up.right"
    }

    private func reload() {
        let db = AppDatabase.shared
        netWorth.value = (try? db.read { try Queries.netWorth($0) }) ?? 0
        netSeries.value = (try? db.read { try Queries.netWorthSeries($0, days: 30) }) ?? []
        accounts.value = (try? db.read { db in
            try Account.order(Column("name")).fetchAll(db).map { account in
                (account, try Queries.accountBalance(db, accountID: account.id))
            }
        }) ?? []
        transactions.value = (try? db.read { try TransactionRecord.order(Column("date").desc).limit(6).fetchAll($0) }) ?? []
        let flow = (try? db.read { try Queries.currentMonthCashflow($0) }) ?? (income: 0, expense: 0)
        monthIncome.value = flow.income
        monthExpense.value = flow.expense
        cashflow.value = (try? db.read { try Queries.monthlyCashflow($0, months: 6) }) ?? []
    }
}

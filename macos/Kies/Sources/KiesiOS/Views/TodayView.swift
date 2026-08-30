import SwiftUI
import Charts
import KiesCore
import GRDB

/// 2026 light banking home: Alpine identity + neon-inspired interaction.
struct TodayView: View {
    @ObservedObject var engine = SyncEngine.shared
    @StateObject private var monthIncome = Box(0.0)
    @StateObject private var monthExpense = Box(0.0)
    @StateObject private var cashflow = Box<[Queries.MonthFlow]>([])
    @StateObject private var netWorth = Box(0.0)
    @StateObject private var netSeries = Box<[Queries.DayValue]>([])
    @StateObject private var accountRows = Box<[(account: Account, balance: Double)]>([])
    @StateObject private var recentTx = Box<[TransactionRecord]>([])
    @StateObject private var dueTodos = Box<[Todo]>([])
    @StateObject private var upcomingEvents = Box<[CalendarEvent]>([])
    @State private var range = 30

    private var monthNet: Double { monthIncome.value - monthExpense.value }
    private var netDelta: Double {
        guard let first = netSeries.value.first?.value, let last = netSeries.value.last?.value else { return 0 }
        return last - first
    }

    var body: some View {
        KScreen(spacing: KSpacing.xl) {
            header
            wealthHero
            accounts
            transactions
            monthlyInsight
            cashflowChart
            if !upcomingEvents.value.isEmpty { upcoming }
            if !dueTodos.value.isEmpty { tasks }
            SyncStatusFooter().font(.caption).foregroundStyle(KColor.secondary)
        }
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                NavigationLink { SettingsView() } label: { Image(systemName: "gearshape") }
            }
            SyncStatusToolbarItem()
        }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text(greeting).font(.subheadline.weight(.semibold)).foregroundStyle(KColor.secondary)
                    Text("Deine Finanzen").font(KFont.title).foregroundStyle(KColor.primary)
                }
                Spacer()
                Circle()
                    .fill(KColor.accent)
                    .frame(width: 44, height: 44)
                    .overlay(Image(systemName: "person.fill").foregroundStyle(KColor.accentInk))
            }
            Text(Date().formatted(.dateTime.weekday(.wide).day().month(.wide)))
                .font(.footnote.weight(.medium)).foregroundStyle(KColor.tertiary)
        }
        .padding(.top, KSpacing.xs)
    }

    private var wealthHero: some View {
        VStack(alignment: .leading, spacing: KSpacing.md) {
            HStack {
                Text("Gesamtvermögen").font(.footnote.weight(.bold)).foregroundStyle(KColor.secondary)
                Spacer()
                Image(systemName: "eye").font(.footnote.weight(.bold)).foregroundStyle(KColor.tertiary)
            }
            Text(kEUR(netWorth.value))
                .font(KFont.hero).foregroundStyle(KColor.primary)
                .minimumScaleFactor(0.55).lineLimit(1)
            HStack(spacing: 7) {
                Image(systemName: netDelta >= 0 ? "arrow.up.right" : "arrow.down.right")
                Text(kEUR(netDelta)).monospacedDigit()
                Text("· 30 Tage").foregroundStyle(KColor.secondary)
            }
            .font(.footnote.weight(.bold))
            .foregroundStyle(netDelta >= 0 ? KColor.positive : KColor.negative)

            if netSeries.value.count > 1 {
                Chart(netSeries.value) { point in
                    AreaMark(x: .value("Tag", point.date), y: .value("Wert", point.value))
                        .foregroundStyle(.linearGradient(colors: [KColor.accent.opacity(0.60), KColor.accent.opacity(0.03)], startPoint: .top, endPoint: .bottom))
                        .interpolationMethod(.monotone)
                    LineMark(x: .value("Tag", point.date), y: .value("Wert", point.value))
                        .foregroundStyle(KColor.accentStrong)
                        .lineStyle(.init(lineWidth: 3, lineCap: .round))
                        .interpolationMethod(.monotone)
                }
                .chartXAxis(.hidden).chartYAxis(.hidden)
                .frame(height: 120)
            }

            HStack {
                Text("Vermögensentwicklung").font(.caption.weight(.bold)).foregroundStyle(KColor.secondary)
                Spacer()
                HStack(spacing: 4) {
                    Button("1M") { range = 30; reload() }.buttonStyle(NeonRangeButton(active: range == 30))
                    Button("3M") { range = 90; reload() }.buttonStyle(NeonRangeButton(active: range == 90))
                }
            }
        }
        .kCard(KSpacing.lg)
    }

    private var accounts: some View {
        VStack(alignment: .leading, spacing: KSpacing.md) {
            KSectionHeader(title: "Konten", action: ("Alle", { TabRouter.shared.selection = .accounts }))
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: KSpacing.md) {
                    ForEach(accountRows.value.prefix(8), id: \.account.id) { row in
                        Button { TabRouter.shared.selection = .accounts } label: {
                            VStack(alignment: .leading, spacing: 10) {
                                HStack {
                                    Image(systemName: icon(for: row.account.type)).foregroundStyle(KColor.accentInk)
                                        .frame(width: 36, height: 36).background(KColor.accent, in: RoundedRectangle(cornerRadius: 11, style: .continuous))
                                    Spacer()
                                    Image(systemName: "arrow.up.right").font(.caption.weight(.bold)).foregroundStyle(KColor.tertiary)
                                }
                                Text(row.account.name).font(.footnote.weight(.bold)).foregroundStyle(KColor.primary).lineLimit(1)
                                Text(kEUR(row.balance, fraction: 2)).font(.system(size: 20, weight: .bold, design: .rounded)).monospacedDigit().foregroundStyle(KColor.primary).lineLimit(1).minimumScaleFactor(0.7)
                                Text(row.account.type.capitalized).font(.caption2.weight(.medium)).foregroundStyle(KColor.secondary)
                            }
                            .frame(width: 164, height: 145, alignment: .leading)
                            .padding(KSpacing.md)
                            .background(KColor.surface, in: RoundedRectangle(cornerRadius: KRadius.md, style: .continuous))
                            .overlay(RoundedRectangle(cornerRadius: KRadius.md, style: .continuous).stroke(KColor.divider, lineWidth: 1))
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            if accountRows.value.isEmpty {
                KEmptyState(icon: "creditcard", title: "Noch keine Konten", message: "Synchronisiere Kies, um deine Konten zu sehen.", actionTitle: "Synchronisieren", action: { Task { await engine.run() } })
            }
        }
    }

    private var transactions: some View {
        VStack(alignment: .leading, spacing: KSpacing.md) {
            KSectionHeader(title: "Letzte Buchungen", action: ("Alle", { TabRouter.shared.selection = .transactions }))
            VStack(spacing: 0) {
                ForEach(Array(recentTx.value.prefix(5))) { tx in
                    KTransactionRow(title: tx.description ?? "Buchung", amount: tx.amount, pending: tx.pending_client_id != nil)
                    if tx.id != recentTx.value.prefix(5).last?.id { Divider().overlay(KColor.divider) }
                }
            }
            .kCard(KSpacing.md)
        }
    }

    private var monthlyInsight: some View {
        Button { TabRouter.shared.selection = .more } label: {
            HStack(spacing: KSpacing.md) {
                Circle().fill(KColor.accent).frame(width: 48, height: 48).overlay(Image(systemName: "bolt.fill").foregroundStyle(KColor.accentInk))
                VStack(alignment: .leading, spacing: 4) {
                    Text("Diesen Monat").font(.footnote.weight(.bold)).foregroundStyle(KColor.secondary)
                    Text("\(kEUR(monthIncome.value)) Einnahmen · \(kEUR(monthExpense.value)) Ausgaben").font(.callout.weight(.semibold)).foregroundStyle(KColor.primary)
                    Text("Netto \(kEUR(monthNet)) · Analyse öffnen →").font(.caption.weight(.bold)).foregroundStyle(KColor.accentStrong)
                }
                Spacer()
            }
            .kCard(KSpacing.md)
        }
        .buttonStyle(.plain)
    }

    private var cashflowChart: some View {
        VStack(alignment: .leading, spacing: KSpacing.md) {
            HStack { Text("Cashflow").font(KFont.sectionH); Spacer(); Text("6 Monate").font(.caption.weight(.semibold)).foregroundStyle(KColor.secondary) }
            Chart {
                ForEach(cashflow.value) { month in
                    BarMark(x: .value("Monat", month.label), y: .value("Betrag", month.income)).foregroundStyle(KColor.accentStrong).cornerRadius(5)
                    BarMark(x: .value("Monat", month.label), y: .value("Betrag", month.expense)).foregroundStyle(KColor.negative.opacity(0.78)).cornerRadius(5)
                }
            }
            .chartYAxis(.hidden)
            .chartXAxis { AxisMarks { AxisValueLabel().foregroundStyle(KColor.secondary) } }
            .frame(height: 170)
            HStack(spacing: 14) {
                Label("Einnahmen", systemImage: "circle.fill").foregroundStyle(KColor.accentStrong)
                Label("Ausgaben", systemImage: "circle.fill").foregroundStyle(KColor.negative)
            }.font(.caption2.weight(.semibold))
        }
        .kCard(KSpacing.md)
    }

    private var upcoming: some View {
        VStack(alignment: .leading, spacing: KSpacing.md) {
            KSectionHeader(title: "Als Nächstes")
            VStack(spacing: 0) {
                ForEach(upcomingEvents.value) { event in
                    KRow(title: event.title, subtitle: event.start)
                    if event.id != upcomingEvents.value.last?.id { Divider().overlay(KColor.divider) }
                }
            }.kCard(KSpacing.md)
        }
    }

    private var tasks: some View {
        VStack(alignment: .leading, spacing: KSpacing.md) {
            KSectionHeader(title: "Aufgaben")
            VStack(spacing: 0) {
                ForEach(dueTodos.value.prefix(4)) { todo in
                    KRow(title: todo.title, trailing: todo.due_date, trailingTint: KColor.warning)
                    if todo.id != dueTodos.value.prefix(4).last?.id { Divider().overlay(KColor.divider) }
                }
            }.kCard(KSpacing.md)
        }
    }

    private var greeting: String {
        switch Calendar.current.component(.hour, from: Date()) { case 5..<11: return "Guten Morgen"; case 11..<18: return "Guten Tag"; default: return "Guten Abend" }
    }

    private func icon(for type: String) -> String {
        switch type.lowercased() { case let t where t.contains("spar"): return "banknote"; case let t where t.contains("kredit") || t.contains("credit"): return "creditcard"; case let t where t.contains("bar") || t.contains("cash"): return "wallet.pass"; case let t where t.contains("depot") || t.contains("invest"): return "chart.line.uptrend.xyaxis"; default: return "building.columns" }
    }

    private func reload() {
        let db = AppDatabase.shared
        netWorth.value = (try? db.read { db in try Queries.netWorth(db) }) ?? 0
        netSeries.value = (try? db.read { db in try Queries.netWorthSeries(db, days: range) }) ?? []
        accountRows.value = (try? db.read { db in try Account.order(Column("name")).fetchAll(db).map { ($0, try Queries.accountBalance(db, accountID: $0.id)) } }) ?? []
        recentTx.value = (try? db.read { db in try TransactionRecord.order(Column("date").desc).limit(6).fetchAll(db) }) ?? []
        dueTodos.value = (try? db.read { db in try Todo.filter(Column("done") == false).order(Column("due_date")).limit(5).fetchAll(db) }) ?? []
        upcomingEvents.value = (try? db.read { db in try CalendarEvent.order(Column("start")).limit(4).fetchAll(db) }) ?? []
        let flow = (try? db.read { db in try Queries.currentMonthCashflow(db) }) ?? (income: 0, expense: 0)
        monthIncome.value = flow.income
        monthExpense.value = flow.expense
        cashflow.value = (try? db.read { db in try Queries.monthlyCashflow(db, months: 6) }) ?? []
    }
}

struct NeonRangeButton: ButtonStyle {
    let active: Bool
    func makeBody(configuration: ButtonStyle.Configuration) -> some View {
        let pressed = configuration.isPressed
        return configuration.label
            .font(.caption.weight(.bold))
            .foregroundStyle(active ? KColor.accentInk : KColor.secondary)
            .padding(.horizontal, 10).padding(.vertical, 6)
            .background(active ? KColor.accent : KColor.surfaceSoft, in: Capsule())
            .overlay(Capsule().stroke(active ? KColor.accent : KColor.divider, lineWidth: 1))
            .scaleEffect(pressed ? 0.96 : 1)
    }
}

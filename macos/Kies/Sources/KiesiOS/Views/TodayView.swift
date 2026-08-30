import SwiftUI
import Charts
import KiesCore
import GRDB

/// Finance-first home screen. No horizontal card carousel, no oversized blank
/// areas: the hierarchy is greeting -> wealth -> monthly pulse -> accounts ->
/// activity. The Alpine image is provided by the fixed screen backdrop.
struct TodayView: View {
    @ObservedObject private var engine = SyncEngine.shared
    @StateObject private var monthIncome = Box(0.0)
    @StateObject private var monthExpense = Box(0.0)
    @StateObject private var cashflow = Box<[Queries.MonthFlow]>([])
    @StateObject private var netWorth = Box(0.0)
    @StateObject private var netSeries = Box<[Queries.DayValue]>([])
    @StateObject private var accountRows = Box<[(account: Account, balance: Double)]>([])
    @StateObject private var recentTx = Box<[TransactionRecord]>([])
    @State private var range = 30
    @State private var showBalance = true

    private var monthNet: Double { monthIncome.value - monthExpense.value }
    private var netDelta: Double {
        guard let first = netSeries.value.first?.value, let last = netSeries.value.last?.value else { return 0 }
        return last - first
    }

    var body: some View {
        KScreen(spacing: 26) {
            header
            wealthHero
            monthPulse
            accountsSection
            activitySection
            cashflowSection
            SyncStatusFooter()
                .font(.caption)
                .foregroundStyle(KColor.secondary)
                .frame(maxWidth: .infinity, alignment: .center)
        }
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

    private var header: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(greeting)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(KColor.secondary)
                Text("Deine Finanzen")
                    .font(KFont.title)
                    .foregroundStyle(KColor.primary)
                Text(Date().formatted(.dateTime.weekday(.wide).day().month(.wide)))
                    .font(.caption.weight(.medium))
                    .foregroundStyle(KColor.tertiary)
            }
            Spacer()
            Circle()
                .fill(KColor.accent)
                .frame(width: 46, height: 46)
                .overlay(
                    Image(systemName: "person.fill")
                        .font(.callout.weight(.bold))
                        .foregroundStyle(KColor.accentInk)
                )
        }
        .padding(.top, 2)
    }

    private var wealthHero: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Gesamtvermögen")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(KColor.secondary)
                    Text(showBalance ? kEUR(netWorth.value, fraction: 2) : "••••••")
                        .font(.system(size: 38, weight: .bold, design: .rounded))
                        .monospacedDigit()
                        .foregroundStyle(KColor.primary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.62)
                }
                Spacer()
                Button {
                    withAnimation(.easeOut(duration: 0.16)) { showBalance.toggle() }
                } label: {
                    Image(systemName: showBalance ? "eye" : "eye.slash")
                        .font(.subheadline.weight(.bold))
                        .foregroundStyle(KColor.secondary)
                        .frame(width: 40, height: 40)
                        .background(KColor.surfaceSoft, in: Circle())
                }
                .buttonStyle(.plain)
            }

            if abs(netDelta) > 0.01 {
                HStack(spacing: 6) {
                    Image(systemName: netDelta >= 0 ? "arrow.up.right" : "arrow.down.right")
                    Text(showBalance ? kEUR(netDelta, fraction: 2) : "••••")
                    Text("· \(range) Tage").foregroundStyle(KColor.secondary)
                }
                .font(.caption.weight(.bold))
                .foregroundStyle(netDelta >= 0 ? KColor.positive : KColor.negative)
            }

            if netSeries.value.count > 1 {
                Chart(netSeries.value) { point in
                    AreaMark(x: .value("Tag", point.date), y: .value("Wert", point.value))
                        .foregroundStyle(
                            .linearGradient(
                                colors: [KColor.accent.opacity(0.55), KColor.accent.opacity(0.02)],
                                startPoint: .top,
                                endPoint: .bottom
                            )
                        )
                        .interpolationMethod(.monotone)
                    LineMark(x: .value("Tag", point.date), y: .value("Wert", point.value))
                        .foregroundStyle(KColor.accentStrong)
                        .lineStyle(.init(lineWidth: 3, lineCap: .round, lineJoin: .round))
                        .interpolationMethod(.monotone)
                }
                .chartXAxis(.hidden)
                .chartYAxis(.hidden)
                .frame(height: 92)
            }

            HStack(spacing: 8) {
                Button("1M") { changeRange(30) }
                    .buttonStyle(NeonRangeButton(active: range == 30))
                Button("3M") { changeRange(90) }
                    .buttonStyle(NeonRangeButton(active: range == 90))
                Spacer()
                Text("Verlauf")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(KColor.tertiary)
            }
        }
        .padding(20)
        .background(
            ZStack(alignment: .trailing) {
                KColor.surface
                Image("AlpenBackground")
                    .resizable()
                    .scaledToFill()
                    .frame(maxWidth: 190, maxHeight: 240)
                    .clipped()
                    .opacity(0.055)
                    .mask(LinearGradient(colors: [.clear, .black], startPoint: .leading, endPoint: .trailing))
            },
            in: RoundedRectangle(cornerRadius: 24, style: .continuous)
        )
        .overlay(RoundedRectangle(cornerRadius: 24, style: .continuous).stroke(KColor.divider, lineWidth: 1))
        .shadow(color: .black.opacity(0.035), radius: 18, x: 0, y: 7)
    }

    private var monthPulse: some View {
        HStack(spacing: 10) {
            pulseMetric("Einnahmen", monthIncome.value, tint: KColor.positive)
            pulseMetric("Ausgaben", monthExpense.value, tint: KColor.negative)
            pulseMetric("Netto", monthNet, tint: monthNet >= 0 ? KColor.positive : KColor.negative)
        }
    }

    private func pulseMetric(_ title: String, _ value: Double, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption2.weight(.bold))
                .foregroundStyle(KColor.secondary)
            Text(showBalance ? kEUR(value) : "••••")
                .font(.system(size: 16, weight: .bold, design: .rounded))
                .monospacedDigit()
                .foregroundStyle(tint)
                .lineLimit(1)
                .minimumScaleFactor(0.65)
        }
        .padding(13)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(KColor.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(KColor.divider, lineWidth: 1))
    }

    private var accountsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            KSectionHeader(title: "Konten", action: ("Alle", { TabRouter.shared.selection = .accounts }))

            if accountRows.value.isEmpty {
                KEmptyState(
                    icon: "creditcard",
                    title: "Noch keine Konten",
                    message: "Synchronisiere Kies, um deine Konten zu sehen.",
                    actionTitle: "Synchronisieren",
                    action: { Task { await engine.run() } }
                )
            } else {
                VStack(spacing: 0) {
                    ForEach(Array(accountRows.value.prefix(5)), id: \.account.id) { row in
                        Button {
                            TabRouter.shared.selection = .accounts
                        } label: {
                            HStack(spacing: 13) {
                                Image(systemName: icon(for: row.account.type))
                                    .font(.subheadline.weight(.bold))
                                    .foregroundStyle(KColor.accentInk)
                                    .frame(width: 40, height: 40)
                                    .background(KColor.accent, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(row.account.name)
                                        .font(.body.weight(.semibold))
                                        .foregroundStyle(KColor.primary)
                                        .lineLimit(1)
                                    Text(row.account.type.capitalized)
                                        .font(.caption)
                                        .foregroundStyle(KColor.secondary)
                                }
                                Spacer()
                                Text(showBalance ? kEUR(row.balance, fraction: 2) : "••••")
                                    .font(.body.weight(.bold))
                                    .monospacedDigit()
                                    .foregroundStyle(row.balance < 0 ? KColor.negative : KColor.primary)
                                    .lineLimit(1)
                                    .minimumScaleFactor(0.7)
                                Image(systemName: "chevron.right")
                                    .font(.caption.weight(.bold))
                                    .foregroundStyle(KColor.tertiary)
                            }
                            .padding(.vertical, 12)
                        }
                        .buttonStyle(.plain)
                        if row.account.id != accountRows.value.prefix(5).last?.account.id {
                            Divider().overlay(KColor.divider)
                        }
                    }
                }
                .padding(.horizontal, 15)
                .background(KColor.surface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(KColor.divider, lineWidth: 1))
            }
        }
    }

    private var activitySection: some View {
        VStack(alignment: .leading, spacing: 12) {
            KSectionHeader(title: "Letzte Buchungen", action: ("Alle", { TabRouter.shared.selection = .transactions }))
            VStack(spacing: 0) {
                ForEach(Array(recentTx.value.prefix(5))) { tx in
                    KTransactionRow(
                        title: tx.description ?? "Buchung",
                        amount: tx.amount,
                        pending: tx.pending_client_id != nil
                    )
                    if tx.id != recentTx.value.prefix(5).last?.id {
                        Divider().overlay(KColor.divider)
                    }
                }
            }
            .padding(.horizontal, 15)
            .background(KColor.surface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(KColor.divider, lineWidth: 1))
        }
    }

    private var cashflowSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Cashflow").font(KFont.sectionH)
                Spacer()
                Text("6 Monate").font(.caption.weight(.semibold)).foregroundStyle(KColor.secondary)
            }

            Chart {
                ForEach(cashflow.value) { month in
                    BarMark(x: .value("Monat", month.label), y: .value("Einnahmen", month.income))
                        .foregroundStyle(KColor.accentStrong)
                        .cornerRadius(4)
                    BarMark(x: .value("Monat", month.label), y: .value("Ausgaben", month.expense))
                        .foregroundStyle(KColor.negative.opacity(0.72))
                        .cornerRadius(4)
                }
            }
            .chartYAxis(.hidden)
            .chartXAxis { AxisMarks { AxisValueLabel().foregroundStyle(KColor.secondary) } }
            .frame(height: 145)
        }
        .padding(18)
        .background(KColor.surface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(KColor.divider, lineWidth: 1))
    }

    private var greeting: String {
        switch Calendar.current.component(.hour, from: Date()) {
        case 5..<11: return "Guten Morgen"
        case 11..<18: return "Guten Tag"
        default: return "Guten Abend"
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

    private func changeRange(_ days: Int) {
        range = days
        reload()
    }

    private func reload() {
        let db = AppDatabase.shared
        netWorth.value = (try? db.read { try Queries.netWorth($0) }) ?? 0
        netSeries.value = (try? db.read { try Queries.netWorthSeries($0, days: range) }) ?? []
        accountRows.value = (try? db.read { db in
            try Account.order(Column("name")).fetchAll(db).map {
                ($0, try Queries.accountBalance(db, accountID: $0.id))
            }
        }) ?? []
        recentTx.value = (try? db.read {
            try TransactionRecord.order(Column("date").desc).limit(6).fetchAll($0)
        }) ?? []
        let flow = (try? db.read { try Queries.currentMonthCashflow($0) }) ?? (income: 0, expense: 0)
        monthIncome.value = flow.income
        monthExpense.value = flow.expense
        cashflow.value = (try? db.read { try Queries.monthlyCashflow($0, months: 6) }) ?? []
    }
}

struct NeonRangeButton: ButtonStyle {
    let active: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.caption.weight(.bold))
            .foregroundStyle(active ? KColor.accentInk : KColor.secondary)
            .padding(.horizontal, 11)
            .padding(.vertical, 7)
            .background(active ? KColor.accent : KColor.surfaceSoft, in: Capsule())
            .overlay(Capsule().stroke(active ? KColor.accent : KColor.divider, lineWidth: 1))
            .scaleEffect(configuration.isPressed ? 0.96 : 1)
    }
}

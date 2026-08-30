import SwiftUI
import Charts
import KiesCore
import GRDB

/// Premium banking-style dashboard. It deliberately avoids a card-per-section
/// layout: one hero, horizontal account rail, transaction feed and a compact
/// monthly pulse. The chart is interactive and all navigation remains native.
struct PremiumTodayView: View {
    @ObservedObject private var engine = SyncEngine.shared
    @StateObject private var netWorth = Box(0.0)
    @StateObject private var netSeries = Box<[Queries.DayValue]>([])
    @StateObject private var accounts = Box<[(account: Account, balance: Double)]>([])
    @StateObject private var transactions = Box<[TransactionRecord]>([])
    @StateObject private var monthIncome = Box(0.0)
    @StateObject private var monthExpense = Box(0.0)
    @State private var period = 30
    @State private var selectedPoint: Queries.DayValue?
    @State private var showQuickCapture = false
    @State private var showBalanceDetails = false

    private var monthNet: Double { monthIncome.value - monthExpense.value }
    private var firstValue: Double { netSeries.value.first?.value ?? netWorth.value }
    private var netDelta: Double { netWorth.value - firstValue }
    private var netDeltaPercent: Double {
        guard abs(firstValue) > 0.01 else { return 0 }
        return netDelta / abs(firstValue) * 100
    }

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(alignment: .leading, spacing: 30) {
                header
                wealthHero
                accountsSection
                transactionsSection
                monthPulse
            }
            .padding(.horizontal, 20)
            .padding(.top, 10)
            .padding(.bottom, 120)
        }
        .background(KColor.background.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
        .refreshable { await engine.run() }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .sheet(isPresented: $showQuickCapture) {
            QuickCaptureView()
        }
        .sheet(isPresented: $showBalanceDetails) {
            NavigationStack {
                PremiumBalanceDetailView(series: netSeries.value, current: netWorth.value)
                    .navigationTitle("Vermögen")
                    .navigationBarTitleDisplayMode(.inline)
            }
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        }
    }

    private var header: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 3) {
                Text(greeting)
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(KColor.secondary)
                Text("Deine Finanzen")
                    .font(.system(size: 29, weight: .bold, design: .rounded))
                    .foregroundStyle(KColor.primary)
            }
            Spacer()
            HStack(spacing: 9) {
                NavigationLink { SettingsView() } label: {
                    Image(systemName: "gearshape")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(KColor.primary)
                        .frame(width: 40, height: 40)
                        .background(.ultraThinMaterial, in: Circle())
                }
                Button { showQuickCapture = true } label: {
                    Image(systemName: "plus")
                        .font(.system(size: 17, weight: .bold))
                        .foregroundStyle(.white)
                        .frame(width: 40, height: 40)
                        .background(KColor.accent, in: Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Schnell erfassen")
            }
        }
    }

    private var wealthHero: some View {
        VStack(alignment: .leading, spacing: 17) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("GESAMTVERMÖGEN")
                        .font(.system(size: 10, weight: .bold))
                        .tracking(1.3)
                        .foregroundStyle(KColor.secondary)
                    Button { showBalanceDetails = true } label: {
                        HStack(alignment: .firstTextBaseline, spacing: 7) {
                            Text(kEUR(netWorth.value, fraction: 2))
                                .font(.system(size: 42, weight: .bold, design: .rounded).monospacedDigit())
                                .foregroundStyle(KColor.primary)
                                .minimumScaleFactor(0.55)
                                .lineLimit(1)
                            Image(systemName: "arrow.up.right")
                                .font(.caption.weight(.bold))
                                .foregroundStyle(KColor.secondary)
                        }
                    }
                    .buttonStyle(.plain)
                }
                Spacer()
                if abs(netDelta) > 0.01 {
                    VStack(alignment: .trailing, spacing: 3) {
                        Text(String(format: "%+.1f %%", netDeltaPercent))
                            .font(.caption.weight(.bold))
                            .foregroundStyle(netDelta >= 0 ? KColor.positive : KColor.negative)
                        Text("in \(period) Tagen")
                            .font(.caption2)
                            .foregroundStyle(KColor.secondary)
                    }
                }
            }

            if let selectedPoint {
                HStack(spacing: 7) {
                    Circle().fill(KColor.accent).frame(width: 6, height: 6)
                    Text(selectedPoint.date.formatted(.dateTime.day().month(.abbreviated)))
                    Text(kEUR(selectedPoint.value, fraction: 2))
                        .fontWeight(.semibold)
                        .monospacedDigit()
                }
                .font(.caption)
                .foregroundStyle(KColor.secondary)
                .transition(.opacity)
            }

            if netSeries.value.count > 1 {
                Chart(netSeries.value) { point in
                    AreaMark(x: .value("Datum", point.date), y: .value("Vermögen", point.value))
                        .foregroundStyle(
                            .linearGradient(
                                colors: [KColor.accent.opacity(0.28), KColor.accent.opacity(0.015)],
                                startPoint: .top,
                                endPoint: .bottom
                            )
                        )
                        .interpolationMethod(.catmullRom)
                    LineMark(x: .value("Datum", point.date), y: .value("Vermögen", point.value))
                        .foregroundStyle(KColor.accent)
                        .lineStyle(StrokeStyle(lineWidth: 2.6, lineCap: .round, lineJoin: .round))
                        .interpolationMethod(.catmullRom)
                    if selectedPoint?.date == point.date {
                        PointMark(x: .value("Datum", point.date), y: .value("Vermögen", point.value))
                            .foregroundStyle(KColor.primary)
                            .symbolSize(48)
                    }
                }
                .chartXAxis(.hidden)
                .chartYAxis(.hidden)
                .chartPlotStyle { plot in plot.clipped() }
                .frame(height: 108)
                .chartOverlay { proxy in
                    GeometryReader { geometry in
                        Rectangle().fill(.clear).contentShape(Rectangle())
                            .gesture(
                                DragGesture(minimumDistance: 0)
                                    .onChanged { value in
                                        let origin = geometry[proxy.plotAreaFrame].origin
                                        let x = value.location.x - origin.x
                                        guard let date: Date = proxy.value(atX: x) else { return }
                                        selectedPoint = netSeries.value.min {
                                            abs($0.date.timeIntervalSince(date)) < abs($1.date.timeIntervalSince(date))
                                        }
                                    }
                                    .onEnded { _ in
                                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                                            withAnimation(.easeOut(duration: 0.2)) { selectedPoint = nil }
                                        }
                                    }
                            )
                    }
                }
            }

            HStack(spacing: 6) {
                ForEach([(7, "1W"), (30, "1M"), (90, "3M")], id: \.0) { days, label in
                    Button {
                        withAnimation(.easeOut(duration: 0.18)) {
                            period = days
                            reloadSeries(days: days)
                        }
                    } label: {
                        Text(label)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(period == days ? .white : KColor.secondary)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 7)
                            .background(period == days ? KColor.accent : KColor.surfaceSecondary, in: Capsule())
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .padding(20)
        .background(
            LinearGradient(
                colors: [KColor.surface, KColor.surfaceSecondary.opacity(0.62)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            ),
            in: RoundedRectangle(cornerRadius: 26, style: .continuous)
        )
        .overlay {
            RoundedRectangle(cornerRadius: 26, style: .continuous)
                .stroke(KColor.primary.opacity(0.055), lineWidth: 1)
        }
    }

    private var accountsSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionHeader("Konten") { TabRouter.shared.selection = .accounts }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 12) {
                    ForEach(accounts.value.prefix(6), id: \.account.id) { row in
                        Button { TabRouter.shared.selection = .accounts } label: {
                            accountCard(row.account, balance: row.balance)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .contentMargins(.trailing, 4, for: .scrollContent)
        }
    }

    private func accountCard(_ account: Account, balance: Double) -> some View {
        VStack(alignment: .leading, spacing: 19) {
            HStack {
                Image(systemName: icon(for: account.type))
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(KColor.accent)
                    .frame(width: 32, height: 32)
                    .background(KColor.accent.opacity(0.11), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                Spacer()
                Image(systemName: "arrow.up.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(KColor.secondary)
            }
            VStack(alignment: .leading, spacing: 5) {
                Text(account.name)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(KColor.primary)
                    .lineLimit(1)
                Text(kEUR(balance, fraction: 2))
                    .font(.system(size: 21, weight: .bold, design: .rounded).monospacedDigit())
                    .foregroundStyle(balance < 0 ? KColor.negative : KColor.primary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            }
        }
        .padding(16)
        .frame(width: 184, height: 136, alignment: .topLeading)
        .background(KColor.surface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .stroke(KColor.primary.opacity(0.045), lineWidth: 1)
        }
    }

    private var transactionsSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionHeader("Letzte Transaktionen") { TabRouter.shared.selection = .transactions }
            VStack(spacing: 0) {
                ForEach(Array(transactions.value.prefix(6))) { tx in
                    Button { TabRouter.shared.selection = .transactions } label: {
                        HStack(spacing: 13) {
                            Image(systemName: transactionIcon(tx.description ?? "", amount: tx.amount))
                                .font(.system(size: 13, weight: .semibold))
                                .foregroundStyle(tx.amount > 0 ? KColor.positive : KColor.secondary)
                                .frame(width: 38, height: 38)
                                .background(KColor.surfaceSecondary, in: Circle())
                            VStack(alignment: .leading, spacing: 3) {
                                Text(tx.description ?? "Buchung")
                                    .font(.subheadline.weight(.medium))
                                    .foregroundStyle(KColor.primary)
                                    .lineLimit(1)
                                Text(transactionDate(tx.date))
                                    .font(.caption)
                                    .foregroundStyle(KColor.secondary)
                            }
                            Spacer(minLength: 8)
                            Text(kEUR(tx.amount, fraction: 2))
                                .font(.subheadline.weight(.semibold).monospacedDigit())
                                .foregroundStyle(tx.amount > 0 ? KColor.positive : KColor.primary)
                        }
                        .contentShape(Rectangle())
                        .padding(.vertical, 9)
                    }
                    .buttonStyle(.plain)
                    if tx.id != transactions.value.prefix(6).last?.id {
                        Divider().overlay(KColor.divider.opacity(0.7))
                    }
                }
            }
        }
    }

    private var monthPulse: some View {
        VStack(alignment: .leading, spacing: 17) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Diesen Monat")
                        .font(.headline.weight(.semibold))
                        .foregroundStyle(KColor.primary)
                    Text("Cashflow")
                        .font(.caption)
                        .foregroundStyle(KColor.secondary)
                }
                Spacer()
                Text(kEUR(monthNet, fraction: 0))
                    .font(.system(size: 22, weight: .bold, design: .rounded).monospacedDigit())
                    .foregroundStyle(monthNet >= 0 ? KColor.positive : KColor.negative)
            }
            HStack(spacing: 20) {
                pulseMetric("Einnahmen", monthIncome.value, KColor.positive, "arrow.down.left")
                pulseMetric("Ausgaben", monthExpense.value, KColor.negative, "arrow.up.right")
            }
        }
        .padding(18)
        .background(KColor.surfaceSecondary.opacity(0.72), in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    private func pulseMetric(_ title: String, _ value: Double, _ tint: Color, _ symbol: String) -> some View {
        HStack(spacing: 9) {
            Image(systemName: symbol)
                .font(.caption.weight(.bold))
                .foregroundStyle(tint)
                .frame(width: 29, height: 29)
                .background(tint.opacity(0.11), in: Circle())
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.caption).foregroundStyle(KColor.secondary)
                Text(kEUR(value, fraction: 0))
                    .font(.subheadline.weight(.semibold).monospacedDigit())
                    .foregroundStyle(KColor.primary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func sectionHeader(_ title: String, action: @escaping () -> Void) -> some View {
        HStack {
            Text(title)
                .font(.headline.weight(.semibold))
                .foregroundStyle(KColor.primary)
            Spacer()
            Button("Alle", action: action)
                .font(.caption.weight(.semibold))
                .foregroundStyle(KColor.accent)
        }
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
        case let value where value.contains("spar"): return "banknote"
        case let value where value.contains("kredit") || value.contains("credit"): return "creditcard"
        case let value where value.contains("bar") || value.contains("cash"): return "wallet.pass"
        case let value where value.contains("depot") || value.contains("invest"): return "chart.line.uptrend.xyaxis"
        default: return "building.columns"
        }
    }

    private func transactionIcon(_ title: String, amount: Double) -> String {
        let value = title.lowercased()
        if value.contains("rewe") || value.contains("edeka") || value.contains("aldi") || value.contains("lidl") { return "cart.fill" }
        if value.contains("amazon") || value.contains("paypal") { return "bag.fill" }
        if value.contains("tank") || value.contains("oil") || value.contains("shell") || value.contains("aral") { return "fuelpump.fill" }
        if value.contains("gehalt") || value.contains("lohn") { return "arrow.down.circle.fill" }
        return amount > 0 ? "arrow.down.left" : "arrow.up.right"
    }

    private func transactionDate(_ value: String?) -> String {
        guard let value else { return "" }
        guard let date = DateFormatter.parseServerDateTime(value) else { return value }
        return date.formatted(.dateTime.day().month(.abbreviated))
    }

    private func reload() {
        let db = AppDatabase.shared
        netWorth.value = (try? db.read { try Queries.netWorth($0) }) ?? 0
        accounts.value = (try? db.read { db in
            try Account.order(Column("name")).fetchAll(db).map { account in
                (account, try Queries.accountBalance(db, accountID: account.id))
            }
        }) ?? []
        transactions.value = (try? db.read { try TransactionRecord.order(Column("date").desc).limit(6).fetchAll($0) }) ?? []
        let flow = (try? db.read { try Queries.currentMonthCashflow($0) }) ?? (income: 0, expense: 0)
        monthIncome.value = flow.income
        monthExpense.value = flow.expense
        reloadSeries(days: period)
    }

    private func reloadSeries(days: Int) {
        netSeries.value = (try? AppDatabase.shared.read { try Queries.netWorthSeries($0, days: days) }) ?? []
    }
}

private struct PremiumBalanceDetailView: View {
    let series: [Queries.DayValue]
    let current: Double

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(alignment: .leading, spacing: 24) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Aktuelles Vermögen")
                        .font(.subheadline)
                        .foregroundStyle(KColor.secondary)
                    Text(kEUR(current, fraction: 2))
                        .font(.system(size: 38, weight: .bold, design: .rounded).monospacedDigit())
                        .foregroundStyle(KColor.primary)
                }
                if series.count > 1 {
                    Chart(series) { point in
                        LineMark(x: .value("Datum", point.date), y: .value("Vermögen", point.value))
                            .foregroundStyle(KColor.accent)
                            .lineStyle(StrokeStyle(lineWidth: 3, lineCap: .round))
                            .interpolationMethod(.catmullRom)
                    }
                    .chartXAxis { AxisMarks(values: .automatic(desiredCount: 4)) }
                    .chartYAxis { AxisMarks(position: .leading) }
                    .frame(height: 220)
                }
            }
            .padding(20)
        }
        .background(KColor.background.ignoresSafeArea())
    }
}

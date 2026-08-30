import SwiftUI
import Charts
import KiesCore
import GRDB

/// Übersichts-Screen: Hero mit Gesamtvermögen + Monatsdelta + Mini-Verlauf,
/// darunter kompakte Konten-Liste, letzte Transaktionen, ein Insight und die
/// bisherigen Abschnitte (Cashflow, Termine, Todos, Ziele, Fristen, Check-ins)
/// im neuen ruhigen Look. Kein Bearbeiten hier - dafür die jeweiligen Tabs.
struct TodayView: View {
    @ObservedObject var engine = SyncEngine.shared
    @StateObject private var dueTodos = Box<[Todo]>([])
    @StateObject private var upcomingEvents = Box<[CalendarEvent]>([])
    @StateObject private var monthIncome = Box(0.0)
    @StateObject private var monthExpense = Box(0.0)
    @StateObject private var cashflow = Box<[Queries.MonthFlow]>([])
    @StateObject private var nearGoals = Box<[Goal]>([])
    @StateObject private var uncheckedAreas = Box<[LifeArea]>([])
    @StateObject private var deadlines = Box<[String]>([])
    @StateObject private var netWorth = Box(0.0)
    @StateObject private var netSeries = Box<[Queries.DayValue]>([])
    @StateObject private var accountRows = Box<[(account: Account, balance: Double)]>([])
    @StateObject private var recentTx = Box<[TransactionRecord]>([])
    @State private var editEvent: CalendarEvent?

    private var monthNet: Double { monthIncome.value - monthExpense.value }
    private var netDelta: Double {
        guard let first = netSeries.value.first?.value, let last = netSeries.value.last?.value else { return 0 }
        return last - first
    }

    var body: some View {
        KScreen {
            header

            if !engine.conflicts.isEmpty {
                NavigationLink { ConflictsView() } label: {
                    HStack {
                        Label(
                            engine.conflicts.count == 1 ? "1 Sync-Konflikt" : "\(engine.conflicts.count) Sync-Konflikte",
                            systemImage: "exclamationmark.triangle.fill"
                        )
                        .font(.subheadline.weight(.semibold))
                        Spacer()
                        Image(systemName: "chevron.right").font(.caption)
                    }
                    .foregroundStyle(KColor.warning)
                    .kCard()
                }
                .buttonStyle(.plain)
            }

            heroCard

            if !accountRows.value.isEmpty {
                VStack(alignment: .leading, spacing: KSpacing.sm) {
                    KSectionHeader(title: "Konten",
                                  action: ("Alle", { TabRouter.shared.selection = .accounts }))
                    VStack(spacing: 0) {
                        ForEach(Array(accountRows.value.prefix(5)), id: \.account.id) { row in
                            KAccountRow(icon: icon(for: row.account.type),
                                        name: row.account.name,
                                        subtitle: row.account.type.capitalized,
                                        amount: row.balance)
                            if row.account.id != accountRows.value.prefix(5).last?.account.id {
                                Divider().overlay(KColor.divider)
                            }
                        }
                    }
                    .kCard(KSpacing.md)
                }
            }

            if !recentTx.value.isEmpty {
                VStack(alignment: .leading, spacing: KSpacing.sm) {
                    KSectionHeader(title: "Letzte Transaktionen",
                                  action: ("Alle", { TabRouter.shared.selection = .transactions }))
                    VStack(spacing: 0) {
                        ForEach(Array(recentTx.value.prefix(6))) { tx in
                            KTransactionRow(title: tx.description ?? "–",
                                            subtitle: nil,
                                            amount: tx.amount,
                                            pending: tx.pending_client_id != nil)
                            if tx.id != recentTx.value.prefix(6).last?.id {
                                Divider().overlay(KColor.divider)
                            }
                        }
                    }
                    .kCard(KSpacing.md)
                }
            }

            KInsightCard(
                icon: "chart.line.uptrend.xyaxis",
                title: "Diesen Monat",
                message: "Einnahmen \(kEUR(monthIncome.value)) · Ausgaben \(kEUR(monthExpense.value)) · Netto \(kEUR(monthNet)).",
                actionTitle: "Analyse öffnen",
                action: { TabRouter.shared.selection = .more }
            )

            if cashflow.value.contains(where: { $0.income > 0 || $0.expense > 0 }) {
                KSection(title: "Cashflow · 6 Monate", systemImage: "chart.bar") {
                    Chart {
                        ForEach(cashflow.value) { m in
                            BarMark(x: .value("Monat", m.label), y: .value("Betrag", m.income))
                                .position(by: .value("Art", "Einnahmen"))
                                .foregroundStyle(by: .value("Art", "Einnahmen"))
                            BarMark(x: .value("Monat", m.label), y: .value("Betrag", m.expense))
                                .position(by: .value("Art", "Ausgaben"))
                                .foregroundStyle(by: .value("Art", "Ausgaben"))
                        }
                    }
                    .chartForegroundStyleScale(["Einnahmen": KColor.positive, "Ausgaben": KColor.negative])
                    .chartLegend(position: .bottom, spacing: 8)
                    .chartYAxis { AxisMarks { AxisValueLabel() } }
                    .frame(height: 150)
                }
            }

            if !upcomingEvents.value.isEmpty {
                KSection(title: "Nächste Termine", systemImage: "calendar") {
                    VStack(spacing: KSpacing.sm) {
                        ForEach(upcomingEvents.value) { event in
                            KRow(title: event.title, subtitle: eventSubtitle(event))
                                .contentShape(Rectangle())
                                .onTapGesture { if event.id > 0 { editEvent = event } }
                        }
                    }
                }
            }

            KSection(title: "Fällige Aufgaben", systemImage: "checklist") {
                if dueTodos.value.isEmpty {
                    Text("Nichts fällig – alles erledigt.").font(.callout).foregroundStyle(KColor.secondary)
                } else {
                    VStack(spacing: KSpacing.sm) {
                        ForEach(dueTodos.value) { todo in
                            let overdue = (todo.due_date ?? "") < DateFormatter.isoDate.string(from: Date()) && todo.due_date != nil
                            KRow(title: todo.title, trailing: todo.due_date,
                                 trailingTint: overdue ? KColor.negative : KColor.secondary)
                        }
                    }
                }
            }

            if !nearGoals.value.isEmpty {
                KSection(title: "Ziele in Reichweite", systemImage: "target") {
                    VStack(spacing: KSpacing.sm) {
                        ForEach(nearGoals.value) { goal in
                            KRow(title: goal.title, trailing: goal.target_date, trailingTint: KColor.secondary)
                        }
                    }
                }
            }

            if !deadlines.value.isEmpty {
                KSection(title: "Fristen", systemImage: "clock.badge.exclamationmark") {
                    VStack(alignment: .leading, spacing: KSpacing.sm) {
                        ForEach(deadlines.value, id: \.self) { text in
                            Text(text).font(.callout).foregroundStyle(KColor.primary)
                        }
                    }
                }
            }

            if !uncheckedAreas.value.isEmpty {
                KSection(title: "Ohne Check-in heute", systemImage: "heart.text.square") {
                    Text(uncheckedAreas.value.map(\.name).joined(separator: " · "))
                        .font(.callout).foregroundStyle(KColor.secondary)
                }
            }

            SyncStatusFooter()
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, KSpacing.xs)
        }
        .navigationTitle("Übersicht")
        .toolbar {
            SyncStatusToolbarItem()
            ToolbarItem(placement: .topBarLeading) {
                NavigationLink { SettingsView() } label: { Image(systemName: "gearshape") }
            }
        }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
        .sheet(item: $editEvent) { event in
            CalendarEventEditorSheet(event: event) { reload() }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Übersicht").font(KFont.title).foregroundStyle(KColor.primary)
            Text(Date().formatted(.dateTime.weekday(.wide).day().month(.wide)))
                .font(.subheadline).foregroundStyle(KColor.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.top, KSpacing.xs)
    }

    private var heroCard: some View {
        VStack(alignment: .leading, spacing: KSpacing.sm) {
            Text("Gesamtvermögen").font(.footnote).foregroundStyle(KColor.secondary)
            Text(kEUR(netWorth.value))
                .font(KFont.hero)
                .foregroundStyle(netWorth.value < 0 ? KColor.negative : KColor.primary)
                .lineLimit(1).minimumScaleFactor(0.5)
            if abs(netDelta) > 0.5 {
                let base = abs(netWorth.value - netDelta)
                HStack(spacing: KSpacing.xs) {
                    Image(systemName: netDelta >= 0 ? "arrow.up.right" : "arrow.down.right")
                    Text("\(netDelta >= 0 ? "+" : "")\(kEUR(netDelta))")
                        .monospacedDigit()
                    if base > 1 {
                        Text("\(netDelta >= 0 ? "+" : "")\(netDelta / base * 100, format: .number.precision(.fractionLength(1)))\u{00A0}%")
                            .foregroundStyle(KColor.secondary)
                    }
                    Text("· 30 Tage").foregroundStyle(KColor.secondary)
                }
                .font(.footnote.weight(.medium))
                .foregroundStyle(netDelta >= 0 ? KColor.positive : KColor.negative)
            }
            if netSeries.value.count > 1 {
                Chart(netSeries.value) { p in
                    AreaMark(x: .value("Tag", p.date), y: .value("Wert", p.value))
                        .foregroundStyle(.linearGradient(colors: [KColor.accent.opacity(0.22), KColor.accent.opacity(0.0)],
                                                         startPoint: .top, endPoint: .bottom))
                        .interpolationMethod(.monotone)
                    LineMark(x: .value("Tag", p.date), y: .value("Wert", p.value))
                        .foregroundStyle(KColor.accent)
                        .interpolationMethod(.monotone)
                }
                .chartXAxis(.hidden).chartYAxis(.hidden)
                .frame(height: 56)
                .padding(.top, KSpacing.xs)
            }
        }
        .kCard(KSpacing.lg)
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

    private var greeting: String {
        switch Calendar.current.component(.hour, from: Date()) {
        case 5..<11: return "Guten Morgen"
        case 11..<18: return "Guten Tag"
        default: return "Guten Abend"
        }
    }

    private func eventSubtitle(_ event: CalendarEvent) -> String {
        let startDisplay: String
        if event.all_day {
            startDisplay = "ganztägig"
        } else if let date = DateFormatter.parseServerDateTime(event.start) {
            startDisplay = DateFormatter.eventDisplay.string(from: date)
        } else {
            startDisplay = event.start
        }
        var parts: [String] = [startDisplay]
        if let location = event.location, !location.isEmpty { parts.append(location) }
        return parts.joined(separator: " · ")
    }

    private func reload() {
        let db = AppDatabase.shared
        let today = DateFormatter.isoDate.string(from: Date())

        netWorth.value = (try? db.read { db in try Queries.netWorth(db) }) ?? 0
        netSeries.value = (try? db.read { db in try Queries.netWorthSeries(db, days: 30) }) ?? []
        accountRows.value = (try? db.read { db in
            try Account.order(Column("name")).fetchAll(db).map { acc in
                (acc, try Queries.accountBalance(db, accountID: acc.id))
            }
        }) ?? []
        recentTx.value = (try? db.read { db in
            try TransactionRecord.order(Column("date").desc).limit(6).fetchAll(db)
        }) ?? []

        dueTodos.value = (try? db.read { db in
            try Todo.filter(Column("done") == false)
                .filter(Column("due_date") <= today || Column("due_date") == nil)
                .order(Column("due_date"))
                .fetchAll(db)
        }) ?? []
        upcomingEvents.value = (try? db.read { db in
            try CalendarEvent.filter(Column("start") >= today)
                .order(Column("start"))
                .limit(5)
                .fetchAll(db)
        }) ?? []

        let flow = (try? db.read { db in try Queries.currentMonthCashflow(db) }) ?? (income: 0, expense: 0)
        monthIncome.value = flow.income
        monthExpense.value = flow.expense
        cashflow.value = (try? db.read { db in try Queries.monthlyCashflow(db, months: 6) }) ?? []

        let cutoff = DateFormatter.isoDate.string(from: Date().addingTimeInterval(60 * 24 * 60 * 60))
        nearGoals.value = ((try? db.read { db in try Queries.goalsNearTarget(db, limit: 20) }) ?? [])
            .filter { ($0.target_date ?? "") <= cutoff && $0.target_date != nil }
            .prefix(3)
            .map { $0 }
        uncheckedAreas.value = (try? db.read { db in try Queries.lifeAreasWithoutCheckinToday(db) }) ?? []

        let contracts = (try? db.read { db in try Queries.contractRemindersDueSoon(db) }) ?? []
        let returns = (try? db.read { db in try Queries.returnDeadlinesDueSoon(db) }) ?? []
        var texts = contracts.map { "Kündigung: \($0.label) – bis \($0.renewal_date)" }
        for r in returns {
            let txDescription = (try? db.read { db -> String? in
                guard let txID = r.transaction_id else { return nil }
                return try TransactionRecord.fetchOne(db, key: txID)?.description
            }) ?? nil
            texts.append("Rückgabe: \(txDescription ?? "Buchung") – \(r.deadline_days) Tage ab \(r.start_date)")
        }
        deadlines.value = texts
    }
}

/// Bearbeitet einen bestehenden Termin (Titel/Beginn/Ende/Ort/ganztägig).
/// Neue Termine anlegen bleibt der Web-App vorbehalten - calendar_events hat
/// lokal keine pending_client_id-Spalte für den Offline-Anlege-Fall.
struct CalendarEventEditorSheet: View {
    let event: CalendarEvent
    let onSaved: () -> Void
    @Environment(\.dismiss) private var dismiss

    @State private var title = ""
    @State private var allDay = false
    @State private var start = Date()
    @State private var hasEnd = false
    @State private var end = Date()
    @State private var location = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("Termin") {
                    TextField("Titel", text: $title)
                    TextField("Ort (optional)", text: $location)
                }
                Section {
                    Toggle("Ganztägig", isOn: $allDay)
                    DatePicker("Beginn", selection: $start,
                               displayedComponents: allDay ? .date : [.date, .hourAndMinute])
                    Toggle("Ende festlegen", isOn: $hasEnd)
                    if hasEnd {
                        DatePicker("Ende", selection: $end,
                                   displayedComponents: allDay ? .date : [.date, .hourAndMinute])
                    }
                }
            }
            .navigationTitle("Termin bearbeiten")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Abbrechen") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Speichern") { save() }
                        .disabled(title.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .onAppear(perform: prime)
        }
    }

    private func prime() {
        title = event.title
        allDay = event.all_day
        location = event.location ?? ""
        if let d = DateFormatter.parseServerDateTime(event.start) { start = d }
        if let e = event.end, let d = DateFormatter.parseServerDateTime(e) {
            hasEnd = true
            end = d
        }
    }

    private func save() {
        let t = title.trimmingCharacters(in: .whitespacesAndNewlines)
        let loc = location.trimmingCharacters(in: .whitespacesAndNewlines)
        try? SyncEngine.shared.updateCalendarEventOffline(
            id: event.id,
            title: t,
            start: DateFormatter.serverDateTime(start),
            end: hasEnd ? DateFormatter.serverDateTime(end) : nil,
            location: loc.isEmpty ? nil : loc,
            allDay: allDay
        )
        dismiss()
        onSaved()
        Task { await SyncEngine.shared.run() }
    }
}

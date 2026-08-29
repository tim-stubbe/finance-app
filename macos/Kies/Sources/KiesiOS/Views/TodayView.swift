import SwiftUI
import Charts
import KiesCore
import GRDB

/// Tagesübersicht als Karten-Screen: Monats-Cashflow (Kacheln + 6-Monats-
/// Balken), dann fällige Todos, nächste Termine, Ziele, Fristen und offene
/// Check-ins als kompakte Abschnitts-Karten. Kein Bearbeiten hier - dafür
/// die jeweiligen Tabs.
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

    private var monthNet: Double { monthIncome.value - monthExpense.value }

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
                    .foregroundStyle(.orange)
                    .kCard()
                }
                .buttonStyle(.plain)
            }

            HStack(spacing: KTheme.gap) {
                KStatTile(label: "Einnahmen", value: kEUR(monthIncome.value), tint: KTheme.positive)
                KStatTile(label: "Ausgaben", value: kEUR(monthExpense.value), tint: KTheme.negative)
                KStatTile(label: "Netto", value: kEUR(monthNet),
                          tint: monthNet < 0 ? KTheme.negative : .primary)
            }

            if cashflow.value.contains(where: { $0.income > 0 || $0.expense > 0 }) {
                KSection(title: "Cashflow 6 Monate", systemImage: "chart.bar") {
                    Chart {
                        ForEach(cashflow.value) { m in
                            BarMark(x: .value("Monat", m.label),
                                    y: .value("Betrag", m.income))
                                .position(by: .value("Art", "Einnahmen"))
                                .foregroundStyle(by: .value("Art", "Einnahmen"))
                            BarMark(x: .value("Monat", m.label),
                                    y: .value("Betrag", m.expense))
                                .position(by: .value("Art", "Ausgaben"))
                                .foregroundStyle(by: .value("Art", "Ausgaben"))
                        }
                    }
                    .chartForegroundStyleScale(["Einnahmen": KTheme.positive, "Ausgaben": KTheme.negative])
                    .chartLegend(position: .bottom, spacing: 8)
                    .frame(height: 150)
                }
            }

            if !upcomingEvents.value.isEmpty {
                KSection(title: "Nächste Termine", systemImage: "calendar") {
                    VStack(spacing: 10) {
                        ForEach(upcomingEvents.value) { event in
                            KRow(title: event.title, subtitle: eventSubtitle(event))
                        }
                    }
                }
            }

            KSection(title: "Fällige Todos", systemImage: "checklist") {
                if dueTodos.value.isEmpty {
                    Text("Nichts fällig 🎉").font(.callout).foregroundStyle(.secondary)
                } else {
                    VStack(spacing: 10) {
                        ForEach(dueTodos.value) { todo in
                            let overdue = (todo.due_date ?? "") < DateFormatter.isoDate.string(from: Date()) && todo.due_date != nil
                            KRow(title: todo.title,
                                 trailing: todo.due_date,
                                 trailingTint: overdue ? KTheme.negative : .secondary)
                        }
                    }
                }
            }

            if !nearGoals.value.isEmpty {
                KSection(title: "Ziele in Reichweite", systemImage: "target") {
                    VStack(spacing: 10) {
                        ForEach(nearGoals.value) { goal in
                            KRow(title: goal.title, trailing: goal.target_date)
                        }
                    }
                }
            }

            if !deadlines.value.isEmpty {
                KSection(title: "Fristen", systemImage: "clock.badge.exclamationmark") {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(deadlines.value, id: \.self) { text in
                            Text(text).font(.callout)
                        }
                    }
                }
            }

            if !uncheckedAreas.value.isEmpty {
                KSection(title: "Ohne Check-in heute", systemImage: "heart.text.square") {
                    Text(uncheckedAreas.value.map(\.name).joined(separator: " · "))
                        .font(.callout).foregroundStyle(.secondary)
                }
            }

            SyncStatusFooter()
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 4)
        }
        .navigationTitle("Heute")
        .toolbar {
            SyncStatusToolbarItem()
            ToolbarItem(placement: .topBarLeading) {
                NavigationLink { SettingsView() } label: { Image(systemName: "gearshape") }
            }
        }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(greeting).font(.title2.weight(.bold))
            Text(Date().formatted(.dateTime.weekday(.wide).day().month(.wide)))
                .font(.subheadline).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
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

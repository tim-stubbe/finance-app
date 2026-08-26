import SwiftUI
import KiesCore
import GRDB

/// "Heute"-Übersicht fürs macOS-Detail-Pane - macOS-Gegenstück zu
/// KiesiOS/Views/TodayView.swift (dieselben KiesCore-Abfragen, gleicher
/// Inhalt: Tagesbilanz, nächste Termine, fällige Todos, Ziele in
/// Reichweite, Fristen, Lebensbereiche ohne Check-in, Sync-Konflikte).
/// Bisher hatte die macOS-App gar keine Übersichtsseite, nur die einzelnen
/// Bereichs-Listen (siehe ROADMAP.md "macOS-Client nachziehen").
struct TodayListView: View {
    @ObservedObject var engine = SyncEngine.shared
    @ObservedObject private var dueTodos = Box<[Todo]>([])
    @ObservedObject private var upcomingEvents = Box<[CalendarEvent]>([])
    @ObservedObject private var income = Box(0.0)
    @ObservedObject private var expense = Box(0.0)
    @ObservedObject private var nearGoals = Box<[Goal]>([])
    @ObservedObject private var uncheckedAreas = Box<[LifeArea]>([])
    @ObservedObject private var deadlines = Box<[String]>([])

    var body: some View {
        List {
            if !engine.conflicts.isEmpty {
                Section {
                    NavigationLink {
                        ConflictsListView()
                    } label: {
                        Label(
                            engine.conflicts.count == 1 ? "1 Sync-Konflikt" : "\(engine.conflicts.count) Sync-Konflikte",
                            systemImage: "exclamationmark.triangle.fill"
                        )
                        .foregroundStyle(.orange)
                    }
                }
            }

            Section("Tagesbilanz") {
                HStack {
                    Label("Einnahmen", systemImage: "arrow.down.circle").foregroundStyle(.green)
                    Spacer()
                    Text(income.value, format: .currency(code: "EUR"))
                }
                HStack {
                    Label("Ausgaben", systemImage: "arrow.up.circle").foregroundStyle(.red)
                    Spacer()
                    Text(abs(expense.value), format: .currency(code: "EUR"))
                }
            }

            if !upcomingEvents.value.isEmpty {
                Section("Nächste Termine") {
                    ForEach(upcomingEvents.value) { event in
                        VStack(alignment: .leading) {
                            Text(event.title).font(.body)
                            Text(eventSubtitle(event)).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }

            Section("Fällige Todos") {
                if dueTodos.value.isEmpty {
                    Text("Nichts fällig.").foregroundStyle(.secondary)
                } else {
                    ForEach(dueTodos.value) { todo in
                        HStack {
                            Text(todo.title)
                            Spacer()
                            if let due = todo.due_date {
                                let overdue = due < DateFormatter.isoDate.string(from: Date())
                                Text(due).font(.caption).foregroundStyle(overdue ? .red : .secondary)
                            }
                        }
                    }
                }
            }

            if !nearGoals.value.isEmpty {
                Section("Ziele in Reichweite") {
                    ForEach(nearGoals.value) { goal in
                        HStack {
                            Text(goal.title)
                            Spacer()
                            if let targetDate = goal.target_date {
                                Text(targetDate).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }

            if !deadlines.value.isEmpty {
                Section("Fristen") {
                    ForEach(deadlines.value, id: \.self) { text in Text(text) }
                }
            }

            if !uncheckedAreas.value.isEmpty {
                Section("Ohne Check-in heute") {
                    ForEach(uncheckedAreas.value) { area in Text(area.name) }
                }
            }
        }
        .navigationTitle("Heute")
        .toolbar {
            ToolbarItem {
                Button {
                    Task { await engine.run() }
                } label: {
                    if engine.isSyncing {
                        ProgressView().controlSize(.small)
                    } else {
                        Label("Sync", systemImage: "arrow.triangle.2.circlepath")
                    }
                }
                .disabled(engine.isSyncing)
            }
        }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
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
        let balance = (try? db.read { db in try Queries.todayBalance(db) }) ?? (income: 0, expense: 0)
        income.value = balance.income
        expense.value = balance.expense

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

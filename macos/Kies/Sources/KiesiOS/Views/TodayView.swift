import SwiftUI
import KiesCore
import GRDB

/// Einfache Tagesübersicht - fällige Todos, die nächsten Termine (falls
/// bereits synchronisiert) und eine grobe Tagesbilanz aus den heutigen
/// Buchungen. Bewusst nur eine Zusammenfassung, kein eigenes Bearbeiten hier
/// (dafür gibt es die Konten-/Buchungen-/Todos-Tabs).
struct TodayView: View {
    @ObservedObject var engine = SyncEngine.shared
    @ObservedObject private var dueTodos = Box<[Todo]>([])
    @ObservedObject private var upcomingEvents = Box<[CalendarEvent]>([])
    @ObservedObject private var income = Box(0.0)
    @ObservedObject private var expense = Box(0.0)

    var body: some View {
        List {
            Section("Tagesbilanz") {
                HStack {
                    Label("Einnahmen", systemImage: "arrow.down.circle")
                        .foregroundStyle(.green)
                    Spacer()
                    Text(income.value, format: .currency(code: "EUR"))
                }
                HStack {
                    Label("Ausgaben", systemImage: "arrow.up.circle")
                        .foregroundStyle(.red)
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
                                Text(due).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }

            Section {
                SyncStatusFooter()
            }
        }
        .navigationTitle("Heute")
        .toolbar { SyncStatusToolbarItem() }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
    }

    private func eventSubtitle(_ event: CalendarEvent) -> String {
        var parts: [String] = [event.all_day ? "ganztägig" : event.start]
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
        let balance = (try? db.read { db in try Queries.todayBalance(db) }) ?? (0, 0)
        income.value = balance.income
        expense.value = balance.expense
    }
}

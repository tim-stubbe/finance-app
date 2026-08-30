import SwiftUI
import GRDB
import KiesCore

/// Offene Ziele - lesend, grob abhaken UND (neu) anlegen/bearbeiten der
/// Kernfelder Titel/Kategorie/Zieldatum. Die Web-App bleibt für die
/// reichhaltigeren Felder (Trigger, Metriken, Vorgänger) der Ort, siehe
/// ROADMAP.md. Kein numerischer Fortschrittsbalken: progress_percent wird
/// serverseitig berechnet, nicht als Rohspalte synchronisiert.
struct GoalsView: View {
    @ObservedObject var engine = SyncEngine.shared
    @StateObject private var goals = Box<[Goal]>([])
    @State private var editor: GoalEditorTarget?

    var body: some View {
        List {
            if goals.value.isEmpty {
                ContentUnavailableView("Keine offenen Ziele", systemImage: "target", description: Text("Tippe auf +, um eins anzulegen."))
            }
            ForEach(goals.value) { goal in
                VStack(alignment: .leading, spacing: 4) {
                    Text(goal.title).font(.headline)
                    if let category = goal.category, !category.isEmpty {
                        Text(category).font(.caption).foregroundStyle(.secondary)
                    }
                    if let targetDate = goal.target_date {
                        Text("Ziel: \(targetDate)").font(.caption).foregroundStyle(.secondary)
                    }
                }
                .kListRow()
                .contentShape(Rectangle())
                .onTapGesture { if goal.id > 0 { editor = .edit(goal) } }
                .swipeActions(edge: .trailing) {
                    Button {
                        markCompleted(goal)
                    } label: {
                        Label("Erledigt", systemImage: "checkmark")
                    }
                    .tint(.green)
                    .disabled(goal.id < 0)
                }
            }
        }
        .listStyle(.insetGrouped)
        .kListChrome()
        .navigationTitle("Ziele")
        .toolbar {
            SyncStatusToolbarItem()
            ToolbarItem(placement: .primaryAction) {
                Button { editor = .create } label: { Image(systemName: "plus") }
            }
        }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
        .sheet(item: $editor) { target in
            GoalEditorSheet(target: target) { reload() }
        }
    }

    private func reload() {
        goals.value = (try? AppDatabase.shared.read { db in try Queries.goalsNearTarget(db, limit: 100) }) ?? []
    }

    private func markCompleted(_ goal: Goal) {
        try? SyncEngine.shared.setGoalStatusOffline(id: goal.id, status: "completed")
        reload()
        Task { await SyncEngine.shared.run() }
    }
}

enum GoalEditorTarget: Identifiable {
    case create
    case edit(Goal)

    var id: Int64 {
        switch self {
        case .create: return 0
        case .edit(let g): return g.id
        }
    }
}

private struct GoalEditorSheet: View {
    let target: GoalEditorTarget
    let onSaved: () -> Void
    @Environment(\.dismiss) private var dismiss

    @State private var title = ""
    @State private var category = ""
    @State private var hasTargetDate = false
    @State private var targetDate = Date()

    private var isEdit: Bool { if case .edit = target { return true }; return false }

    var body: some View {
        NavigationStack {
            Form {
                Section("Ziel") {
                    TextField("Titel", text: $title)
                    TextField("Kategorie (optional)", text: $category)
                }
                Section {
                    Toggle("Zieldatum", isOn: $hasTargetDate)
                    if hasTargetDate {
                        DatePicker("Datum", selection: $targetDate, displayedComponents: .date)
                    }
                }
            }
            .navigationTitle(isEdit ? "Ziel bearbeiten" : "Neues Ziel")
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
        guard case .edit(let g) = target else { return }
        title = g.title
        category = g.category ?? ""
        if let d = g.target_date, let parsed = Self.dayFormatter.date(from: String(d.prefix(10))) {
            hasTargetDate = true
            targetDate = parsed
        }
    }

    private func save() {
        let t = title.trimmingCharacters(in: .whitespacesAndNewlines)
        let cat = category.trimmingCharacters(in: .whitespacesAndNewlines)
        let catOrNil = cat.isEmpty ? nil : cat
        let dateStr = hasTargetDate ? Self.dayFormatter.string(from: targetDate) : nil
        switch target {
        case .create:
            try? SyncEngine.shared.createGoalOffline(title: t, category: catOrNil, targetDate: dateStr)
        case .edit(let g):
            try? SyncEngine.shared.updateGoalOffline(id: g.id, title: t, category: catOrNil, targetDate: dateStr)
        }
        dismiss()
        onSaved()
        Task { await SyncEngine.shared.run() }
    }

    static let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()
}

import SwiftUI
import GRDB
import KiesCore

/// Offene Ziele - lesend + grob als erledigt markieren (kein volles
/// Bearbeiten in dieser iOS-Scheibe, die Web-App bleibt dafür der
/// reichhaltigere Ort, siehe ROADMAP.md). Kein numerischer Fortschritts-
/// balken: progress_percent wird serverseitig aus GoalProgress/Kontostand
/// berechnet, nicht als Rohspalte synchronisiert (siehe KiesCore/Database/
/// Models.swift-Kommentar zu Goal).
struct GoalsView: View {
    @ObservedObject var engine = SyncEngine.shared
    @StateObject private var goals = Box<[Goal]>([])

    var body: some View {
        List {
            if goals.value.isEmpty {
                ContentUnavailableView("Keine offenen Ziele", systemImage: "target", description: Text("Wird beim nächsten Sync geladen."))
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
        .navigationTitle("Ziele")
        .toolbar { SyncStatusToolbarItem() }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
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

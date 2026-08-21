import SwiftUI
import KiesCore
import GRDB

/// Offene Ziele, rein lesend - analog zu KiesiOS/Views/GoalsView.swift.
/// Kein numerischer Fortschritt lokal verfügbar (progress_percent wird
/// serverseitig berechnet, siehe KiesCore/Database/Models.swift-Kommentar
/// zu Goal) - dafür bleibt die Web-App der Ort.
struct GoalsListView: View {
    @ObservedObject var engine = SyncEngine.shared
    @ObservedObject private var goals = Box<[Goal]>([])

    var body: some View {
        List(goals.value) { (goal: Goal) in
            VStack(alignment: .leading, spacing: 4) {
                Text(goal.title).font(.headline)
                if let category = goal.category, !category.isEmpty {
                    Text(category).font(.caption).foregroundStyle(.secondary)
                }
                if let targetDate = goal.target_date {
                    Text("Ziel: \(targetDate)").font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .navigationTitle("Ziele")
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
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
    }

    private func reload() {
        goals.value = (try? AppDatabase.shared.read { db in try Queries.goalsNearTarget(db, limit: 200) }) ?? []
    }
}

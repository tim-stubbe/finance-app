import SwiftUI
import KiesCore
import GRDB

/// Lebensbereiche: lesend + Check-in setzen - analog zu
/// KiesiOS/Views/LifeAreasView.swift. Kein Anlegen/Bearbeiten von Bereichen
/// selbst, dafür bleibt die Web-App der Ort.
struct LifeAreasListView: View {
    @ObservedObject var engine = SyncEngine.shared
    @ObservedObject private var allAreas = Box<[LifeArea]>([])
    @ObservedObject private var openAreaIDs = Box<Set<Int64>>([])
    @ObservedObject private var checkinNote = Box("")

    var body: some View {
        List(allAreas.value) { (area: LifeArea) in
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(area.name).font(.headline)
                    if openAreaIDs.value.contains(area.id) {
                        Text("Heute noch kein Check-in").font(.caption).foregroundStyle(.orange)
                    } else {
                        Text("Heute schon eingecheckt").font(.caption).foregroundStyle(.green)
                    }
                }
                Spacer()
                Button {
                    quickCheckin(area)
                } label: {
                    Image(systemName: "checkmark.circle")
                }
                .buttonStyle(.plain)
            }
        }
        .navigationTitle("Leben")
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
        allAreas.value = (try? AppDatabase.shared.read { db in
            try LifeArea.filter(Column("active") == true).order(Column("name")).fetchAll(db)
        }) ?? []
        let openAreas = (try? AppDatabase.shared.read { db in try Queries.lifeAreasWithoutCheckinToday(db) }) ?? []
        openAreaIDs.value = Set(openAreas.map(\.id))
    }

    private func quickCheckin(_ area: LifeArea) {
        try? SyncEngine.shared.createLifeCheckInOffline(areaID: area.id, note: "Erledigt")
        reload()
        Task { await SyncEngine.shared.run() }
    }
}

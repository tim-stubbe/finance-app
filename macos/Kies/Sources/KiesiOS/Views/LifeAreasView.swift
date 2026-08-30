import SwiftUI
import GRDB
import KiesCore

/// Lebensbereiche: lesend + Check-in setzen (kein Anlegen/Bearbeiten von
/// Bereichen selbst - dafür bleibt die Web-App der Ort, siehe ROADMAP.md).
/// Streak/30-Tage-Verlauf sind serverseitig berechnete Werte, nicht Teil der
/// synchronisierten Rohspalten - "heute schon eingecheckt" wird stattdessen
/// lokal aus life_checkins abgeleitet (siehe Queries.lifeAreasWithoutCheckinToday).
struct LifeAreasView: View {
    @ObservedObject var engine = SyncEngine.shared
    @StateObject private var allAreas = Box<[LifeArea]>([])
    @StateObject private var openAreaIDs = Box<Set<Int64>>([])
    @StateObject private var streaks = Box<[Int64: Int]>([:])
    @State private var checkinArea: LifeArea?
    @State private var checkinNote = ""

    var body: some View {
        List {
            if allAreas.value.isEmpty {
                ContentUnavailableView("Keine Lebensbereiche", systemImage: "heart.text.square", description: Text("Wird beim nächsten Sync geladen."))
            }
            ForEach(allAreas.value) { area in
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(area.name).font(.headline)
                        if openAreaIDs.value.contains(area.id) {
                            Text("Heute noch kein Check-in").font(.caption).foregroundStyle(.orange)
                        } else {
                            Text("Heute schon eingecheckt").font(.caption).foregroundStyle(.green)
                        }
                        if let s = streaks.value[area.id], s > 0 {
                            Text("🔥 \(s) Tag\(s == 1 ? "" : "e") in Folge").font(.caption2).foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    Button {
                        checkinArea = area
                        checkinNote = ""
                    } label: {
                        Image(systemName: "checkmark.circle")
                    }
                    .buttonStyle(.borderless)
                }
                .kListRow()
                .swipeActions(edge: .trailing) {
                    Button {
                        quickCheckin(area)
                    } label: {
                        Label("Heute erledigt", systemImage: "checkmark")
                    }
                    .tint(.green)
                }
            }
        }
        .listStyle(.insetGrouped)
        .kListChrome()
        .navigationTitle("Leben")
        .toolbar { SyncStatusToolbarItem() }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
        .sheet(item: $checkinArea) { area in
            NavigationStack {
                Form {
                    Section("Check-in für \(area.name)") {
                        TextField("Notiz (optional)", text: $checkinNote)
                    }
                }
                .navigationTitle("Check-in")
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Abbrechen") { checkinArea = nil }
                    }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Speichern") {
                            saveCheckin(area, note: checkinNote)
                        }
                    }
                }
            }
        }
    }

    private func reload() {
        allAreas.value = (try? AppDatabase.shared.read { db in
            try LifeArea.filter(Column("active") == true).order(Column("name")).fetchAll(db)
        }) ?? []
        let openAreas = (try? AppDatabase.shared.read { db in try Queries.lifeAreasWithoutCheckinToday(db) }) ?? []
        openAreaIDs.value = Set(openAreas.map(\.id))
        streaks.value = (try? AppDatabase.shared.read { db in
            var out: [Int64: Int] = [:]
            for area in try LifeArea.filter(Column("active") == true).fetchAll(db) {
                out[area.id] = try Queries.checkinStreak(db, areaID: area.id)
            }
            return out
        }) ?? [:]
    }

    private func quickCheckin(_ area: LifeArea) {
        try? SyncEngine.shared.createLifeCheckInOffline(areaID: area.id, note: "Erledigt")
        reload()
        Task { await SyncEngine.shared.run() }
    }

    private func saveCheckin(_ area: LifeArea, note: String) {
        let text = note.trimmingCharacters(in: .whitespacesAndNewlines)
        try? SyncEngine.shared.createLifeCheckInOffline(areaID: area.id, note: text.isEmpty ? "Erledigt" : text)
        checkinArea = nil
        reload()
        Task { await SyncEngine.shared.run() }
    }
}

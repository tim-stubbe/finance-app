import SwiftUI
import KiesCore

/// Minimaler Start/Stop-Screen für die Zeiterfassung. Die eigentliche Logik
/// (Device-Token-REST-Aufrufe, Live-Activity-Verwaltung) sitzt komplett in
/// `LiveActivityManager` (KiesCore) - diese View ist nur die Projektauswahl
/// und ein großer Start/Stop-Button, analog zum Lock-Screen-Widget.
struct TimeTrackingView: View {
    @ObservedObject private var manager = LiveActivityManager.shared
    @State private var selectedProjectId: Int?
    @State private var note: String = ""
    @State private var isBusy = false

    var body: some View {
        KScreen(spacing: KSpacing.lg) {
            header
            if let entry = manager.runningEntry {
                runningCard(entry)
            } else {
                startCard
            }
            if let error = manager.errorMessage {
                Text(error).font(.caption).foregroundStyle(KColor.warning)
            }
        }
        .navigationTitle("Zeiterfassung")
        .task {
            if manager.projects.isEmpty { await manager.loadProjects() }
            if selectedProjectId == nil { selectedProjectId = manager.projects.first { $0.active }?.id }
        }
        .refreshable { await manager.loadProjects() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 5) {
            KKicker(text: "Zeiterfassung")
            Text("Timer").font(KFont.title).foregroundStyle(KColor.primary)
            Text("Startet auch eine Live Activity auf dem Sperrbildschirm.").font(.subheadline).foregroundStyle(KColor.secondary)
        }
    }

    private var startCard: some View {
        VStack(alignment: .leading, spacing: KSpacing.md) {
            if manager.projects.isEmpty {
                ContentUnavailableView("Keine Projekte", systemImage: "folder", description: Text("Wird beim nächsten Laden aktualisiert."))
            } else {
                Picker("Projekt", selection: $selectedProjectId) {
                    ForEach(manager.projects.filter(\.active)) { project in
                        Text(project.name).tag(Optional(project.id))
                    }
                }
                .pickerStyle(.menu)
                TextField("Notiz (optional)", text: $note)
                    .textFieldStyle(.roundedBorder)
                Button {
                    start()
                } label: {
                    Label("Starten", systemImage: "play.fill").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(selectedProjectId == nil || isBusy)
            }
        }
        .kCard(KSpacing.md)
    }

    private func runningCard(_ entry: TimeEntry) -> some View {
        VStack(alignment: .leading, spacing: KSpacing.md) {
            let name = manager.projects.first { $0.id == entry.projectId }?.name ?? "Projekt"
            HStack {
                Image(systemName: "clock.fill").foregroundStyle(KColor.accentStrong)
                Text(name).font(.headline)
            }
            Text(entry.startedAt, style: .relative).font(.caption).foregroundStyle(KColor.secondary)
            Button {
                stop()
            } label: {
                Label("Stoppen", systemImage: "stop.fill").frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .tint(.red)
            .disabled(isBusy)
        }
        .kCard(KSpacing.md)
    }

    private func start() {
        guard let projectId = selectedProjectId else { return }
        let name = manager.projects.first { $0.id == projectId }?.name ?? "Projekt"
        let trimmedNote = note.trimmingCharacters(in: .whitespacesAndNewlines)
        isBusy = true
        Task {
            await manager.start(projectId: projectId, projectName: name, note: trimmedNote.isEmpty ? nil : trimmedNote)
            isBusy = false
        }
    }

    private func stop() {
        isBusy = true
        Task {
            await manager.stop()
            isBusy = false
        }
    }
}

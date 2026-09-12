#if os(iOS)
import Foundation
import ActivityKit
import Combine

/// Verwaltet die lokale Live Activity für die Zeiterfassung (Lock Screen /
/// Dynamic Island). Kein APNs im Projekt - die Activity wird ausschließlich
/// von der App selbst gestartet/aktualisiert/beendet, analog zu
/// `TimeEntryClient` (Device-Token, kein GRDB-Sync).
@MainActor
public final class LiveActivityManager: ObservableObject {
    public static let shared = LiveActivityManager()

    @Published public private(set) var runningEntry: TimeEntry?
    @Published public private(set) var errorMessage: String?
    @Published public private(set) var projects: [DeviceProject] = []

    private var activity: Activity<TimerActivityAttributes>?

    private init() {}

    /// Lädt die Projektliste für die Start/Stop-UI. Best effort - Fehler
    /// landen in `errorMessage`, blockieren aber nicht den restlichen Flow.
    public func loadProjects() async {
        do {
            projects = try await TimeEntryClient.projects()
        } catch {
            errorMessage = "Projekte konnten nicht geladen werden: \(error.localizedDescription)"
        }
    }

    /// Startet eine Zeiterfassung für `projectId` und - falls unterstützt -
    /// eine begleitende Live Activity. Scheitert die Live Activity (z.B.
    /// Nutzer hat sie in den Einstellungen deaktiviert), bleibt die
    /// serverseitige Zeiterfassung trotzdem aktiv.
    public func start(projectId: Int, projectName: String, note: String? = nil) async {
        errorMessage = nil
        do {
            let entry = try await TimeEntryClient.start(projectId: projectId, note: note)
            runningEntry = entry
            beginActivity(entryId: entry.id, projectName: projectName, startedAt: entry.startedAt)
        } catch {
            errorMessage = "Start fehlgeschlagen: \(error.localizedDescription)"
        }
    }

    public func stop() async {
        guard let entry = runningEntry else { return }
        errorMessage = nil
        do {
            _ = try await TimeEntryClient.stop(entryId: entry.id)
            runningEntry = nil
            await endActivity()
        } catch {
            errorMessage = "Stop fehlgeschlagen: \(error.localizedDescription)"
        }
    }

    /// Beim App-Start/Foreground aufrufen: läuft serverseitig noch eine
    /// Zeiterfassung (z.B. App wurde beendet, während der Timer lief), aber
    /// es existiert keine lokale Live Activity mehr, wird sie neu erzeugt.
    public func restoreIfNeeded(projectName: (Int) -> String?) async {
        do {
            guard let entry = try await TimeEntryClient.runningEntry() else {
                runningEntry = nil
                await endActivity()
                return
            }
            runningEntry = entry
            guard activity == nil else { return }
            let name = projectName(entry.projectId) ?? "Projekt"
            beginActivity(entryId: entry.id, projectName: name, startedAt: entry.startedAt)
        } catch {
            // Best effort - kein Netz/nicht gekoppelt beim Start ist kein Fehlerfall.
        }
    }

    private func beginActivity(entryId: Int, projectName: String, startedAt: Date) {
        guard ActivityAuthorizationInfo().areActivitiesEnabled else { return }
        // Falls noch eine (verwaiste) Activity läuft, zuerst beenden.
        if activity != nil {
            Task { await endActivity() }
        }
        let attributes = TimerActivityAttributes(entryId: entryId)
        let state = TimerActivityAttributes.ContentState(projectName: projectName, startedAt: startedAt)
        do {
            activity = try Activity.request(
                attributes: attributes,
                content: .init(state: state, staleDate: nil)
            )
        } catch {
            errorMessage = "Live Activity konnte nicht gestartet werden: \(error.localizedDescription)"
        }
    }

    private func endActivity() async {
        guard let activity else { return }
        await activity.end(nil, dismissalPolicy: .immediate)
        self.activity = nil
    }
}
#endif

import SwiftUI
import KiesCore

/// Liste offener Sync-Konflikte fürs macOS-Detail-Pane - macOS-Gegenstück
/// zu KiesiOS/Views/ConflictsView.swift, identische Logik (SyncEngine.
/// resolveConflictKeepServer/-RetryMine, siehe dort für die Begründung
/// gegen einen automatischen Merge).
struct ConflictsListView: View {
    @ObservedObject private var engine = SyncEngine.shared
    @State private var busyConflictID: Int64?

    var body: some View {
        List {
            if engine.conflicts.isEmpty {
                ContentUnavailableView("Keine Konflikte", systemImage: "checkmark.circle", description: Text("Alle Änderungen sind sauber synchronisiert."))
            } else {
                ForEach(engine.conflicts) { conflict in
                    Section {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(kindLabel(conflict.entity_type)).font(.headline)
                            Text(reasonText(conflict)).font(.subheadline).foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 2)

                        HStack {
                            Button("Server behalten") {
                                resolve(conflict) { try await engine.resolveConflictKeepServer(conflict) }
                            }
                            Spacer()
                            Button("Meine Version behalten") {
                                resolve(conflict) { try await engine.resolveConflictRetryMine(conflict) }
                            }
                            .buttonStyle(.borderedProminent)
                        }
                        .disabled(busyConflictID == conflict.id)
                    }
                }
            }
        }
        .navigationTitle("Konflikte")
        .task { await engine.loadConflicts() }
    }

    private func resolve(_ conflict: SyncConflict, action: @escaping () async throws -> Void) {
        busyConflictID = conflict.id
        Task {
            try? await action()
            busyConflictID = nil
        }
    }

    private func kindLabel(_ entityType: String) -> String {
        switch entityType {
        case "Transaction": return "Buchung"
        case "Todo": return "Todo"
        case "Account": return "Konto"
        case "Category": return "Kategorie"
        case "WishlistItem": return "Wunsch"
        case "LifeCheckIn": return "Check-in"
        default: return entityType
        }
    }

    private func reasonText(_ conflict: SyncConflict) -> String {
        switch conflict.reason {
        case "server_newer":
            return "Wurde zwischenzeitlich auch auf dem Server geändert (z.B. über die Web-App oder iOS)."
        default:
            return conflict.reason
        }
    }
}

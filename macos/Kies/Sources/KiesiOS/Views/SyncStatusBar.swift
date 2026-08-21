import SwiftUI
import KiesCore

/// Sync-Status als Toolbar-Button (Icon dreht/spinnt beim Laufen, Fehler als
/// Badge-Punkt) - gemeinsam für alle vier Tabs statt vier eigenen Kopien,
/// analog zum "Sync"-Toolbar-Button, den jede macOS-Detailansicht einzeln hat
/// (siehe z.B. Sources/Kies/Views/AccountsListView.swift).
struct SyncStatusToolbarItem: ToolbarContent {
    @ObservedObject var engine = SyncEngine.shared

    var body: some ToolbarContent {
        ToolbarItem(placement: .topBarTrailing) {
            Button {
                Task { await engine.run() }
            } label: {
                if engine.isSyncing {
                    ProgressView().controlSize(.small)
                } else if engine.lastError != nil {
                    Image(systemName: "exclamationmark.arrow.triangle.2.circlepath")
                        .foregroundStyle(.red)
                } else {
                    Image(systemName: "arrow.triangle.2.circlepath")
                }
            }
            .disabled(engine.isSyncing)
        }
    }
}

/// Kleine Fußzeile mit "zuletzt synchronisiert"/Fehlertext/offenen Änderungen -
/// auf der Heute-Seite eingeblendet, analog zum Sidebar-Footer der macOS-App.
/// Bei einem Netzwerkfehler bleiben lokale Daten unverändert nutzbar - hier
/// nur ein Hinweistext, kein Abbruch/Crash-Dialog.
struct SyncStatusFooter: View {
    @ObservedObject var engine = SyncEngine.shared
    @ObservedObject private var pendingCount = Box(0)

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 6) {
                if engine.isSyncing {
                    Text("Synchronisiert…").font(.caption2).foregroundStyle(.secondary)
                } else if let last = engine.lastSyncedAt {
                    Text("Zuletzt synchronisiert: \(last.formatted(date: .omitted, time: .shortened))")
                        .font(.caption2).foregroundStyle(.secondary)
                } else {
                    Text("Noch nicht synchronisiert").font(.caption2).foregroundStyle(.secondary)
                }
            }
            if pendingCount.value > 0 {
                Text("\(pendingCount.value) Änderung\(pendingCount.value == 1 ? "" : "en") wartet\(pendingCount.value == 1 ? "" : "en") auf Upload")
                    .font(.caption2).foregroundStyle(.orange)
            }
            if let error = engine.lastError {
                Text("Fehler: \(error) - lokale Daten bleiben nutzbar.").font(.caption2).foregroundStyle(.red).lineLimit(2)
            }
        }
        .task { await reload() }
        .onChange(of: engine.isSyncing) { _, syncing in
            if !syncing { Task { await reload() } }
        }
    }

    private func reload() async {
        pendingCount.value = await SyncEngine.shared.pendingOutboxCount()
    }
}

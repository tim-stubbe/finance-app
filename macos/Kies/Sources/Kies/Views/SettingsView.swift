import SwiftUI
import KiesCore

/// Einstellungsfenster (Cmd+,) - macOS-Gegenstück zu
/// KiesiOS/Views/SettingsView.swift, gleicher Inhalt: App-Sperre-Toggle +
/// Verbindungsinfo. Bisher gab es dafür auf macOS gar keinen Ort (siehe
/// ROADMAP.md "macOS-Client nachziehen" - "klarerer Sync-Status").
struct SettingsView: View {
    @ObservedObject private var lock = AppLockStore.shared
    @ObservedObject private var pairing = PairingStore.shared

    var body: some View {
        Form {
            Section {
                Toggle("Touch ID/Passwort beim Öffnen", isOn: $lock.enabled)
            } footer: {
                Text("Sperrt Kies beim Start und nach längerer Zeit im Hintergrund. Rein lokal auf diesem Gerät - kein serverseitiges Passwort.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Verbindung") {
                LabeledContent("Server", value: pairing.baseURLString)
                Button("Verbindung trennen", role: .destructive) {
                    pairing.secret = ""
                }
            }
        }
        .padding(20)
        .frame(width: 420)
        .onChange(of: lock.enabled) { _, enabled in
            if enabled { lock.lockIfEnabled() }
        }
    }
}

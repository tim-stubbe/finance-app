import SwiftUI
import KiesCore

/// Schlanke Einstellungen für die iOS-App selbst (App-Sperre, Verbindung) -
/// kein Abbild der vielen Web-Einstellungen, die bleiben bewusst der Web-App
/// vorbehalten.
struct SettingsView: View {
    @ObservedObject private var lock = AppLockStore.shared
    @ObservedObject private var pairing = PairingStore.shared

    var body: some View {
        Form {
            Section {
                Toggle("Face ID/Touch ID beim Öffnen", isOn: $lock.enabled)
            } footer: {
                Text("Sperrt Kies beim Start und nach längerer Zeit im Hintergrund. Rein lokal auf diesem Gerät - kein serverseitiges Passwort.")
            }
            Section("Verbindung") {
                LabeledContent("Server", value: pairing.baseURLString)
                Button("Verbindung trennen", role: .destructive) {
                    pairing.secret = ""
                }
            }
        }
        .navigationTitle("Einstellungen")
        .onChange(of: lock.enabled) { _, enabled in
            if enabled { lock.lockIfEnabled() }
        }
    }
}

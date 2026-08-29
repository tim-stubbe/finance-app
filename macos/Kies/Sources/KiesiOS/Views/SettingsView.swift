import SwiftUI
import KiesCore

/// Schlanke Einstellungen für die iOS-App selbst (App-Sperre, Verbindung) -
/// kein Abbild der vielen Web-Einstellungen, die bleiben bewusst der Web-App
/// vorbehalten.
struct SettingsView: View {
    @ObservedObject private var lock = AppLockStore.shared
    @ObservedObject private var pairing = PairingStore.shared
    @ObservedObject private var notifications = NotificationManager.shared
    @ObservedObject private var health = HealthKitSync.shared

    var body: some View {
        Form {
            Section {
                Toggle("Face ID/Touch ID beim Öffnen", isOn: $lock.enabled)
            } footer: {
                Text("Sperrt Kies beim Start und nach längerer Zeit im Hintergrund. Rein lokal auf diesem Gerät - kein serverseitiges Passwort.")
            }
            Section {
                Toggle("Lokale Benachrichtigungen", isOn: $notifications.enabled)
                if notifications.authorizationDenied {
                    Text("iOS hat Benachrichtigungen für Kies blockiert - bitte in den Systemeinstellungen erlauben.")
                        .font(.caption).foregroundStyle(.red)
                }
            } footer: {
                Text("Meldet fällige Todos, ablaufende Fristen und fehlgeschlagene Syncs direkt auf diesem Gerät - rein lokal, kein Push-Server. Telegram bleibt die Haupt-Benachrichtigung.")
            }
            if health.isAvailable {
                Section {
                    Toggle("Apple Health synchronisieren", isOn: $health.enabled)
                    if health.enabled {
                        Button {
                            Task { await health.syncNow() }
                        } label: {
                            HStack {
                                Text("Jetzt synchronisieren")
                                if health.isSyncing { Spacer(); ProgressView() }
                            }
                        }
                        .disabled(health.isSyncing || !pairing.isPaired)
                        if let last = health.lastSync {
                            Text("Zuletzt: \(last.formatted(date: .abbreviated, time: .shortened))")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        if let err = health.lastError {
                            Text(err).font(.caption).foregroundStyle(.red)
                        }
                    }
                } footer: {
                    Text("Übernimmt Schritte, Ruhepuls, Gewicht und Schlaf der letzten 30 Tage in deinen Gesundheits-Verlauf (ein Wert pro Tag). Läuft zusätzlich beim App-Start. Freigabe erteilst du im Health-Dialog von iOS.")
                }
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
        .onChange(of: notifications.enabled) { _, enabled in
            if enabled { Task { await notifications.requestAuthorization() } }
        }
        .onChange(of: health.enabled) { _, enabled in
            if enabled { Task { await health.requestAuthorization(); await health.syncNow() } }
        }
    }
}

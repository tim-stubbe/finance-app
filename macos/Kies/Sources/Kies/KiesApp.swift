import SwiftUI
import KiesCore
import AppKit

@main
struct KiesApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @ObservedObject private var lock = AppLockStore.shared

    init() {
        // Ohne App-Bundle/Info.plist (kein Xcode-Projekt, siehe Package.swift)
        // startet der Prozess manchmal nicht als reguläre, fokussierbare App -
        // Fenster erscheint, nimmt aber keine Klicks/Tastatureingaben an.
        // Erzwingt die normale Aktivierungs-Policy und holt die App aktiv
        // in den Vordergrund.
        NSApplication.shared.setActivationPolicy(.regular)
        NSApplication.shared.activate(ignoringOtherApps: true)
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .onChange(of: scenePhase) { _, phase in
            // scenePhase auf macOS: .background entspricht "keine Fenster
            // aktiv/App im Hintergrund" - dieselbe App-Sperre-Logik wie iOS
            // (AppLockStore.handleBackground/-Foreground, jetzt in KiesCore).
            switch phase {
            case .background: lock.handleBackground()
            case .active: lock.handleForeground()
            default: break
            }
        }

        // Cmd+, - App-Sperre-Einstellung + Verbindungsinfo (siehe
        // Views/SettingsView.swift). Gab es auf macOS bisher gar nicht.
        Settings {
            SettingsView()
        }
    }
}

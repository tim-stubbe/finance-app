import SwiftUI
import KiesCore
import AppKit

@main
struct KiesApp: App {
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
    }
}

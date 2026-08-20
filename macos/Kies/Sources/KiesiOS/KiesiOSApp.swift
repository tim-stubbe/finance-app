import SwiftUI
import KiesCore

/// Erste iOS-Version von Kies - bewusst schlank (Heute/Konten/Buchungen/
/// Todos), kein Anspruch auf Feature-Parität mit der Web-App oder dem
/// macOS-Client (siehe ROADMAP.md, Abschnitt "Native iOS-App"). Teilt sich
/// KiesCore (Datenbank, Sync-Engine, Pairing, Keychain) mit dem macOS-Client
/// unter Sources/Kies - nur die Oberfläche ist eigenständig für iOS gebaut
/// (TabView statt NavigationSplitView, siehe Sources/Kies/Views/ContentView.swift
/// für den macOS-Gegenpart).
///
/// Start in Xcode: Package.swift öffnen, Schema "KiesiOS" + einen iOS-
/// Simulator (oder ein eigenes Gerät) als Ziel wählen, Cmd+R.
@main
struct KiesiOSApp: App {
    var body: some Scene {
        WindowGroup {
            RootView()
        }
    }
}

struct RootView: View {
    @ObservedObject var pairing = PairingStore.shared
    @ObservedObject var engine = SyncEngine.shared

    var body: some View {
        Group {
            if !pairing.isPaired {
                PairingView()
            } else {
                RootTabView()
            }
        }
        .task {
            guard pairing.isPaired else { return }
            await engine.run()
        }
    }
}

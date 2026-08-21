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
    @Environment(\.scenePhase) private var scenePhase
    @ObservedObject private var lock = AppLockStore.shared

    var body: some Scene {
        WindowGroup {
            RootView()
        }
        .onChange(of: scenePhase) { _, phase in
            switch phase {
            case .background: lock.handleBackground()
            case .active: lock.handleForeground()
            default: break
            }
        }
    }
}

struct RootView: View {
    @ObservedObject var pairing = PairingStore.shared
    @ObservedObject var engine = SyncEngine.shared
    @ObservedObject var lock = AppLockStore.shared

    var body: some View {
        ZStack {
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
            .onAppear { lock.lockIfEnabled() }

            if lock.isLocked {
                AppLockView()
            }
        }
    }
}

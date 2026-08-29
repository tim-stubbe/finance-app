import SwiftUI
import KiesCore
import WidgetKit

/// Erste iOS-Version von Kies - bewusst schlank (Heute/Konten/Buchungen/
/// Todos), kein Anspruch auf Feature-Parität mit der Web-App oder dem
/// macOS-Client (siehe ROADMAP.md, Abschnitt "Native iOS-App"). Teilt sich
/// KiesCore (Datenbank, Sync-Engine, Pairing, Keychain) mit dem macOS-Client
/// unter Sources/Kies - nur die Oberfläche ist eigenständig für iOS gebaut
/// (TabView statt NavigationSplitView, siehe Sources/Kies/Views/ContentView.swift
/// für den macOS-Gegenpart).
///
/// Start: entweder Package.swift öffnen (Schema "KiesiOS", schnell, ohne
/// Widget/Share-Extension) oder Kies.xcodeproj (per `xcodegen generate`
/// erzeugt, siehe project.yml - mit Widget + Share-Extension). Simulator/
/// Gerät als Ziel wählen, Cmd+R.
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
    @ObservedObject private var router = TabRouter.shared

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
                // Widget zeigt sonst bis zum nächsten WidgetKit-eigenen
                // Refresh-Fenster (siehe KiesTodayProvider.getTimeline) den
                // Stand vor diesem Sync - nach einem erfolgreichen Sync direkt
                // anstoßen, kostet nichts, wenn (noch) kein Widget hinzugefügt
                // wurde (reloadAllTimelines ist dann einfach ein No-Op).
                if engine.lastError == nil {
                    WidgetCenter.shared.reloadAllTimelines()
                }
                // Apple-Health-Werte (falls aktiviert) gleich mitziehen -
                // eigener Endpunkt, unabhaengig vom Entity-Sync oben.
                await HealthKitSync.shared.syncNow()
            }
            .onAppear { lock.lockIfEnabled() }
            .onOpenURL { url in
                // Widget-Deep-Link (siehe KiesWidget: .widgetURL(kies://...)) -
                // aktuell nur "today", weitere Tab-Namen (AppTab.rawValue)
                // funktionieren bereits automatisch mit, falls später gebraucht.
                guard url.scheme == "kies", let tab = AppTab(rawValue: url.host ?? "") else { return }
                router.jump(to: tab)
            }

            if lock.isLocked {
                AppLockView()
            }
        }
    }
}

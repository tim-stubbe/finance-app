import SwiftUI
import KiesCore
import WidgetKit

@main
struct KiesiOSApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @ObservedObject private var lock = AppLockStore.shared

    init() { KiesAppearance.apply() }

    var body: some Scene {
        WindowGroup {
            RootView()
                .tint(KColor.accentStrong)
                .preferredColorScheme(.light)
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
            NeonBackdrop(opacity: 0.14)
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
                if engine.lastError == nil {
                    WidgetCenter.shared.reloadAllTimelines()
                }
                await HealthKitSync.shared.syncNow()
            }
            .onAppear { lock.lockIfEnabled() }
            .onOpenURL { url in
                guard url.scheme == "kies", let tab = AppTab(rawValue: url.host ?? "") else { return }
                router.jump(to: tab)
            }

            if lock.isLocked {
                AppLockView()
            }
        }
    }
}

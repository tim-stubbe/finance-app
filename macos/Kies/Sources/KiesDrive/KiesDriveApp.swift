import SwiftUI
import KiesCore

@main
struct KiesDriveApp: App {
    init() {
        #if DEBUG && os(iOS)
        // Allows a developer-installed build to be paired without exposing the
        // token in source code or UserDefaults. devicectl supplies this value
        // only to this launch; after import it lives exclusively in Keychain.
        if let bootstrapToken = ProcessInfo.processInfo.environment["KIES_DRIVE_BOOTSTRAP_TOKEN"],
           !bootstrapToken.isEmpty {
            DeviceTokenStore.shared.setToken(bootstrapToken)
        }
        #endif
    }

    var body: some Scene {
        #if os(macOS)
        WindowGroup { DriveContentView() }
            .defaultSize(width: 1120, height: 760)
        #else
        WindowGroup { DriveContentView() }
        #endif
    }
}

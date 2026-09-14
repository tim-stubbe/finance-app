import SwiftUI

@main
struct KiesDriveApp: App {
    var body: some Scene {
        #if os(macOS)
        WindowGroup { DriveContentView() }
            .defaultSize(width: 1120, height: 760)
        #else
        WindowGroup { DriveContentView() }
        #endif
    }
}

#if os(iOS)
import ActivityKit
import Foundation

/// Attribute + Zustand für die Zeiterfassungs-Live-Activity (Lock Screen /
/// Dynamic Island). Liegt in KiesCore, damit sowohl `KiesiOS`
/// (`LiveActivityManager`) als auch die `KiesWidget`-Extension (eigenes
/// Xcode-Target, kein Source-Sharing mit KiesiOS) denselben Typ verwenden -
/// beide binden bereits das KiesCore-Package ein. `ActivityKit` gibt es nur
/// auf iOS/watchOS, daher der `os(iOS)`-Guard: das macOS-Target `Kies`
/// baut KiesCore ebenfalls (Package.swift: `.macOS(.v14), .iOS(.v17)`) und
/// darf hierdurch nicht brechen.
public struct TimerActivityAttributes: ActivityAttributes {
    public struct ContentState: Codable, Hashable {
        public var projectName: String
        public var startedAt: Date

        public init(projectName: String, startedAt: Date) {
            self.projectName = projectName
            self.startedAt = startedAt
        }
    }

    public var entryId: Int

    public init(entryId: Int) {
        self.entryId = entryId
    }
}
#endif

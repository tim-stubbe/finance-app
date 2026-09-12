import Foundation

/// Zentrale Stelle, um von außerhalb (Widget-Deep-Link kies://quick-capture,
/// siehe KiesiOSApp.onOpenURL) den QuickCapture-Sheet mit einer bestimmten
/// Art (Buchung/Todo/Check-in) vorausgewählt zu öffnen - spiegelt das Muster
/// von TabRouter. RootTabView beobachtet `pendingKind` und öffnet den Sheet,
/// wenn er gesetzt wird.
@MainActor
final class QuickCaptureRouter: ObservableObject {
    static let shared = QuickCaptureRouter()
    @Published var pendingKind: QuickCaptureView.Kind?

    private init() {}

    func request(_ kind: QuickCaptureView.Kind) {
        pendingKind = kind
    }

    func clear() {
        pendingKind = nil
    }
}

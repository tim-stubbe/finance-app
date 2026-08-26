import Foundation
import LocalAuthentication

/// Optionale App-Sperre (Face ID auf iOS, Touch ID/Geräte-Passwort auf
/// macOS - LocalAuthentication.deviceOwnerAuthentication deckt beides ab),
/// rein lokal auf dem Gerät, kein serverseitiges Passwort. Die "aktiviert"-
/// Einstellung ist kein Geheimnis (nur ein Schalter), deshalb UserDefaults
/// statt Keychain - konsistent zu PairingStore.baseURLString, das aus
/// demselben Grund auch UserDefaults statt Keychain nutzt (siehe dort).
///
/// Ursprünglich iOS-only (Sources/KiesiOS/AppLock/), nach KiesCore
/// verschoben, damit die macOS-App (Sources/Kies) es mitnutzen kann (siehe
/// ROADMAP.md "macOS-Client nachziehen") - reine Logik ohne SwiftUI-Import,
/// passt zur bestehenden KiesCore-Regel (siehe AppDatabase-Kopfkommentar:
/// "läuft dadurch auch als reines Kommandozeilen-Tool"). Die dazugehörige
/// AppLockView (SwiftUI) bleibt bewusst pro Plattform eigenständig (analog
/// zu Box.swift), UI gehört nicht in KiesCore.
@MainActor
public final class AppLockStore: ObservableObject {
    public static let shared = AppLockStore()

    private static let enabledKey = "kies.appLockEnabled"
    /// Nach wie viel Hintergrundzeit erneut gesperrt wird - kurz genug, dass
    /// ein kurzer App-Wechsel (z.B. Safari-Link) nicht nervt, aber lang genug,
    /// dass es noch eine echte Sperre ist.
    private static let reauthAfterSeconds: TimeInterval = 30

    @Published public var enabled: Bool {
        didSet { UserDefaults.standard.set(enabled, forKey: Self.enabledKey) }
    }
    /// True, solange die Sperre aktiv ist und die Oberfläche verdeckt werden muss.
    @Published public var isLocked: Bool
    /// Deutsche Fehlermeldung des letzten fehlgeschlagenen Versuchs, für Anzeige
    /// auf dem Sperrbildschirm.
    @Published public var lastErrorMessage: String?

    private var backgroundedAt: Date?

    private init() {
        let enabled = UserDefaults.standard.bool(forKey: Self.enabledKey)
        self.enabled = enabled
        self.isLocked = enabled
    }

    /// Beim App-Start bzw. wenn die Einstellung gerade erst eingeschaltet wurde.
    public func lockIfEnabled() {
        guard enabled else { return }
        isLocked = true
    }

    /// Beim Wechsel in den Hintergrund gemerkt - erst beim Zurückkommen wird
    /// entschieden, ob die Zeit für eine erneute Sperre reicht (siehe
    /// handleForeground). Ein sofortiges Sperren beim Backgrounden würde
    /// z.B. beim Teilen eines Screenshots oder kurzem App-Wechsel nerven.
    public func handleBackground() {
        guard enabled else { return }
        backgroundedAt = Date()
    }

    public func handleForeground() {
        guard enabled else { return }
        if let since = backgroundedAt, Date().timeIntervalSince(since) >= Self.reauthAfterSeconds {
            isLocked = true
        }
        backgroundedAt = nil
    }

    /// Face ID/Touch ID mit Geräte-Code als Fallback (deviceOwnerAuthentication,
    /// nicht nur biometrics) - ohne Fallback wäre ein Nutzer ohne eingerichtete
    /// Biometrie oder mit temporär fehlgeschlagener Gesichtserkennung komplett
    /// ausgesperrt.
    public func authenticate() async {
        let context = LAContext()
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            lastErrorMessage = "Face ID/Touch ID ist auf diesem Gerät nicht eingerichtet. Bitte in den iOS-Einstellungen aktivieren oder die App-Sperre in Kies ausschalten."
            return
        }
        do {
            let success = try await context.evaluatePolicy(
                .deviceOwnerAuthentication,
                localizedReason: "Zum Öffnen von Kies entsperren"
            )
            if success {
                isLocked = false
                lastErrorMessage = nil
            }
        } catch let laError as LAError {
            switch laError.code {
            case .userCancel, .appCancel, .systemCancel:
                lastErrorMessage = nil  // bewusst kein Fehlertext bei einfachem Abbrechen
            case .userFallback:
                lastErrorMessage = nil
            case .biometryNotEnrolled:
                lastErrorMessage = "Face ID/Touch ID ist auf diesem Gerät nicht eingerichtet."
            case .biometryLockout:
                lastErrorMessage = "Zu viele Fehlversuche - bitte mit dem Geräte-Code entsperren."
            default:
                lastErrorMessage = "Entsperren fehlgeschlagen. Bitte erneut versuchen."
            }
        } catch {
            lastErrorMessage = "Entsperren fehlgeschlagen. Bitte erneut versuchen."
        }
    }
}

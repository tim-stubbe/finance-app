import Foundation
import Combine

/// Server-Adresse + Secret fürs Koppeln - Adresse in UserDefaults (kein
/// Geheimnis), Secret im Keychain (siehe KeychainHelper).
///
/// Ist KIES_BASE_URL/KIES_SYNC_SECRET gesetzt (Skript-/Testaufbau, z.B.
/// KiesCLI), wird das Keychain komplett übersprungen - wichtig, weil das
/// Login-Keychain bei gesperrtem Bildschirm ebenfalls gesperrt ist und
/// SecItemCopyMatching/-Add dann OHNE sichtbaren Prompt (kein interaktiver
/// Session) auf unbestimmte Zeit blockiert, statt einen Fehler zu liefern -
/// das legt jeden automatisierten/CLI-Lauf ohne aktive Sitzung sonst lahm.
public final class PairingStore: ObservableObject {
    public static let shared = PairingStore()

    @Published public var baseURLString: String {
        didSet {
            guard !usesEnvOverride else { return }
            UserDefaults.standard.set(baseURLString, forKey: "kies.baseURL")
        }
    }
    @Published public var secret: String {
        didSet {
            guard !usesEnvOverride else { return }
            if secret.isEmpty {
                KeychainHelper.remove(account: "sync-secret")
            } else {
                KeychainHelper.set(secret, account: "sync-secret")
            }
        }
    }

    private let usesEnvOverride: Bool

    public var isPaired: Bool { !baseURLString.isEmpty && !secret.isEmpty }

    private init() {
        let env = ProcessInfo.processInfo.environment
        if let url = env["KIES_BASE_URL"], let secret = env["KIES_SYNC_SECRET"] {
            usesEnvOverride = true
            baseURLString = url
            self.secret = secret
        } else {
            usesEnvOverride = false
            baseURLString = UserDefaults.standard.string(forKey: "kies.baseURL") ?? ""
            secret = KeychainHelper.get(account: "sync-secret") ?? ""
        }
    }
}

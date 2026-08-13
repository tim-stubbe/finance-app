import Foundation
import Combine

/// Server-Adresse + Secret fürs Koppeln - Adresse in UserDefaults (kein
/// Geheimnis), Secret im Keychain (siehe KeychainHelper).
final class PairingStore: ObservableObject {
    static let shared = PairingStore()

    @Published var baseURLString: String {
        didSet { UserDefaults.standard.set(baseURLString, forKey: "kies.baseURL") }
    }
    @Published var secret: String {
        didSet {
            if secret.isEmpty {
                KeychainHelper.remove(account: "sync-secret")
            } else {
                KeychainHelper.set(secret, account: "sync-secret")
            }
        }
    }

    var isPaired: Bool { !baseURLString.isEmpty && !secret.isEmpty }

    private init() {
        baseURLString = UserDefaults.standard.string(forKey: "kies.baseURL") ?? ""
        secret = KeychainHelper.get(account: "sync-secret") ?? ""
    }
}

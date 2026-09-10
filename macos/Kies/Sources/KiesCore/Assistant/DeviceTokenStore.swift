import Foundation
import Security

/// Keychain-Store für den **plaintext** Device-Token.
///
/// Backend speichert nur Hashes; der iOS-Client behält das Klartext-Token
/// im Keychain, wie in der P1-Sicherheitsanforderung beschrieben.
public final class DeviceTokenStore: ObservableObject {
    public static let shared = DeviceTokenStore()

    @Published public var token: String?

    private let service = "app.kies.device-token"
    private let account = "active-device-token"

    private init() {
        self.token = Self.load(account: account, service: service)
    }

    public func setToken(_ newValue: String?) {
        if let v = newValue, !v.isEmpty {
            Self.save(v, account: account, service: service)
            token = v
        } else {
            Self.remove(account: account, service: service)
            token = nil
        }
    }

    private static func save(_ value: String, account: String, service: String) {
        let data = Data(value.utf8)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)

        var attributes = query
        attributes[kSecValueData as String] = data
        SecItemAdd(attributes as CFDictionary, nil)
    }

    private static func load(account: String, service: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func remove(account: String, service: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
    }
}

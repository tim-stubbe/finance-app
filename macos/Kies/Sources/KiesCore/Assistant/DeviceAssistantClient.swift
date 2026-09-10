import Foundation

public enum AssistantClientError: Error {
    case notPaired
    case http(Int)
}

public struct AssistantChatRequest: Encodable {
    public var message: String
    public var history: [[String: String]]

    public init(message: String, history: [[String: String]] = []) {
        self.message = message
        self.history = history
    }
}

public struct AssistantSource: Decodable {
    public var title: String?
    public var url: String
    public var snippet: String?
}

public struct AssistantAction: Decodable {
    public var type: String

    // We keep it intentionally lax: the agent may return different action
    // shapes. SwiftUI can still render at least the summary/type.
    public var summary: String?
    public var title: String?
    public var requires_confirmation: Bool?

    enum CodingKeys: String, CodingKey {
        case type
        case summary
        case title
        case requires_confirmation
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        type = (try? c.decode(String.self, forKey: .type)) ?? ""
        summary = try? c.decode(String.self, forKey: .summary)
        title = try? c.decode(String.self, forKey: .title)
        requires_confirmation = try? c.decode(Bool.self, forKey: .requires_confirmation)
    }
}

public struct AssistantChatResponse: Decodable {
    public var ok: Bool
    public var domain: String?
    public var reply: String?
    public var actions: [AssistantAction]?
    public var sources: [AssistantSource]?

    enum CodingKeys: String, CodingKey {
        case ok
        case domain
        case reply
        case actions
        case sources
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = (try? c.decode(Bool.self, forKey: .ok)) ?? false
        domain = try? c.decode(String.self, forKey: .domain)
        reply = try? c.decode(String.self, forKey: .reply)
        actions = try? c.decode([AssistantAction].self, forKey: .actions)
        sources = try? c.decode([AssistantSource].self, forKey: .sources)
    }
}

/// Slim client für `/api/jarvis/chat` mit Device-Token.
///
/// - Web-Session wird NICHT genutzt
/// - Device-Token kommt aus der iOS Keychain (siehe `DeviceTokenStore`)
/// - Token wird als `X-Kies-Device-Token` Header gesendet.
public enum DeviceAssistantClient {

    public static func chat(message: String, history: [[String: String]] = []) async throws -> AssistantChatResponse {
        guard let token = DeviceTokenStore.shared.token else {
            throw AssistantClientError.notPaired
        }

        let pairing = PairingStore.shared
        guard pairing.isPaired else { throw AssistantClientError.notPaired }
        var base = pairing.baseURLString
        if base.hasSuffix("/") { base.removeLast() }
        guard let url = URL(string: base + "/api/jarvis/chat") else {
            throw AssistantClientError.http(-1)
        }

        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue(token, forHTTPHeaderField: "X-Kies-Device-Token")

        let body = AssistantChatRequest(message: message, history: history)
        req.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await KiesHTTP.session.data(for: req)
        try checkStatus(response)
        return try JSONDecoder().decode(AssistantChatResponse.self, from: data)
    }

    private static func checkStatus(_ response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse else { throw AssistantClientError.http(-1) }
        guard (200..<300).contains(http.statusCode) else {
            throw AssistantClientError.http(http.statusCode)
        }
    }
}

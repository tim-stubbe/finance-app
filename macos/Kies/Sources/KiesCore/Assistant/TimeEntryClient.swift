import Foundation

public struct DeviceProject: Decodable, Identifiable {
    public var id: Int
    public var name: String
    public var active: Bool

    enum CodingKeys: String, CodingKey {
        case id, name, active
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        active = (try? c.decode(Bool.self, forKey: .active)) ?? true
    }
}

public struct TimeEntry: Decodable {
    public var id: Int
    public var projectId: Int
    public var note: String?
    public var startedAt: Date
    public var stoppedAt: Date?
    public var minutes: Double?

    enum CodingKeys: String, CodingKey {
        case id
        case projectId = "project_id"
        case note
        case startedAt = "started_at"
        case stoppedAt = "stopped_at"
        case minutes
    }
}

/// Slim REST-Client für Zeiterfassung per Device-Token, nach dem exakten
/// Vorbild von `DeviceAssistantClient` (kein GRDB-Sync - TimeEntry ist
/// bewusst nicht Teil von `SYNC_REGISTRY`, siehe ROADMAP.md Live Activity).
///
/// - Web-Session wird NICHT genutzt
/// - Device-Token kommt aus der iOS Keychain (`DeviceTokenStore`)
/// - Token wird als `X-Kies-Device-Token` Header gesendet.
public enum TimeEntryClient {

    private static func baseURL() throws -> String {
        let pairing = PairingStore.shared
        guard pairing.isPaired else { throw AssistantClientError.notPaired }
        var base = pairing.baseURLString
        if base.hasSuffix("/") { base.removeLast() }
        return base
    }

    private static func request(path: String, method: String) throws -> URLRequest {
        guard let token = DeviceTokenStore.shared.token else {
            throw AssistantClientError.notPaired
        }
        guard let url = URL(string: try baseURL() + path) else {
            throw AssistantClientError.http(-1)
        }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue(token, forHTTPHeaderField: "X-Kies-Device-Token")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        return req
    }

    private static func checkStatus(_ response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse else { throw AssistantClientError.http(-1) }
        guard (200..<300).contains(http.statusCode) else {
            throw AssistantClientError.http(http.statusCode)
        }
    }

    private static func decoder() -> JSONDecoder {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }

    public static func projects() async throws -> [DeviceProject] {
        let req = try request(path: "/api/projects", method: "GET")
        let (data, response) = try await KiesHTTP.session.data(for: req)
        try checkStatus(response)
        return try decoder().decode([DeviceProject].self, from: data)
    }

    public static func runningEntry() async throws -> TimeEntry? {
        let req = try request(path: "/api/time-entries/running", method: "GET")
        let (data, response) = try await KiesHTTP.session.data(for: req)
        try checkStatus(response)
        if data.isEmpty || data == Data("null".utf8) { return nil }
        return try decoder().decode(TimeEntry.self, from: data)
    }

    public static func start(projectId: Int, note: String? = nil) async throws -> TimeEntry {
        var path = "/api/projects/\(projectId)/time-entries/start"
        if let note, !note.isEmpty,
           let encoded = note.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) {
            path += "?note=\(encoded)"
        }
        let req = try request(path: path, method: "POST")
        let (data, response) = try await KiesHTTP.session.data(for: req)
        try checkStatus(response)
        return try decoder().decode(TimeEntry.self, from: data)
    }

    public static func stop(entryId: Int) async throws -> TimeEntry {
        let req = try request(path: "/api/time-entries/\(entryId)/stop", method: "POST")
        let (data, response) = try await KiesHTTP.session.data(for: req)
        try checkStatus(response)
        return try decoder().decode(TimeEntry.self, from: data)
    }
}

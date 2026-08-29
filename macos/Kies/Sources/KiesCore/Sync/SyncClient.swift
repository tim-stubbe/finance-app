import Foundation

struct SyncPullResponse: Decodable {
    var server_time: String
    var entities: [String: [[String: AnyCodable]]]
    var tombstones: [Tombstone]

    struct Tombstone: Decodable {
        var entity_type: String
        var entity_id: Int64
        var space_id: Int64?
        var deleted_at: String
    }
}

struct SyncPushResponse: Decodable {
    var id_map: [String: Int64]
    var applied: [String]
    var conflicts: [ConflictEntry]

    struct ConflictEntry: Decodable {
        var entity_type: String
        var server_id: Int64?
        var reason: String
        // Nur bei reason=="server_newer" gesetzt (siehe backend/app/sync.py:
        // push()) - die aktuelle Server-Version der Zeile, fürs "Server
        // behalten" in SyncEngine.resolveConflictKeepServer (per applyRow
        // direkt in die lokale Tabelle übernommen, kein erneuter Pull nötig).
        var server_data: [String: AnyCodable]?
    }
}

/// Locker getypter JSON-Wert - die Pull-Antwort enthält je Entität rohe
/// Tabellenspalten unterschiedlichen Typs (siehe backend/app/sync.py:
/// _serialize_row), ein festes Decodable-Modell pro Entität würde hier nur
/// Mapping-Code duplizieren, den AppDatabase.apply(...) ohnehin selbst pro
/// Spalte extrahiert.
enum AnyCodable: Codable {
    case string(String)
    case int(Int64)
    case double(Double)
    case bool(Bool)
    case null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Int64.self) { self = .int(v) }
        else if let v = try? c.decode(Double.self) { self = .double(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else { self = .null }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let v): try c.encode(v)
        case .int(let v): try c.encode(v)
        case .double(let v): try c.encode(v)
        case .bool(let v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }

    var stringValue: String? {
        switch self {
        case .string(let v): return v
        case .int(let v): return String(v)
        case .double(let v): return String(v)
        case .bool(let v): return String(v)
        case .null: return nil
        }
    }

    var int64Value: Int64? {
        switch self {
        case .int(let v): return v
        case .double(let v): return Int64(v)
        case .string(let v): return Int64(v)
        default: return nil
        }
    }

    var boolValue: Bool? {
        switch self {
        case .bool(let v): return v
        case .int(let v): return v != 0
        default: return nil
        }
    }

    var doubleValue: Double? {
        switch self {
        case .double(let v): return v
        case .int(let v): return Double(v)
        case .string(let v): return Double(v)
        default: return nil
        }
    }
}

enum SyncClientError: Error {
    case notPaired
    case http(Int)
}

/// Spricht mit den Phase-1-Endpunkten (backend/app/sync.py) - X-Sync-Secret
/// statt Session-Cookie (kein Login-System, siehe sync.py-Docstring). Die
/// selbstsignierte-Zertifikat-Behandlung liegt jetzt zentral in KiesHTTP,
/// damit Apple-Health-Sync und Siri-Intent dieselbe Session nutzen.
final class SyncClient {
    private var session: URLSession { KiesHTTP.session }

    private func request(path: String, query: [String: String] = [:]) throws -> URLRequest {
        let pairing = PairingStore.shared
        guard pairing.isPaired, var comps = URLComponents(string: pairing.baseURLString + path) else {
            throw SyncClientError.notPaired
        }
        if !query.isEmpty {
            comps.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) }
        }
        var req = URLRequest(url: comps.url!)
        req.setValue(pairing.secret, forHTTPHeaderField: "X-Sync-Secret")
        return req
    }

    func pull(since: String?) async throws -> SyncPullResponse {
        var query: [String: String] = [:]
        if let since { query["since"] = since }
        let req = try request(path: "/api/sync/pull", query: query)
        let (data, response) = try await session.data(for: req)
        try Self.checkStatus(response)
        return try JSONDecoder().decode(SyncPullResponse.self, from: data)
    }

    func push(ops: [[String: Any]], spaceID: Int64?) async throws -> SyncPushResponse {
        var req = try request(path: "/api/sync/push")
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        var body: [String: Any] = ["ops": ops]
        if let spaceID { body["space_id"] = spaceID }
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await session.data(for: req)
        try Self.checkStatus(response)
        return try JSONDecoder().decode(SyncPushResponse.self, from: data)
    }

    private static func checkStatus(_ response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? -1
            throw SyncClientError.http(code)
        }
    }
}

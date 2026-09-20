import Foundation
import CoreLocation
import KiesCore

@MainActor
final class DriveSettings: ObservableObject {
    static let shared = DriveSettings()
    @Published var baseURL: String { didSet { UserDefaults.standard.set(baseURL, forKey: "drive.baseURL") } }
    @Published var fuel: FuelKind { didSet { UserDefaults.standard.set(fuel.rawValue, forKey: "drive.fuel") } }
    @Published var avoidTolls: Bool { didSet { UserDefaults.standard.set(avoidTolls, forKey: "drive.avoidTolls") } }
    @Published var avoidHighways: Bool { didSet { UserDefaults.standard.set(avoidHighways, forKey: "drive.avoidHighways") } }
    @Published var mapAppearance: DriveMapAppearance { didSet { UserDefaults.standard.set(mapAppearance.rawValue, forKey: "drive.mapAppearance") } }
    @Published var voiceGuidance: Bool { didSet { UserDefaults.standard.set(voiceGuidance, forKey: "drive.voiceGuidance") } }

    /// Fahrzeugdaten für Reichweiten-/Tankvorschläge.
    /// Einheit: L/100km und Liter.
    @Published var consumptionLPer100km: Double { didSet { UserDefaults.standard.set(consumptionLPer100km, forKey: "drive.consumptionLPer100km") } }
    @Published var tankCapacityL: Double { didSet { UserDefaults.standard.set(tankCapacityL, forKey: "drive.tankCapacityL") } }
    @Published var fuelPricePerLitre: Double { didSet { UserDefaults.standard.set(fuelPricePerLitre, forKey: "drive.fuelPricePerLitre") } }
    @Published var targetSpeedKmh: Double { didSet { UserDefaults.standard.set(targetSpeedKmh, forKey: "drive.targetSpeedKmh") } }

    private init() {
        baseURL = UserDefaults.standard.string(forKey: "drive.baseURL") ?? "https://100.72.226.91:8000"
        fuel = FuelKind(rawValue: UserDefaults.standard.string(forKey: "drive.fuel") ?? "diesel") ?? .diesel
        avoidTolls = UserDefaults.standard.object(forKey: "drive.avoidTolls") as? Bool ?? true
        avoidHighways = UserDefaults.standard.object(forKey: "drive.avoidHighways") as? Bool ?? false
        mapAppearance = DriveMapAppearance(rawValue: UserDefaults.standard.string(forKey: "drive.mapAppearance") ?? "standard") ?? .standard
        voiceGuidance = UserDefaults.standard.object(forKey: "drive.voiceGuidance") as? Bool ?? true

        consumptionLPer100km = UserDefaults.standard.object(forKey: "drive.consumptionLPer100km") as? Double ?? 6.5
        tankCapacityL = UserDefaults.standard.object(forKey: "drive.tankCapacityL") as? Double ?? 50.0
        fuelPricePerLitre = UserDefaults.standard.object(forKey: "drive.fuelPricePerLitre") as? Double ?? 1.75
        targetSpeedKmh = UserDefaults.standard.object(forKey: "drive.targetSpeedKmh") as? Double ?? 150
    }
    var isReady: Bool { !baseURL.isEmpty && DeviceTokenStore.shared.token != nil }
    /// App-Version + Build, z.B. "1.0 (3)" - zur Diagnose, ob ein Gerät noch
    /// eine veraltete Build-Version ausführt.
    static var appVersionString: String {
        let info = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "?"
        let build = info?["CFBundleVersion"] as? String ?? "?"
        return "\(version) (\(build))"
    }
}

enum DriveAPIError: LocalizedError {
    case configuration, response(Int), invalidData
    var errorDescription: String? {
        switch self {
        case .configuration: "Server-Adresse oder Geräte-Token fehlt."
        case .response(let code): "Serverfehler (HTTP \(code))."
        case .invalidData: "Die Serverantwort konnte nicht gelesen werden."
        }
    }
}

@MainActor
enum DriveAPI {
    private static func request(path: String, method: String = "GET", body: Data? = nil) throws -> URLRequest {
        let settings = DriveSettings.shared
        guard let token = DeviceTokenStore.shared.token, !token.isEmpty,
              let url = URL(string: settings.baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + path)
        else { throw DriveAPIError.configuration }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body
        request.setValue(token, forHTTPHeaderField: "X-Kies-Device-Token")
        if body != nil { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        return request
    }

    private static func data(for request: URLRequest) async throws -> Data {
        let (data, response) = try await KiesHTTP.session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw DriveAPIError.invalidData }
        guard 200..<300 ~= http.statusCode else { throw DriveAPIError.response(http.statusCode) }
        return data
    }

    static func stations(near coordinate: CLLocationCoordinate2D, fuel: FuelKind, radiusKm: Double = 8) async throws -> [FuelStation] {
        let boundedRadius = min(12, max(3, radiusKm))
        let path = String(format: "/api/navigation/fuel-stations?lat=%.6f&lon=%.6f&radius_km=%.1f&fuel=%@",
                          coordinate.latitude, coordinate.longitude, boundedRadius, fuel.apiValue)
        let payload = try await data(for: try request(path: path))
        return try JSONDecoder().decode(FuelStationEnvelope.self, from: payload).stations
    }

    static func askJarvis(_ message: String) async throws -> String {
        let body = try JSONSerialization.data(withJSONObject: ["message": message, "history": []])
        let payload = try await data(for: try request(path: "/api/jarvis/chat", method: "POST", body: body))
        let result = try JSONDecoder().decode(DriveChatResponse.self, from: payload)
        return result.reply ?? "Jarvis hat keine Antwort geliefert."
    }

    static func speedLimits(along points: [CLLocationCoordinate2D]) async throws -> [SpeedLimitResult] {
        guard !points.isEmpty else { return [] }
        let body = try JSONSerialization.data(withJSONObject: [
            "points": points.map { ["lat": $0.latitude, "lon": $0.longitude] },
        ])
        let payload = try await data(for: try request(path: "/api/navigation/speed-limits", method: "POST", body: body))
        return try JSONDecoder().decode(SpeedLimitEnvelope.self, from: payload).limits
    }
}

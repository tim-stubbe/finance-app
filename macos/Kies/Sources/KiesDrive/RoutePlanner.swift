import Foundation
import MapKit
import AVFoundation

private extension Array {
    subscript(safe index: Int) -> Element? { indices.contains(index) ? self[index] : nil }
}

/// Für den Offline-Fallback zwischengespeicherte Routen- und Tankstellendaten -
/// bewusst schlank (kein `MKRoute`, das ist nicht `Codable`), damit die letzte
/// berechnete Route auch ohne Netzverbindung als Text/Liste angezeigt werden kann.
/// Eine echte Offline-Kartendarstellung bietet MapKit über keine öffentliche API an.
struct CachedRoute: Codable {
    struct Step: Codable { let instructions: String; let distance: Double }
    struct Leg: Codable { let distance: Double; let travelTime: TimeInterval; let steps: [Step] }
    let destinationName: String
    let legs: [Leg]
    let stations: [FuelStation]
    let savedAt: Date
}

@MainActor
final class RoutePlanner: NSObject, ObservableObject, AVSpeechSynthesizerDelegate {
    /// Eine gemeinsame Instanz für die SwiftUI-Oberfläche und die
    /// CarPlay-Szene, damit beide dieselbe Route/Tankstellenliste sehen.
    static let shared = RoutePlanner()

    @Published var destinationText = ""
    @Published var suggestions: [MKMapItem] = []
    @Published var destination: MKMapItem?
    @Published var viaStation: FuelStation?
    @Published var legs: [MKRoute] = []
    @Published var alternatives: [MKRoute] = []
    @Published var stations: [FuelStation] = []
    @Published var isLoading = false
    @Published var errorMessage: String?
    @Published var isRecalculating = false
    @Published var lastAnnouncement: String?
    @Published var speedWarning: Bool = false
    @Published var offlineRoute: CachedRoute?

    /// Tempolimits entlang der Route, parallel zu `speedLimitPoints` indiziert.
    private var speedLimitPoints: [CLLocationCoordinate2D] = []
    private var speedLimits: [SpeedLimitResult] = []

    private let synthesizer = AVSpeechSynthesizer()
    private var announcedStepKeys: Set<String> = []
    private var offRouteStrikes = 0
    private static let cacheKey = "drive.offlineRoute"

    override init() {
        super.init()
        synthesizer.delegate = self
        offlineRoute = Self.loadCache()
    }

    /// Erste Teilstrecke - für Rückwärtskompatibilität und schnellen Zugriff
    /// auf die "Hauptroute" (ohne Zwischenstopp identisch mit der Gesamtroute).
    var route: MKRoute? { legs.first }
    var totalDistance: Double { legs.reduce(0) { $0 + $1.distance } }
    var totalTravelTime: TimeInterval { legs.reduce(0) { $0 + $1.expectedTravelTime } }

    func searchDestination(near coordinate: CLLocationCoordinate2D?) async {
        guard destinationText.count > 2 else { suggestions = []; return }
        let request = MKLocalSearch.Request()
        request.naturalLanguageQuery = destinationText
        if let coordinate { request.region = .init(center: coordinate, latitudinalMeters: 100_000, longitudinalMeters: 100_000) }
        do { suggestions = try await MKLocalSearch(request: request).start().mapItems }
        catch { errorMessage = "Zielsuche fehlgeschlagen: \(error.localizedDescription)" }
    }

    func calculate(from start: CLLocationCoordinate2D, settings: DriveSettings) async {
        guard let destination else { return }
        isLoading = true; errorMessage = nil; stations = []
        defer { isLoading = false }
        let startItem = MKMapItem(placemark: MKPlacemark(coordinate: start))
        do {
            if let viaStation {
                // MapKit kennt keine mehrgliedrigen Routen - daher zwei
                // Teilstrecken (Start→Tankstelle, Tankstelle→Ziel) einzeln
                // berechnen und aneinanderhängen.
                let viaItem = MKMapItem(placemark: MKPlacemark(coordinate: viaStation.coordinate))
                guard let leg1 = try await computeRoutes(from: startItem, to: viaItem, settings: settings, alternates: false).first,
                      let leg2 = try await computeRoutes(from: viaItem, to: destination, settings: settings, alternates: false).first
                else { throw DriveAPIError.invalidData }
                legs = [leg1, leg2]
                alternatives = []
            } else {
                let routes = try await computeRoutes(from: startItem, to: destination, settings: settings, alternates: true)
                alternatives = routes
                legs = routes.first.map { [$0] } ?? []
            }
            announcedStepKeys = []
            offRouteStrikes = 0
            await loadStations(fuel: settings.fuel)
            await loadSpeedLimits()
            cacheForOffline()
        } catch { errorMessage = "Route konnte nicht berechnet werden: \(error.localizedDescription)" }
    }

    /// Speichert die aktuell berechnete Route + Tankstellenliste lokal, damit
    /// sie bei fehlender Verbindung (z.B. Funkloch unterwegs) weiter als Text
    /// angezeigt werden kann - kein Kartenmaterial, nur Fahrhinweise und Preise.
    private func cacheForOffline() {
        guard !legs.isEmpty else { return }
        let cached = CachedRoute(
            destinationName: destination?.name ?? destinationText,
            legs: legs.map { leg in
                CachedRoute.Leg(distance: leg.distance, travelTime: leg.expectedTravelTime,
                                 steps: leg.steps.map { .init(instructions: $0.instructions, distance: $0.distance) })
            },
            stations: stations,
            savedAt: Date()
        )
        offlineRoute = cached
        if let data = try? JSONEncoder().encode(cached) { UserDefaults.standard.set(data, forKey: Self.cacheKey) }
    }

    private static func loadCache() -> CachedRoute? {
        guard let data = UserDefaults.standard.data(forKey: Self.cacheKey) else { return nil }
        return try? JSONDecoder().decode(CachedRoute.self, from: data)
    }

    /// Löscht die zwischengespeicherte Offline-Route (z.B. wenn sie veraltet ist).
    func clearOfflineCache() {
        offlineRoute = nil
        UserDefaults.standard.removeObject(forKey: Self.cacheKey)
    }

    // MARK: - Navigation live: Ansagen, Tempowarnung, automatische Neuberechnung

    /// Wird laufend mit der aktuellen Position während der Fahrt aufgerufen.
    /// Kümmert sich um drei Dinge: nächste Fahranweisung ansagen, Tempolimit-
    /// Überschreitung erkennen und bei Abweichung von der Route automatisch
    /// neu berechnen.
    func updateProgress(at location: CLLocation, settings: DriveSettings) {
        guard let route = legs.first else { return }
        checkSpeedLimit(at: location.coordinate, speedMps: location.speed)
        if settings.voiceGuidance { announceNextStep(near: location.coordinate, in: route) }
        checkForDeviation(from: location.coordinate, route: route, settings: settings)
    }

    private func checkSpeedLimit(at coordinate: CLLocationCoordinate2D, speedMps: Double) {
        guard speedMps >= 0, let limit = currentSpeedLimit(near: coordinate), let maxspeed = limit.maxspeed else {
            speedWarning = false
            return
        }
        let speedKmh = speedMps * 3.6
        // 5 km/h Toleranz für GPS-Ungenauigkeit / Tacho-Rundung.
        speedWarning = speedKmh > Double(maxspeed) + 5
    }

    private func announceNextStep(near coordinate: CLLocationCoordinate2D, in route: MKRoute) {
        let here = CLLocation(latitude: coordinate.latitude, longitude: coordinate.longitude)
        for (index, step) in route.steps.enumerated() where index > 0 {
            let key = "\(index):\(step.instructions)"
            guard !announcedStepKeys.contains(key) else { continue }
            let stepStart = step.polyline.coordinate
            let distance = here.distance(from: CLLocation(latitude: stepStart.latitude, longitude: stepStart.longitude))
            if distance <= 120 {
                announcedStepKeys.insert(key)
                speak(step.instructions.isEmpty ? "Weiter geradeaus" : step.instructions)
                lastAnnouncement = step.instructions
                break
            }
        }
    }

    private func speak(_ text: String) {
        guard !text.isEmpty else { return }
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "de-DE")
        synthesizer.speak(utterance)
    }

    /// Zählt aufeinanderfolgende Positionsmeldungen weit abseits der Route und
    /// löst nach ein paar Treffern (nicht schon beim ersten GPS-Ausreißer) eine
    /// automatische Neuberechnung ab der aktuellen Position aus.
    private func checkForDeviation(from coordinate: CLLocationCoordinate2D, route: MKRoute, settings: DriveSettings) {
        guard !isLoading, !isRecalculating else { return }
        let here = CLLocation(latitude: coordinate.latitude, longitude: coordinate.longitude)
        let samples = sample(route.polyline, maximum: 120)
        let nearest = samples.map { here.distance(from: CLLocation(latitude: $0.latitude, longitude: $0.longitude)) }.min() ?? 0
        if nearest > 80 {
            offRouteStrikes += 1
        } else {
            offRouteStrikes = 0
        }
        guard offRouteStrikes >= 3 else { return }
        offRouteStrikes = 0
        Task {
            isRecalculating = true
            lastAnnouncement = "Route wird neu berechnet …"
            await calculate(from: coordinate, settings: settings)
            isRecalculating = false
        }
    }

    /// Lädt Tempolimits für abgetastete Routenpunkte (OpenStreetMap/Overpass).
    /// Fehler hier werden bewusst nicht als `errorMessage` angezeigt, damit ein
    /// überlasteter Overpass-Dienst nicht die restliche Routenplanung blockiert.
    func loadSpeedLimits() async {
        guard !legs.isEmpty else { speedLimitPoints = []; speedLimits = []; return }
        let points = legs.flatMap { sample($0.polyline, maximum: 80) }
        speedLimitPoints = points
        speedLimits = (try? await DriveAPI.speedLimits(along: points)) ?? []
    }

    /// Aktuelles Tempolimit für den nächstgelegenen abgetasteten Routenpunkt
    /// zur übergebenen Position (z.B. der aktuelle Standort während der Fahrt).
    func currentSpeedLimit(near coordinate: CLLocationCoordinate2D) -> SpeedLimitResult? {
        guard !speedLimitPoints.isEmpty else { return nil }
        let here = CLLocation(latitude: coordinate.latitude, longitude: coordinate.longitude)
        var bestIndex = 0
        var bestDistance = Double.greatestFiniteMagnitude
        for (i, point) in speedLimitPoints.enumerated() {
            let dist = here.distance(from: CLLocation(latitude: point.latitude, longitude: point.longitude))
            if dist < bestDistance { bestDistance = dist; bestIndex = i }
        }
        guard bestDistance <= 200 else { return nil }
        return speedLimits[safe: bestIndex]
    }

    private func computeRoutes(from source: MKMapItem, to destination: MKMapItem, settings: DriveSettings, alternates: Bool) async throws -> [MKRoute] {
        let request = MKDirections.Request()
        request.source = source
        request.destination = destination
        request.transportType = .automobile
        request.requestsAlternateRoutes = alternates
        request.tollPreference = settings.avoidTolls ? .avoid : .any
        request.highwayPreference = settings.avoidHighways ? .avoid : .any
        return try await MKDirections(request: request).calculate().routes
    }

    func loadStations(fuel: FuelKind) async {
        guard !legs.isEmpty else { return }
        let points = legs.flatMap { sample($0.polyline, maximum: 10) }
        var unique: [String: FuelStation] = [:]
        await withTaskGroup(of: [FuelStation].self) { group in
            for point in points { group.addTask { (try? await DriveAPI.stations(near: point, fuel: fuel)) ?? [] } }
            for await batch in group { for station in batch { unique[station.id] = station } }
        }
        let routePoints = legs.flatMap { sample($0.polyline, maximum: 80) }.map { CLLocation(latitude: $0.latitude, longitude: $0.longitude) }
        stations = unique.values.filter { station in
            let point = CLLocation(latitude: station.lat, longitude: station.lon)
            return routePoints.map { $0.distance(from: point) }.min() ?? .greatestFiniteMagnitude < 8_000
        }.sorted { $0.price == $1.price ? $0.distanceKm < $1.distanceKm : $0.price < $1.price }
    }

    /// Fügt eine Tankstelle als Zwischenstopp ein (oder entfernt sie erneut,
    /// wenn sie bereits als Zwischenstopp gesetzt ist) und berechnet die
    /// Route neu.
    func toggleWaypoint(_ station: FuelStation, from start: CLLocationCoordinate2D, settings: DriveSettings) async {
        viaStation = (viaStation?.id == station.id) ? nil : station
        await calculate(from: start, settings: settings)
    }

    private func sample(_ polyline: MKPolyline, maximum: Int) -> [CLLocationCoordinate2D] {
        guard polyline.pointCount > 0 else { return [] }
        let coordinates = UnsafeMutablePointer<CLLocationCoordinate2D>.allocate(capacity: polyline.pointCount)
        defer { coordinates.deallocate() }
        polyline.getCoordinates(coordinates, range: NSRange(location: 0, length: polyline.pointCount))
        let stride = max(1, polyline.pointCount / maximum)
        return Swift.stride(from: 0, to: polyline.pointCount, by: stride).map { coordinates[$0] }
    }
}

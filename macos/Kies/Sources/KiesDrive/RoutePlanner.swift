import Foundation
import MapKit

@MainActor
final class RoutePlanner: ObservableObject {
    @Published var destinationText = ""
    @Published var suggestions: [MKMapItem] = []
    @Published var destination: MKMapItem?
    @Published var viaStation: FuelStation?
    @Published var legs: [MKRoute] = []
    @Published var alternatives: [MKRoute] = []
    @Published var stations: [FuelStation] = []
    @Published var isLoading = false
    @Published var errorMessage: String?

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
            await loadStations(fuel: settings.fuel)
        } catch { errorMessage = "Route konnte nicht berechnet werden: \(error.localizedDescription)" }
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

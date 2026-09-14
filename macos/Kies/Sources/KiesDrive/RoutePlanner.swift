import Foundation
import MapKit

@MainActor
final class RoutePlanner: ObservableObject {
    @Published var destinationText = ""
    @Published var suggestions: [MKMapItem] = []
    @Published var destination: MKMapItem?
    @Published var route: MKRoute?
    @Published var alternatives: [MKRoute] = []
    @Published var stations: [FuelStation] = []
    @Published var isLoading = false
    @Published var errorMessage: String?

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
        let request = MKDirections.Request()
        request.source = MKMapItem(placemark: MKPlacemark(coordinate: start))
        request.destination = destination
        request.transportType = .automobile
        request.requestsAlternateRoutes = true
        request.tollPreference = settings.avoidTolls ? .avoid : .any
        request.highwayPreference = settings.avoidHighways ? .avoid : .any
        do {
            let response = try await MKDirections(request: request).calculate()
            alternatives = response.routes
            route = response.routes.first
            await loadStations(fuel: settings.fuel)
        } catch { errorMessage = "Route konnte nicht berechnet werden: \(error.localizedDescription)" }
    }

    func loadStations(fuel: FuelKind) async {
        guard let route else { return }
        let points = sample(route.polyline, maximum: 10)
        var unique: [String: FuelStation] = [:]
        await withTaskGroup(of: [FuelStation].self) { group in
            for point in points { group.addTask { (try? await DriveAPI.stations(near: point, fuel: fuel)) ?? [] } }
            for await batch in group { for station in batch { unique[station.id] = station } }
        }
        let routePoints = sample(route.polyline, maximum: 80).map { CLLocation(latitude: $0.latitude, longitude: $0.longitude) }
        stations = unique.values.filter { station in
            let point = CLLocation(latitude: station.lat, longitude: station.lon)
            return routePoints.map { $0.distance(from: point) }.min() ?? .greatestFiniteMagnitude < 8_000
        }.sorted { $0.price == $1.price ? $0.distanceKm < $1.distanceKm : $0.price < $1.price }
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

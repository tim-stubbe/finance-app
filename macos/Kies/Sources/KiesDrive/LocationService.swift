import Foundation
import CoreLocation

@MainActor
final class LocationService: NSObject, ObservableObject, CLLocationManagerDelegate {
    /// Gemeinsame Instanz für die SwiftUI-Oberfläche und die CarPlay-Szene.
    static let shared = LocationService()

    @Published var location: CLLocation?
    @Published var authorization: CLAuthorizationStatus = .notDetermined
    private let manager = CLLocationManager()

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBestForNavigation
        manager.distanceFilter = 8
        authorization = manager.authorizationStatus
    }

    func start() {
        #if os(iOS)
        // "Always" statt nur "when in use", damit Ansagen und CarPlay-
        // Navigation auch bei gesperrtem Bildschirm weiterlaufen.
        manager.requestAlwaysAuthorization()
        manager.allowsBackgroundLocationUpdates = true
        manager.pausesLocationUpdatesAutomatically = false
        #else
        manager.requestAlwaysAuthorization()
        #endif
        manager.startUpdatingLocation()
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        authorization = manager.authorizationStatus
        #if os(iOS)
        if authorization == .authorizedAlways || authorization == .authorizedWhenInUse { manager.startUpdatingLocation() }
        #else
        if authorization == .authorizedAlways { manager.startUpdatingLocation() }
        #endif
    }
    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        location = locations.last
    }
}

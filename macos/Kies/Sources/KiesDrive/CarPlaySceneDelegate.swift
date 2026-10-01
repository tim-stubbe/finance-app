#if os(iOS)
import CarPlay
import Combine
import MapKit

/// CarPlay-Einstiegspunkt für Kies Drive (Kategorie "CarPlay Fueling").
///
/// Zeigt eine einfache Listen-Oberfläche mit der aktuellen Route und den
/// Tankstellen entlang des Weges - dieselben Daten wie in der iPhone-App,
/// über `RoutePlanner.shared`/`LocationService.shared` geteilt. CarPlay
/// erlaubt für diese Kategorie keine eigene Kartendarstellung (das bleibt
/// der Rolle "Navigation" mit `CPMapTemplate` vorbehalten, die von Apple
/// separat freigegeben werden müsste) - eine Liste reicht aber aus, um
/// unterwegs den nächsten Tankstopp auszuwählen, ohne zum Telefon greifen
/// zu müssen.
///
/// Hinweis: Damit diese Szene auf einem echten Fahrzeug-Bildschirm
/// erscheint, muss Apple dem Entwicklerteam die CarPlay-Fueling-
/// Berechtigung freigeben (developer.apple.com/contact/carplay) - ohne
/// Freigabe läuft der Code nur im Xcode-CarPlay-Simulator.
final class CarPlaySceneDelegate: NSObject, CPTemplateApplicationSceneDelegate {
    private var interfaceController: CPInterfaceController?
    private var cancellables: Set<AnyCancellable> = []

    func templateApplicationScene(
        _ templateApplicationScene: CPTemplateApplicationScene,
        didConnect interfaceController: CPInterfaceController
    ) {
        self.interfaceController = interfaceController
        LocationService.shared.start()
        observePlanner()
        interfaceController.setRootTemplate(makeListTemplate(), animated: false, completion: nil)
    }

    func templateApplicationScene(
        _ templateApplicationScene: CPTemplateApplicationScene,
        didDisconnectInterfaceController interfaceController: CPInterfaceController
    ) {
        self.interfaceController = nil
        cancellables.removeAll()
    }

    /// Baut die Liste bei jeder Routen-/Tankstellenänderung neu auf.
    private func observePlanner() {
        let planner = RoutePlanner.shared
        Publishers.CombineLatest3(planner.$legs, planner.$stations, planner.$viaStations)
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _, _, _ in
                guard let self, let listTemplate = self.interfaceController?.rootTemplate as? CPListTemplate else { return }
                listTemplate.updateSections(self.makeSections())
            }
            .store(in: &cancellables)
    }

    private func makeListTemplate() -> CPListTemplate {
        let template = CPListTemplate(title: "Kies Drive", sections: makeSections())
        return template
    }

    private func makeSections() -> [CPListSection] {
        let planner = RoutePlanner.shared
        var sections: [CPListSection] = []

        if !planner.legs.isEmpty {
            let distance = formatDistance(planner.totalDistance)
            let time = formatTime(planner.totalTravelTime)
            let routeItem = CPListItem(text: planner.destination?.name ?? "Aktuelle Route", detailText: "\(distance) · \(time)")
            routeItem.handler = { [weak self] _, completion in
                self?.openInMaps()
                completion()
            }
            sections.append(CPListSection(items: [routeItem], header: "Route", sectionIndexTitle: nil))
        } else {
            let empty = CPListItem(text: "Keine Route geplant", detailText: "Ziel bitte am iPhone eingeben")
            sections.append(CPListSection(items: [empty]))
        }

        if !planner.stations.isEmpty {
            let stationItems: [CPListItem] = planner.stations.prefix(8).map { station in
                let isVia = planner.viaStations.contains(where: { $0.id == station.id })
                let name = station.brand.isEmpty ? station.name : station.brand
                let item = CPListItem(
                    text: isVia ? "✓ \(name)" : name,
                    detailText: String(format: "%.3f € · %.1f km", station.price, station.distanceKm)
                )
                item.handler = { [weak self] _, completion in
                    self?.toggleWaypoint(station)
                    completion()
                }
                return item
            }
            sections.append(CPListSection(items: stationItems, header: "Tankstellen auf der Strecke", sectionIndexTitle: nil))
        }

        return sections
    }

    private func toggleWaypoint(_ station: FuelStation) {
        guard let start = LocationService.shared.location?.coordinate else { return }
        Task { await RoutePlanner.shared.toggleWaypoint(station, from: start, settings: DriveSettings.shared) }
    }

    private func openInMaps() {
        guard let destination = RoutePlanner.shared.destination else { return }
        destination.openInMaps(launchOptions: [MKLaunchOptionsDirectionsModeKey: MKLaunchOptionsDirectionsModeDriving])
    }

    private func formatDistance(_ metres: Double) -> String { metres >= 1000 ? String(format: "%.1f km", metres / 1000) : "\(Int(metres)) m" }
    private func formatTime(_ seconds: TimeInterval) -> String { let m = Int(seconds / 60); return m >= 60 ? "\(m / 60) Std. \(m % 60) Min." : "\(m) Min." }
}
#endif

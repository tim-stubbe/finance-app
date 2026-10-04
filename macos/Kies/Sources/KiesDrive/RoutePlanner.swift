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
    /// Shared by the phone UI and CarPlay so both surfaces operate on the
    /// same route, stops and long-trip plan.
    static let shared = RoutePlanner()
    @Published var destinationText = ""
    @Published var suggestions: [MKMapItem] = []
    @Published var destination: MKMapItem?
    @Published var viaStations: [FuelStation] = []
    @Published var legs: [MKRoute] = []
    @Published var alternatives: [MKRoute] = []
    @Published var stations: [FuelStation] = []
    @Published var isLoading = false
    @Published var errorMessage: String?
    @Published var isRecalculating = false
    @Published var lastAnnouncement: String?
    @Published var speedWarning: Bool = false
    @Published var offlineRoute: CachedRoute?
    @Published var longTripPlan: LongTripPlan?
    @Published var isNavigating = false
    @Published var activeRouteLock: ActiveRouteLock?
    private var comparisonRoute: MKRoute?
    private var researchedToll: TollCost = .unknown(reason: "Mautrecherche läuft noch.")

    /// Tempolimits entlang der Route, parallel zu `speedLimitPoints` indiziert.
    private var speedLimitPoints: [CLLocationCoordinate2D] = []
    private var speedLimits: [SpeedLimitResult] = []

    private let synthesizer = AVSpeechSynthesizer()
    private var announcedStepKeys: Set<String> = []
    private var offRouteStrikes = 0
    private var stationLoadGeneration = UUID()
    private var didAttemptAutomaticRestore = false
    private static let cacheKey = "drive.offlineRoute"
    private let routeLockStore = RouteLockStore.shared

    override init() {
        super.init()
        synthesizer.delegate = self
        offlineRoute = Self.loadCache()
        activeRouteLock = routeLockStore.activeLock
        if let lock = activeRouteLock {
            destinationText = lock.destinationName
            destination = MKMapItem(placemark: MKPlacemark(coordinate: lock.destination.clLocationCoordinate))
        }
    }

    /// Erste Teilstrecke - für Rückwärtskompatibilität und schnellen Zugriff
    /// auf die "Hauptroute" (ohne Zwischenstopp identisch mit der Gesamtroute).
    var route: MKRoute? { legs.first }
    var totalDistance: Double { legs.reduce(0) { $0 + $1.distance } }
    var totalTravelTime: TimeInterval { legs.reduce(0) { $0 + $1.expectedTravelTime } }

    func startNavigation() {
        guard !legs.isEmpty else { return }
        persistActiveTrip()
        isNavigating = true
        announcedStepKeys = []
        lastAnnouncement = nextInstruction ?? "Route gestartet"
        speak(lastAnnouncement ?? "Route gestartet")
    }

    func stopNavigation() {
        isNavigating = false
        synthesizer.stopSpeaking(at: .immediate)
        lastAnnouncement = nil
        speedWarning = false
    }

    /// Beendet den Trip bewusst. Ein normales Stoppen/Pausieren der Navigation
    /// loescht den Lock dagegen nicht, damit Rast und App-Neustart sicher sind.
    func completeActiveTrip() {
        stopNavigation()
        routeLockStore.finish()
        activeRouteLock = nil
        routeLockStore.clearFinished()
    }

    private func persistActiveTrip() {
        guard let destination else { return }
        let coordinate = destination.placemark.coordinate
        let options = LockedRouteOptions(avoidTolls: DriveSettings.shared.avoidTolls,
                                         avoidHighways: DriveSettings.shared.avoidHighways)
        let existing = routeLockStore.activeLock
        let waypoints: [LockedWaypoint]
        if let existing, existing.isActive {
            waypoints = existing.waypoints
        } else {
            waypoints = viaStations.map {
                LockedWaypoint(id: $0.id, name: $0.brand.isEmpty ? $0.name : $0.brand,
                               coordinate: .init(latitude: $0.lat, longitude: $0.lon),
                               required: true, optionsAfter: nil)
            }
        }
        let lock = ActiveRouteLock(
            id: existing?.id ?? UUID(), title: existing?.title ?? (destination.name ?? destinationText),
            destinationName: destination.name ?? destinationText,
            destination: .init(latitude: coordinate.latitude, longitude: coordinate.longitude),
            waypoints: waypoints, defaultOptions: existing?.defaultOptions ?? options,
            corridorWidthMetres: existing?.corridorWidthMetres ?? 5_000,
            corridorPoints: existing?.corridorPoints ?? legs.flatMap { sample($0.polyline, maximum: 120) }
                .map { .init(latitude: $0.latitude, longitude: $0.longitude) },
            visitedWaypointIDs: existing?.visitedWaypointIDs ?? [],
            status: .active, createdAt: existing?.createdAt ?? Date(), updatedAt: Date()
        )
        routeLockStore.save(lock)
        activeRouteLock = lock
    }

    /// Einmaliger Wiederanlauf nach App-Start. Erst mit einer echten Position
    /// wird neu gerechnet; dadurch setzt MapKit am passenden aktuellen
    /// Routenabschnitt an, waehrend Pflichtpunkte und Segmentregeln erhalten bleiben.
    func restoreActiveTripIfNeeded(from current: CLLocationCoordinate2D, settings: DriveSettings) async {
        guard !didAttemptAutomaticRestore else { return }
        didAttemptAutomaticRestore = true
        guard let lock = routeLockStore.activeLock, lock.isActive else { return }
        activeRouteLock = lock
        destinationText = lock.destinationName
        destination = MKMapItem(placemark: MKPlacemark(coordinate: lock.destination.clLocationCoordinate))
        await calculate(from: current, settings: settings)
        if !legs.isEmpty { startNavigation() }
    }

    func restoreActiveTrip(from current: CLLocationCoordinate2D, settings: DriveSettings) async {
        didAttemptAutomaticRestore = false
        await restoreActiveTripIfNeeded(from: current, settings: settings)
    }

    func updateLockedRouteOptions(waypointID: String?, avoidTolls: Bool?, avoidHighways: Bool?) {
        routeLockStore.update { lock in
            if let waypointID, let index = lock.waypoints.firstIndex(where: { $0.id == waypointID }) {
                var options = lock.waypoints[index].optionsAfter ?? lock.defaultOptions
                if let avoidTolls { options.avoidTolls = avoidTolls }
                if let avoidHighways { options.avoidHighways = avoidHighways }
                lock.waypoints[index].optionsAfter = options
            } else {
                if let avoidTolls { lock.defaultOptions.avoidTolls = avoidTolls }
                if let avoidHighways { lock.defaultOptions.avoidHighways = avoidHighways }
            }
        }
        activeRouteLock = routeLockStore.activeLock
    }

    func replaceRouteLockForRemoteDestination(waypoints: [LockedWaypoint] = []) {
        guard let destination else { return }
        let coordinate = destination.placemark.coordinate
        let lock = ActiveRouteLock(
            id: UUID(), title: destination.name ?? destinationText,
            destinationName: destination.name ?? destinationText,
            destination: .init(latitude: coordinate.latitude, longitude: coordinate.longitude),
            waypoints: waypoints,
            defaultOptions: .init(avoidTolls: DriveSettings.shared.avoidTolls,
                                  avoidHighways: DriveSettings.shared.avoidHighways),
            corridorWidthMetres: 5_000, corridorPoints: nil, visitedWaypointIDs: [],
            status: .active, createdAt: Date(), updatedAt: Date())
        routeLockStore.save(lock)
        activeRouteLock = lock
    }

    var nextInstruction: String? {
        legs.first?.steps.enumerated().first(where: { index, step in
            index > 0 && !step.instructions.isEmpty &&
            !announcedStepKeys.contains("\(index):\(step.instructions)")
        })?.element.instructions
    }

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
            let lock = routeLockStore.activeLock
            let visited = Set(lock?.visitedWaypointIDs ?? [])
            let lockedWaypoints = lock?.waypoints.filter { $0.required && !visited.contains($0.id) } ?? []
            if viaStations.isEmpty && lockedWaypoints.isEmpty {
                let routes = try await computeRoutes(from: startItem, to: destination, settings: settings, alternates: true)
                alternatives = routes
                legs = routes.first.map { [$0] } ?? []
                // Request the opposite toll preference for an honest route-level
                // distance/time comparison. MapKit exposes no toll price; that
                // remains explicitly unknown until a verified provider responds.
                comparisonRoute = try? await computeRoutes(
                    from: startItem, to: destination, settings: settings,
                    alternates: false, avoidTollsOverride: !settings.avoidTolls
                ).first
            } else {
                // MapKit kennt keine mehrgliedrigen Routen als ein einziges Objekt.
                // Daher Teilstrecken sequentiell (Start→wp1→wp2→…→Ziel) berechnen.
                let waypoints: [MKMapItem] = lockedWaypoints.isEmpty
                    ? viaStations.map { MKMapItem(placemark: MKPlacemark(coordinate: $0.coordinate)) }
                    : lockedWaypoints.map { MKMapItem(placemark: MKPlacemark(coordinate: $0.coordinate.clLocationCoordinate)) }
                let allStops = [startItem] + waypoints + [destination]

                var newLegs: [MKRoute] = []
                for i in 0..<(allStops.count - 1) {
                    let from = allStops[i]
                    let to = allStops[i + 1]
                    let lockedOptions = i == 0 ? routeLockStore.activeLock?.defaultOptions
                        : lockedWaypoints[safe: i - 1]?.optionsAfter ?? routeLockStore.activeLock?.defaultOptions
                    guard let leg = try await computeRoutes(from: from, to: to, settings: settings,
                                                            alternates: false, lockedOptions: lockedOptions).first else {
                        throw DriveAPIError.invalidData
                    }
                    newLegs.append(leg)
                }
                legs = newLegs
                alternatives = []
                comparisonRoute = nil
            }
            announcedStepKeys = []
            offRouteStrikes = 0
            await loadStations(fuel: settings.fuel)
            await loadSpeedLimits()
            await loadTollCost(from: start)
            buildLongTripPlan(settings: settings)
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
        guard isNavigating, let route = legs.first else { return }
        markReachedWaypoints(at: location, settings: settings)
        checkSpeedLimit(at: location.coordinate, speedMps: location.speed)
        if settings.voiceGuidance { announceNextStep(near: location.coordinate, in: route) }
        checkForDeviation(from: location.coordinate, route: route, settings: settings)
    }

    private func markReachedWaypoints(at location: CLLocation, settings: DriveSettings) {
        guard let lock = routeLockStore.activeLock else { return }
        let visited = Set(lock.visitedWaypointIDs ?? [])
        guard let reached = lock.waypoints.first(where: {
            !visited.contains($0.id) && location.distance(from: CLLocation(
                latitude: $0.coordinate.latitude, longitude: $0.coordinate.longitude)) <= 250
        }) else { return }
        routeLockStore.update { current in
            var ids = current.visitedWaypointIDs ?? []
            if !ids.contains(reached.id) { ids.append(reached.id) }
            current.visitedWaypointIDs = ids
        }
        activeRouteLock = routeLockStore.activeLock
        Task { await calculate(from: location.coordinate, settings: settings) }
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

    private func computeRoutes(from source: MKMapItem, to destination: MKMapItem, settings: DriveSettings,
                               alternates: Bool, avoidTollsOverride: Bool? = nil,
                               lockedOptions: LockedRouteOptions? = nil) async throws -> [MKRoute] {
        let request = MKDirections.Request()
        request.source = source
        request.destination = destination
        request.transportType = .automobile
        request.requestsAlternateRoutes = alternates
        request.tollPreference = (avoidTollsOverride ?? lockedOptions?.avoidTolls ?? settings.avoidTolls) ? .avoid : .any
        request.highwayPreference = (lockedOptions?.avoidHighways ?? settings.avoidHighways) ? .avoid : .any
        let routes = try await MKDirections(request: request).calculate().routes
        guard let lock = routeLockStore.activeLock,
              let corridor = lock.corridorPoints, !corridor.isEmpty else { return routes }
        return routes.filter { routeInsideLockedCorridor($0, points: corridor,
                                                         width: lock.corridorWidthMetres) }
    }

    private func buildLongTripPlan(settings: DriveSettings) {
        guard !legs.isEmpty else { longTripPlan = nil; return }
        let mainDistance = totalDistance
        let mainTime = totalTravelTime
        let knownLimits = speedLimits.filter { $0.maxspeed != nil || $0.unlimited }
        let unlimitedFraction = knownLimits.isEmpty ? 0 : Double(knownLimits.filter(\.unlimited).count) / Double(knownLimits.count)
        let candidates = breakCandidates(totalDistance: mainDistance)
        var inputs = [RoutePlanningInput(
            id: settings.avoidTolls ? "toll-avoiding" : "standard",
            title: settings.avoidTolls ? "Maut vermeiden" : "Schnellste Route",
            distanceMetres: mainDistance,
            mapKitExpectedTravelTime: mainTime,
            unlimitedMotorwayFraction: unlimitedFraction,
            typicalUnlimitedSpeedKmh: 130,
            toll: settings.avoidTolls ? .unknown(reason: "Mautvermeidung gewählt; Restmaut wird nicht als null angenommen.") : researchedToll,
            breakCandidates: candidates
        )]
        if let comparisonRoute,
           abs(comparisonRoute.distance - mainDistance) > 100 || abs(comparisonRoute.expectedTravelTime - mainTime) > 60 {
            inputs.append(.init(
                id: settings.avoidTolls ? "standard" : "toll-avoiding",
                title: settings.avoidTolls ? "Schnellste Route" : "Maut vermeiden",
                distanceMetres: comparisonRoute.distance,
                mapKitExpectedTravelTime: comparisonRoute.expectedTravelTime,
                unlimitedMotorwayFraction: 0,
                typicalUnlimitedSpeedKmh: 130,
                toll: settings.avoidTolls ? researchedToll : .unknown(reason: "Mautvermeidung gewählt; Restmaut wird nicht als null angenommen."),
                breakCandidates: []
            ))
        }
        let profile = VehicleProfile(
            baseConsumptionLPer100km: settings.consumptionLPer100km,
            fuelPricePerLitre: settings.fuelPricePerLitre,
            tankCapacityLitres: settings.tankCapacityL
        )
        let scenarios = [SpeedScenario.target(settings.targetSpeedKmh)] + (settings.targetSpeedKmh == 200 ? [] : [.target(200)])
        longTripPlan = RouteComparison(fuelModel: .init(), breakPlanner: .init())
            .compare(routes: inputs, scenarios: scenarios, vehicle: profile)
    }

    private func loadTollCost(from start: CLLocationCoordinate2D) async {
        guard let destination else { return }
        let origin = String(format: "%.4f, %.4f", start.latitude, start.longitude)
        let destinationName = destination.placemark.title ?? destination.name ?? destinationText
        do {
            researchedToll = try await DriveAPI.tollCost(origin: origin, destination: destinationName)
        } catch {
            researchedToll = .unknown(reason: "SearXNG-Mautrecherche nicht verfügbar: \(error.localizedDescription)")
        }
    }

    /// Recomputes scenario numbers from the already loaded route when vehicle
    /// or target-speed settings change; no network request is required.
    func refreshLongTripPlan(settings: DriveSettings) {
        buildLongTripPlan(settings: settings)
    }

    private func breakCandidates(totalDistance: Double) -> [BreakCandidate] {
        let routeCoordinates = legs.flatMap { sample($0.polyline, maximum: 160) }
        guard routeCoordinates.count > 1 else { return [] }
        return stations.compactMap { station in
            let location = CLLocation(latitude: station.lat, longitude: station.lon)
            guard let match = routeCoordinates.enumerated().min(by: {
                location.distance(from: CLLocation(latitude: $0.element.latitude, longitude: $0.element.longitude)) <
                location.distance(from: CLLocation(latitude: $1.element.latitude, longitude: $1.element.longitude))
            }) else { return nil }
            let detour = location.distance(from: CLLocation(latitude: match.element.latitude, longitude: match.element.longitude))
            return BreakCandidate(
                id: station.id, name: station.brand.isEmpty ? station.name : station.brand,
                coordinate: station.coordinate,
                progress: Double(match.offset) / Double(routeCoordinates.count - 1),
                detourMetres: detour * 2, isOpen: station.open != false
            )
        }
    }

    func loadStations(fuel: FuelKind) async {
        guard !legs.isEmpty else { return }
        let generation = UUID()
        stationLoadGeneration = generation
        // A handful of evenly distributed requests is sufficient. The old
        // 25-km radius at ten route points returned hundreds of duplicates.
        let points = evenlySpaced(legs.flatMap { sample($0.polyline, maximum: 80) }, maximum: 6)
        var unique: [String: FuelStation] = [:]
        await withTaskGroup(of: [FuelStation].self) { group in
            for point in points { group.addTask { (try? await DriveAPI.stations(near: point, fuel: fuel, radiusKm: 8)) ?? [] } }
            for await batch in group { for station in batch { unique[station.id] = station } }
        }
        guard generation == stationLoadGeneration else { return }
        let routeCoordinates = legs.flatMap { sample($0.polyline, maximum: 160) }
        let routePoints = routeCoordinates.map { CLLocation(latitude: $0.latitude, longitude: $0.longitude) }
        let nearRoute = unique.values.compactMap { station -> (FuelStation, Int)? in
            let point = CLLocation(latitude: station.lat, longitude: station.lon)
            guard let match = routePoints.enumerated().min(by: { $0.element.distance(from: point) < $1.element.distance(from: point) }),
                  match.element.distance(from: point) < 4_000 else { return nil }
            return (station, match.offset)
        }
        // Keep at most one strong candidate per route section. This gives the
        // break planner geographic coverage without flooding MapKit with pins.
        let bucketCount = min(12, max(1, routeCoordinates.count))
        let grouped = Dictionary(grouping: nearRoute) { item in
            min(bucketCount - 1, item.1 * bucketCount / max(1, routeCoordinates.count))
        }
        stations = grouped.keys.sorted().compactMap { bucket in
            grouped[bucket]?.min {
                if $0.0.open != $1.0.open { return $0.0.open != false }
                return $0.0.price == $1.0.price ? $0.0.distanceKm < $1.0.distanceKm : $0.0.price < $1.0.price
            }?.0
        }
    }

    /// Fügt eine Tankstelle als Zwischenstopp ein (oder entfernt sie erneut,
    /// wenn sie bereits als Zwischenstopp gesetzt ist) und berechnet die
    /// Route neu.
    func toggleWaypoint(_ station: FuelStation, from start: CLLocationCoordinate2D, settings: DriveSettings) async {
        if let index = viaStations.firstIndex(where: { $0.id == station.id }) {
            viaStations.remove(at: index)
        } else {
            viaStations.append(station)
        }
        await calculate(from: start, settings: settings)
    }

    func addPlannedBreak(_ plannedBreak: PlannedBreak, from start: CLLocationCoordinate2D, settings: DriveSettings) async {
        guard let candidate = plannedBreak.candidate,
              let station = stations.first(where: { $0.id == candidate.id }),
              !viaStations.contains(where: { $0.id == station.id }) else { return }
        viaStations.append(station)
        let progressByID = Dictionary(uniqueKeysWithValues: breakCandidates(totalDistance: totalDistance).map { ($0.id, $0.progress) })
        viaStations.sort { lhs, rhs in
            (progressByID[lhs.id] ?? 1) < (progressByID[rhs.id] ?? 1)
        }
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

    private func evenlySpaced(_ points: [CLLocationCoordinate2D], maximum: Int) -> [CLLocationCoordinate2D] {
        guard points.count > maximum, maximum > 1 else { return points }
        return (0..<maximum).map { index in
            points[index * (points.count - 1) / (maximum - 1)]
        }
    }

    private func routeInsideLockedCorridor(_ route: MKRoute, points: [DriveCoordinate], width: Double) -> Bool {
        let anchors = points.map { CLLocation(latitude: $0.latitude, longitude: $0.longitude) }
        let routePoints = sample(route.polyline, maximum: 100)
        guard !anchors.isEmpty, !routePoints.isEmpty else { return false }
        // Einzelne Anschlussstellen duerfen den Korridor leicht verlassen;
        // mindestens 90 % der Neuberechnung muessen innerhalb bleiben.
        let inside = routePoints.filter { coordinate in
            let location = CLLocation(latitude: coordinate.latitude, longitude: coordinate.longitude)
            return anchors.contains { $0.distance(from: location) <= width }
        }.count
        return Double(inside) / Double(routePoints.count) >= 0.9
    }
}

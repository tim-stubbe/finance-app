import Foundation
import CoreLocation

struct VehicleProfile: Codable, Equatable {
    var name: String = "Mein Fahrzeug"
    var baseConsumptionLPer100km: Double = 6.5
    var referenceSpeedKmh: Double = 100
    var fuelPricePerLitre: Double = 1.75
    var tankCapacityLitres: Double = 50
    var usableTankFraction: Double = 0.85
}

struct SpeedScenario: Codable, Identifiable, Equatable {
    let id: String
    var name: String
    var targetSpeedKmh: Double

    static func target(_ speed: Double) -> Self {
        .init(id: "target-\(Int(speed))", name: "Zieltempo \(Int(speed)) km/h", targetSpeedKmh: speed)
    }
}

enum TollCost: Codable, Equatable {
    case known(amount: Decimal, currency: String, source: String)
    case noToll(source: String)
    case unknown(reason: String)

    var amount: Decimal? {
        if case .known(let amount, _, _) = self { return amount }
        if case .noToll = self { return 0 }
        return nil
    }
}

struct TollRouteDescriptor: Sendable {
    let routeID: String
    let distanceMetres: Double
    let countries: [String]
}

protocol TollProvider: Sendable {
    var name: String { get }
    func tollCost(for route: TollRouteDescriptor, vehicle: VehicleProfile) async throws -> TollCost
}

/// Safe default until a contracted/provider-backed toll endpoint is configured.
/// An absent price must remain absent; it is never estimated from distance.
struct UnknownTollProvider: TollProvider {
    let name = "Keine verifizierte Mautquelle"
    func tollCost(for route: TollRouteDescriptor, vehicle: VehicleProfile) async throws -> TollCost {
        .unknown(reason: "Für diese Route liegen keine belastbaren Providerdaten vor.")
    }
}

struct FuelEstimate: Codable, Equatable {
    let litres: Double
    let cost: Double
    let averageConsumptionLPer100km: Double
}

struct FuelModel {
    /// Aerodynamic drag rises strongly with speed. This bounded curve is a
    /// transparent planning estimate, not a replacement for measured telemetry.
    func estimate(distanceMetres: Double, effectiveSpeedKmh: Double, profile: VehicleProfile) -> FuelEstimate {
        let reference = max(30, profile.referenceSpeedKmh)
        let speedRatio = max(0.3, effectiveSpeedKmh / reference)
        let multiplier = min(3.2, max(0.65, 0.55 + 0.45 * speedRatio * speedRatio))
        let average = profile.baseConsumptionLPer100km * multiplier
        let litres = max(0, distanceMetres / 100_000 * average)
        return .init(litres: litres, cost: litres * max(0, profile.fuelPricePerLitre), averageConsumptionLPer100km: average)
    }
}

struct BreakCandidate: Identifiable, Equatable {
    let id: String
    let name: String
    let coordinate: CLLocationCoordinate2D
    let progress: Double
    let detourMetres: Double
    let isOpen: Bool

    static func == (lhs: Self, rhs: Self) -> Bool { lhs.id == rhs.id }
}

struct PlannedBreak: Identifiable, Equatable {
    let id: String
    let candidate: BreakCandidate?
    let afterDriving: TimeInterval
    let duration: TimeInterval
    let routeProgress: Double
    let explanation: String
}

struct BreakPlanner {
    var maximumContinuousDriving: TimeInterval = 2 * 60 * 60
    var defaultBreakDuration: TimeInterval = 20 * 60

    func plan(drivingTime: TimeInterval, candidates: [BreakCandidate]) -> [PlannedBreak] {
        guard drivingTime > maximumContinuousDriving else { return [] }
        let count = max(1, Int(ceil(drivingTime / maximumContinuousDriving)) - 1)
        var remaining = candidates.filter { $0.isOpen }
        return (1...count).map { index in
            let idealProgress = Double(index) / Double(count + 1)
            let best = remaining.min {
                score($0, idealProgress: idealProgress) < score($1, idealProgress: idealProgress)
            }
            if let best { remaining.removeAll { $0.id == best.id } }
            let progress = best?.progress ?? idealProgress
            let detour = best.map { " · \(Int($0.detourMetres / 100) * 100) m Umweg" } ?? ""
            return PlannedBreak(
                id: "break-\(index)", candidate: best,
                afterDriving: drivingTime * progress, duration: defaultBreakDuration,
                routeProgress: progress,
                explanation: best == nil ? "Pause nahe dem optimalen Streckenpunkt; Ort noch nicht verifiziert." : "Offener Halt nahe dem optimalen Pausenfenster\(detour)."
            )
        }
    }

    private func score(_ candidate: BreakCandidate, idealProgress: Double) -> Double {
        abs(candidate.progress - idealProgress) * 100 + min(30, candidate.detourMetres / 1_000 * 4)
    }
}

struct RouteComparisonDelta: Equatable {
    let timeDifference: TimeInterval
    let distanceDifferenceMetres: Double
    let fuelDifferenceLitres: Double
    let fuelCostDifference: Double
    let tollSavings: Decimal?

    init(from baseline: RouteScenarioResult, to alternative: RouteScenarioResult) {
        timeDifference = alternative.totalTime - baseline.totalTime
        distanceDifferenceMetres = alternative.distanceMetres - baseline.distanceMetres
        fuelDifferenceLitres = alternative.fuel.litres - baseline.fuel.litres
        fuelCostDifference = alternative.fuel.cost - baseline.fuel.cost
        if let baselineToll = baseline.toll.amount, let alternativeToll = alternative.toll.amount {
            tollSavings = baselineToll - alternativeToll
        } else {
            tollSavings = nil
        }
    }
}

struct RoutePlanningInput {
    let id: String
    let title: String
    let distanceMetres: Double
    let mapKitExpectedTravelTime: TimeInterval
    let unlimitedMotorwayFraction: Double
    let typicalUnlimitedSpeedKmh: Double
    let toll: TollCost
    let breakCandidates: [BreakCandidate]
}

struct RouteScenarioResult: Identifiable, Equatable {
    let id: String
    let routeTitle: String
    let scenario: SpeedScenario
    let distanceMetres: Double
    let drivingTime: TimeInterval
    let totalTime: TimeInterval
    let fuel: FuelEstimate
    let toll: TollCost
    let breaks: [PlannedBreak]
    let unlimitedFraction: Double
}

struct LongTripPlan: Equatable {
    let createdAt: Date
    let results: [RouteScenarioResult]
    let note: String
}

struct RouteComparison {
    let fuelModel: FuelModel
    let breakPlanner: BreakPlanner

    func compare(routes: [RoutePlanningInput], scenarios: [SpeedScenario], vehicle: VehicleProfile, now: Date = Date()) -> LongTripPlan {
        let results = routes.flatMap { route in
            scenarios.map { scenario in
                result(route: route, scenario: scenario, vehicle: vehicle)
            }
        }
        return LongTripPlan(
            createdAt: now,
            results: results,
            note: "ETA basiert auf MapKit-Verkehrsdaten. Das Zieltempo verändert nur den geeigneten Anteil ohne bekanntes Limit; Pausen kommen anschließend hinzu."
        )
    }

    private func result(route: RoutePlanningInput, scenario: SpeedScenario, vehicle: VehicleProfile) -> RouteScenarioResult {
        let fraction = min(1, max(0, route.unlimitedMotorwayFraction))
        let baseline = max(1, route.typicalUnlimitedSpeedKmh)
        let target = min(max(80, scenario.targetSpeedKmh), 220)
        let baselineUnlimitedTime = route.mapKitExpectedTravelTime * fraction
        let adjustedUnlimitedTime = baselineUnlimitedTime * baseline / target
        // Preserve MapKit's limited/urban/traffic component instead of assuming
        // the selected target speed applies to the whole route.
        let drivingTime = max(route.mapKitExpectedTravelTime * (1 - fraction), route.mapKitExpectedTravelTime - baselineUnlimitedTime) + adjustedUnlimitedTime
        let averageSpeed = route.distanceMetres / max(1, drivingTime) * 3.6
        let fuel = fuelModel.estimate(distanceMetres: route.distanceMetres, effectiveSpeedKmh: averageSpeed, profile: vehicle)
        let breaks = breakPlanner.plan(drivingTime: drivingTime, candidates: route.breakCandidates)
        return .init(
            id: "\(route.id)-\(scenario.id)", routeTitle: route.title, scenario: scenario,
            distanceMetres: route.distanceMetres, drivingTime: drivingTime,
            totalTime: drivingTime + breaks.reduce(0) { $0 + $1.duration }, fuel: fuel,
            toll: route.toll, breaks: breaks, unlimitedFraction: fraction
        )
    }
}

/// Boundary for a later DriveLog/OBD integration. Kies Drive does not own or
/// persist telemetry; callers may provide aggregated observations later.
protocol DriveTelemetryProviding: Sendable {
    func observedConsumptionLPer100km() async -> Double?
    func observedCruisingSpeedKmh() async -> Double?
}

struct NoTelemetryProvider: DriveTelemetryProviding {
    func observedConsumptionLPer100km() async -> Double? { nil }
    func observedCruisingSpeedKmh() async -> Double? { nil }
}

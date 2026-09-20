import XCTest

final class LongTripPlanningTests: XCTestCase {
    func testHigherTargetSpeedOnlyChangesUnlimitedShareAndUsesMoreFuel() {
        let route = RoutePlanningInput(
            id: "holiday", title: "Route", distanceMetres: 600_000,
            mapKitExpectedTravelTime: 6 * 3600, unlimitedMotorwayFraction: 0.5,
            typicalUnlimitedSpeedKmh: 130, toll: .unknown(reason: "test"), breakCandidates: []
        )
        let plan = RouteComparison(fuelModel: .init(), breakPlanner: .init())
            .compare(routes: [route], scenarios: [.target(150), .target(200)], vehicle: .init())

        XCTAssertEqual(plan.results.count, 2)
        XCTAssertLessThan(plan.results[1].drivingTime, plan.results[0].drivingTime)
        XCTAssertGreaterThan(plan.results[1].fuel.litres, plan.results[0].fuel.litres)
        XCTAssertGreaterThan(plan.results[1].drivingTime, 3 * 3600, "Limited/traffic time must be preserved")
    }

    func testBreakPlannerPrefersOpenLowDetourStopNearWindow() {
        let candidates = [
            BreakCandidate(id: "closed", name: "Closed", coordinate: .init(latitude: 0, longitude: 0), progress: 0.34, detourMetres: 50, isOpen: false),
            BreakCandidate(id: "far", name: "Far", coordinate: .init(latitude: 0, longitude: 0), progress: 0.34, detourMetres: 8_000, isOpen: true),
            BreakCandidate(id: "best", name: "Best", coordinate: .init(latitude: 0, longitude: 0), progress: 0.38, detourMetres: 300, isOpen: true),
        ]
        let breaks = BreakPlanner().plan(drivingTime: 5 * 3600, candidates: candidates)

        XCTAssertEqual(breaks.count, 2)
        XCTAssertEqual(breaks.first?.candidate?.id, "best")
    }

    func testUnknownTollNeverTurnsIntoInventedZero() async throws {
        let cost = try await UnknownTollProvider().tollCost(
            for: .init(routeID: "route", distanceMetres: 100_000, countries: ["DE"]),
            vehicle: .init()
        )
        XCTAssertNil(cost.amount)
        guard case .unknown = cost else { return XCTFail("Expected unknown toll cost") }
    }

    func testShortTripDoesNotAddBreak() {
        XCTAssertTrue(BreakPlanner().plan(drivingTime: 90 * 60, candidates: []).isEmpty)
    }
}

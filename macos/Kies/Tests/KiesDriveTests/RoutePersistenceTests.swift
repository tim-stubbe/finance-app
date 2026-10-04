import XCTest

@MainActor
final class RoutePersistenceTests: XCTestCase {
    func testActiveTripSurvivesStoreRecreationWithSegmentRules() throws {
        let suite = "RoutePersistenceTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let first = RouteLockStore(defaults: defaults)
        let lock = ActiveRouteLock(
            id: UUID(), title: "Kroatien", destinationName: "Split",
            destination: .init(latitude: 43.508, longitude: 16.44),
            waypoints: [.init(
                id: "slovenia", name: "Slowenien", coordinate: .init(latitude: 46.05, longitude: 14.5),
                required: true, optionsAfter: .init(avoidTolls: false, avoidHighways: true))],
            defaultOptions: .init(avoidTolls: false, avoidHighways: false),
            corridorWidthMetres: 5_000, corridorPoints: [.init(latitude: 46.1, longitude: 14.6)],
            visitedWaypointIDs: [],
            status: .active, createdAt: Date(), updatedAt: Date())
        first.save(lock)

        let restored = RouteLockStore(defaults: defaults).activeLock
        XCTAssertEqual(restored?.title, "Kroatien")
        XCTAssertEqual(restored?.waypoints.first?.optionsAfter?.avoidHighways, true)
        XCTAssertEqual(restored?.waypoints.first?.required, true)
        XCTAssertEqual(restored?.corridorPoints?.count, 1)
    }

    func testFinishedTripIsNotRestored() throws {
        let suite = "RoutePersistenceTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = RouteLockStore(defaults: defaults)
        store.save(.init(
            id: UUID(), title: "Test", destinationName: "Ziel",
            destination: .init(latitude: 1, longitude: 2), waypoints: [],
            defaultOptions: .init(avoidTolls: false, avoidHighways: false),
            corridorWidthMetres: 1_000, corridorPoints: nil,
            visitedWaypointIDs: [],
            status: .active, createdAt: Date(), updatedAt: Date()))
        store.finish()
        XCTAssertNil(RouteLockStore(defaults: defaults).activeLock)
    }
}

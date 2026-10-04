import Foundation
import CoreLocation
import MapKit

struct DriveRemoteState: Encodable {
    struct Position: Encodable { let latitude: Double; let longitude: Double; let accuracyMetres: Double }
    struct Route: Encodable { let destination: String; let distanceMetres: Double; let travelTimeSeconds: Double }
    struct Maneuver: Encodable { let instruction: String }

    let location: Position?
    let headingDegrees: Double?
    let speedKmh: Double?
    let activeRoute: Route?
    let nextManeuver: Maneuver?
    let routeLock: ActiveRouteLock?
    let navigationActive: Bool
    let recordedAt: Date
}

struct DriveRemoteCommand: Decodable {
    let id: Int
    let command: String
    let arguments: [String: JSONValue]
}

struct DriveRemoteCommandEnvelope: Decodable { let commands: [DriveRemoteCommand] }

enum JSONValue: Codable {
    case string(String), number(Double), bool(Bool), array([JSONValue]), object([String: JSONValue]), null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([JSONValue].self) { self = .array(v) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let v): try c.encode(v); case .number(let v): try c.encode(v)
        case .bool(let v): try c.encode(v); case .array(let v): try c.encode(v)
        case .object(let v): try c.encode(v); case .null: try c.encodeNil()
        }
    }
    var string: String? { if case .string(let value) = self { value } else { nil } }
    var number: Double? { if case .number(let value) = self { value } else { nil } }
    var bool: Bool? { if case .bool(let value) = self { value } else { nil } }
    var array: [JSONValue]? { if case .array(let value) = self { value } else { nil } }
    var object: [String: JSONValue]? { if case .object(let value) = self { value } else { nil } }
}

@MainActor
final class DriveRemoteBridge {
    static let shared = DriveRemoteBridge()
    private var lastSync = Date.distantPast
    private var handledCommandIDs: Set<Int> = []
    private var syncing = false

    func sync(location: CLLocation) async {
        guard DriveSettings.shared.isReady, !syncing,
              Date().timeIntervalSince(lastSync) >= 5 else { return }
        syncing = true
        defer { syncing = false; lastSync = Date() }
        let planner = RoutePlanner.shared
        let state = DriveRemoteState(
            location: .init(latitude: location.coordinate.latitude,
                            longitude: location.coordinate.longitude,
                            accuracyMetres: location.horizontalAccuracy),
            headingDegrees: location.course >= 0 ? location.course : nil,
            speedKmh: location.speed >= 0 ? location.speed * 3.6 : nil,
            activeRoute: planner.legs.isEmpty ? nil : .init(
                destination: planner.destination?.name ?? planner.destinationText,
                distanceMetres: planner.totalDistance, travelTimeSeconds: planner.totalTravelTime),
            nextManeuver: planner.nextInstruction.map { .init(instruction: $0) },
            routeLock: planner.activeRouteLock,
            navigationActive: planner.isNavigating, recordedAt: Date()
        )
        do {
            try await DriveAPI.publishRemoteState(state)
            for command in try await DriveAPI.remoteCommands() where !handledCommandIDs.contains(command.id) {
                handledCommandIDs.insert(command.id)
                do {
                    try await execute(command, at: location.coordinate)
                    try await DriveAPI.completeRemoteCommand(command.id, ok: true, message: "In Kies Drive ausgeführt")
                } catch {
                    try? await DriveAPI.completeRemoteCommand(command.id, ok: false, message: error.localizedDescription)
                }
            }
        } catch {
            // Navigation bleibt absichtlich unbeeinflusst, wenn die Remote-
            // Schnittstelle oder der TrueNAS nicht erreichbar ist.
        }
    }

    private func execute(_ command: DriveRemoteCommand, at current: CLLocationCoordinate2D) async throws {
        let planner = RoutePlanner.shared
        let settings = DriveSettings.shared
        switch command.command {
        case "restore_route":
            await planner.restoreActiveTrip(from: current, settings: settings)
        case "set_route_options":
            if let value = command.arguments["avoid_tolls"]?.bool { settings.avoidTolls = value }
            if let value = command.arguments["avoid_highways"]?.bool { settings.avoidHighways = value }
            planner.updateLockedRouteOptions(
                waypointID: command.arguments["waypoint_id"]?.string,
                avoidTolls: command.arguments["avoid_tolls"]?.bool,
                avoidHighways: command.arguments["avoid_highways"]?.bool)
            await planner.calculate(from: current, settings: settings)
        case "set_destination":
            if let lat = command.arguments["latitude"]?.number,
               let lon = command.arguments["longitude"]?.number {
                let item = MKMapItem(placemark: MKPlacemark(coordinate: .init(latitude: lat, longitude: lon)))
                item.name = command.arguments["query"]?.string ?? "Remote-Ziel"
                planner.destination = item
                planner.destinationText = item.name ?? "Remote-Ziel"
            } else if let query = command.arguments["query"]?.string {
                planner.destinationText = query
                await planner.searchDestination(near: current)
                guard let item = planner.suggestions.first else { throw DriveRemoteError.destinationNotFound }
                planner.destination = item
                planner.destinationText = item.name ?? query
            } else { throw DriveRemoteError.destinationNotFound }
            let waypoints = command.arguments["required_waypoints"]?.array?.compactMap { value -> LockedWaypoint? in
                guard let item = value.object,
                      let latitude = item["latitude"]?.number,
                      let longitude = item["longitude"]?.number else { return nil }
                let segment = item["options_after"]?.object
                let options = segment.map {
                    LockedRouteOptions(avoidTolls: $0["avoid_tolls"]?.bool ?? settings.avoidTolls,
                                       avoidHighways: $0["avoid_highways"]?.bool ?? settings.avoidHighways)
                }
                return LockedWaypoint(
                    id: item["id"]?.string ?? UUID().uuidString,
                    name: item["name"]?.string ?? "Pflicht-Zwischenpunkt",
                    coordinate: .init(latitude: latitude, longitude: longitude),
                    required: true, optionsAfter: options)
            } ?? []
            planner.replaceRouteLockForRemoteDestination(waypoints: waypoints)
            await planner.calculate(from: current, settings: settings)
            planner.startNavigation()
        default:
            throw DriveRemoteError.unknownCommand
        }
    }
}

enum DriveRemoteError: LocalizedError {
    case destinationNotFound, unknownCommand
    var errorDescription: String? {
        switch self {
        case .destinationNotFound: "Ziel konnte nicht gefunden werden."
        case .unknownCommand: "Unbekannter Remote-Befehl."
        }
    }
}

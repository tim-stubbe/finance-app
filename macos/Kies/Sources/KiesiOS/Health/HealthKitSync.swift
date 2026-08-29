import Foundation
import HealthKit
import KiesCore

/// Ein Tageswert einer Gesundheits-Kennzahl (fuer Diagramme + Upload).
public struct HealthPoint: Identifiable {
    public let id = UUID()
    public let day: Date
    public let value: Double
}

/// Die vier Kennzahlen als Tagesreihen - fuer HealthView.
public struct HealthSeries {
    public var steps: [HealthPoint] = []
    public var pulse: [HealthPoint] = []
    public var weight: [HealthPoint] = []
    public var sleep: [HealthPoint] = []

    public var isEmpty: Bool { steps.isEmpty && pulse.isEmpty && weight.isEmpty && sleep.isEmpty }
}

/// Liest Schritte, Ruhepuls, Gewicht und Schlaf aus Apple Health - schickt sie
/// tageweise an Kies (`POST /api/sync/health`, Auth per X-Sync-Secret) UND
/// liefert sie fuer die lokale Anzeige (HealthView). Bewusst schlank: eine
/// Aggregation pro Tag und Kennzahl, kein HKObserverQuery/Background-Delivery.
///
/// HealthKit ist iOS-only, deshalb liegt diese Datei im KiesiOS-Target.
@MainActor
public final class HealthKitSync: ObservableObject {
    public static let shared = HealthKitSync()

    private static let enabledKey = "kies.healthSyncEnabled"
    private static let lastSyncKey = "kies.healthLastSync"

    private let store = HKHealthStore()

    @Published public var enabled: Bool {
        didSet { UserDefaults.standard.set(enabled, forKey: Self.enabledKey) }
    }
    @Published public var isSyncing = false
    @Published public var lastError: String?
    @Published public private(set) var lastSync: Date?

    public var isAvailable: Bool { HKHealthStore.isHealthDataAvailable() }

    private init() {
        enabled = UserDefaults.standard.bool(forKey: Self.enabledKey)
        let ts = UserDefaults.standard.double(forKey: Self.lastSyncKey)
        lastSync = ts > 0 ? Date(timeIntervalSince1970: ts) : nil
    }

    private var stepType: HKQuantityType { HKQuantityType(.stepCount) }
    private var restingHRType: HKQuantityType { HKQuantityType(.restingHeartRate) }
    private var bodyMassType: HKQuantityType { HKQuantityType(.bodyMass) }
    private var sleepType: HKCategoryType { HKCategoryType(.sleepAnalysis) }
    private var bpmUnit: HKUnit { HKUnit.count().unitDivided(by: .minute()) }

    private var readTypes: Set<HKObjectType> { [stepType, restingHRType, bodyMassType, sleepType] }

    /// Fragt die Lese-Berechtigung an. HealthKit verraet aus Datenschutz-
    /// gruenden NICHT, ob der Nutzer zugestimmt hat - `true` heisst nur, dass
    /// der Dialog durchlief.
    @discardableResult
    public func requestAuthorization() async -> Bool {
        guard isAvailable else { return false }
        do {
            try await store.requestAuthorization(toShare: [], read: readTypes)
            return true
        } catch {
            lastError = error.localizedDescription
            return false
        }
    }

    /// `fullHistory` (Voll-Import per Knopf / beim Aktivieren) holt ~3 Jahre,
    /// der automatische Lauf beim App-Start nur die letzten Wochen (schnell,
    /// schliesst Luecken). Backend upsert't je (Typ, Tag), also idempotent.
    public func syncNow(fullHistory: Bool = false) async {
        let days = fullHistory ? 1200 : 60
        guard enabled, isAvailable else { return }
        let pairing = PairingStore.shared
        guard pairing.isPaired else { return }
        if isSyncing { return }
        isSyncing = true
        lastError = nil
        defer { isSyncing = false }

        do {
            await requestAuthorization()
            let s = try await series(days: days)
            let payload =
                s.steps.map  { row("schritte", $0) } +
                s.pulse.map  { row("puls", $0) } +
                s.weight.map { row("gewicht", $0) } +
                s.sleep.map  { row("schlaf", $0) }
            if payload.isEmpty { markSynced(); return }
            try await upload(metrics: payload, pairing: pairing)
            markSynced()
        } catch {
            lastError = (error as NSError).localizedDescription
        }
    }

    /// Tagesreihen der vier Kennzahlen fuer die letzten `days` Tage - direkt
    /// aus HealthKit, ohne Server (HealthView zeigt das offline an).
    public func series(days: Int) async throws -> HealthSeries {
        guard isAvailable else { return HealthSeries() }
        await requestAuthorization()
        var out = HealthSeries()
        out.steps  = try await daily(stepType, unit: .count(), options: .cumulativeSum, days: days)
        out.pulse  = try await daily(restingHRType, unit: bpmUnit, options: .discreteAverage, days: days)
        out.weight = try await daily(bodyMassType, unit: .gramUnit(with: .kilo), options: .discreteAverage, days: days)
        out.sleep  = try await dailySleepHours(days: days)
        return out
    }

    // MARK: - Aggregationen

    private func row(_ type: String, _ p: HealthPoint) -> [String: Any] {
        let c = Calendar.current.dateComponents([.year, .month, .day], from: p.day)
        return [
            "metric_type": type,
            "date": String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0),
            "value": p.value,
        ]
    }

    private func window(days: Int) -> Date {
        let cal = Calendar.current
        return cal.date(byAdding: .day, value: -max(1, days), to: cal.startOfDay(for: Date()))
            ?? cal.startOfDay(for: Date())
    }

    private func daily(_ type: HKQuantityType, unit: HKUnit, options: HKStatisticsOptions, days: Int) async throws -> [HealthPoint] {
        let start = window(days: days)
        let predicate = HKQuery.predicateForSamples(withStart: start, end: Date(), options: .strictStartDate)
        let coll: HKStatisticsCollection = try await withCheckedThrowingContinuation { cont in
            let q = HKStatisticsCollectionQuery(
                quantityType: type, quantitySamplePredicate: predicate,
                options: options, anchorDate: start,
                intervalComponents: DateComponents(day: 1)
            )
            q.initialResultsHandler = { _, result, error in
                if let result { cont.resume(returning: result) }
                else { cont.resume(throwing: error ?? HKError(.errorDatabaseInaccessible)) }
            }
            store.execute(q)
        }
        var out: [HealthPoint] = []
        coll.enumerateStatistics(from: start, to: Date()) { stat, _ in
            let q = options == .cumulativeSum ? stat.sumQuantity() : stat.averageQuantity()
            guard let q else { return }
            let v = q.doubleValue(for: unit)
            if v > 0 { out.append(HealthPoint(day: stat.startDate, value: v)) }
        }
        return out
    }

    private func dailySleepHours(days: Int) async throws -> [HealthPoint] {
        let start = window(days: days)
        let predicate = HKQuery.predicateForSamples(withStart: start, end: Date(), options: .strictStartDate)
        let asleep: Set<Int> = [
            HKCategoryValueSleepAnalysis.asleepUnspecified.rawValue,
            HKCategoryValueSleepAnalysis.asleepCore.rawValue,
            HKCategoryValueSleepAnalysis.asleepDeep.rawValue,
            HKCategoryValueSleepAnalysis.asleepREM.rawValue,
        ]
        let samples: [HKCategorySample] = try await withCheckedThrowingContinuation { cont in
            let q = HKSampleQuery(sampleType: sleepType, predicate: predicate, limit: HKObjectQueryNoLimit, sortDescriptors: nil) { _, res, error in
                if let res = res as? [HKCategorySample] { cont.resume(returning: res) }
                else { cont.resume(throwing: error ?? HKError(.errorDatabaseInaccessible)) }
            }
            store.execute(q)
        }
        let cal = Calendar.current
        var hoursByDay: [Date: Double] = [:]
        for s in samples where asleep.contains(s.value) {
            let key = cal.startOfDay(for: s.endDate)  // dem Aufwach-Tag zuordnen
            hoursByDay[key, default: 0] += s.endDate.timeIntervalSince(s.startDate) / 3600
        }
        return hoursByDay
            .filter { $0.value > 0 }
            .map { HealthPoint(day: $0.key, value: $0.value) }
            .sorted { $0.day < $1.day }
    }

    // MARK: - Upload

    private func upload(metrics: [[String: Any]], pairing: PairingStore) async throws {
        var base = pairing.baseURLString
        if base.hasSuffix("/") { base.removeLast() }
        guard let url = URL(string: base + "/api/sync/health") else {
            throw NSError(domain: "Kies", code: 1, userInfo: [NSLocalizedDescriptionKey: "Ungültige Serveradresse."])
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 30
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue(pairing.secret, forHTTPHeaderField: "X-Sync-Secret")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["metrics": metrics])

        let (data, resp) = try await KiesHTTP.session.data(for: req)
        guard let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let code = (resp as? HTTPURLResponse)?.statusCode ?? -1
            let body = String(data: data, encoding: .utf8) ?? ""
            throw NSError(domain: "Kies", code: code,
                          userInfo: [NSLocalizedDescriptionKey: "Server \(code): \(body.prefix(200))"])
        }
    }

    private func markSynced() {
        let now = Date()
        lastSync = now
        UserDefaults.standard.set(now.timeIntervalSince1970, forKey: Self.lastSyncKey)
    }
}

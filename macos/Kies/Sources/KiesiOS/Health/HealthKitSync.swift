import Foundation
import HealthKit
import KiesCore

/// Liest Schritte, Ruhepuls, Gewicht und Schlaf aus Apple Health und schickt
/// sie tageweise an Kies (`POST /api/sync/health`, Auth per X-Sync-Secret wie
/// pull/push). Bewusst schlank: eine Aggregation pro Tag und Kennzahl, kein
/// HKObserverQuery/Background-Delivery in v1 - Sync laeuft beim App-Start
/// (nach dem normalen Datensync) und auf Knopfdruck in den Einstellungen.
///
/// HealthKit ist iOS-only, deshalb liegt diese Datei im KiesiOS-Target und
/// nicht im plattformneutralen KiesCore.
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

    // Die vier gelesenen HealthKit-Typen -> Kies-metric_type.
    private var stepType: HKQuantityType { HKQuantityType(.stepCount) }
    private var restingHRType: HKQuantityType { HKQuantityType(.restingHeartRate) }
    private var bodyMassType: HKQuantityType { HKQuantityType(.bodyMass) }
    private var sleepType: HKCategoryType { HKCategoryType(.sleepAnalysis) }

    private var readTypes: Set<HKObjectType> {
        [stepType, restingHRType, bodyMassType, sleepType]
    }

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

    public func syncNow(days: Int = 30) async {
        guard enabled, isAvailable else { return }
        let pairing = PairingStore.shared
        guard pairing.isPaired else { return }
        if isSyncing { return }
        isSyncing = true
        lastError = nil
        defer { isSyncing = false }

        do {
            await requestAuthorization()
            var payload: [[String: Any]] = []
            payload += try await dailySum(stepType, unit: .count(), type: "schritte", days: days)
            payload += try await dailyAverage(restingHRType, unit: HKUnit.count().unitDivided(by: .minute()), type: "puls", days: days)
            payload += try await dailyAverage(bodyMassType, unit: .gramUnit(with: .kilo), type: "gewicht", days: days)
            payload += try await dailySleepHours(days: days)

            if payload.isEmpty {
                markSynced()
                return
            }
            try await upload(metrics: payload, pairing: pairing)
            markSynced()
        } catch {
            lastError = (error as NSError).localizedDescription
        }
    }

    // MARK: - Aggregationen

    private func dayString(_ date: Date) -> String {
        let c = Calendar.current.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }

    private func window(days: Int) -> (start: Date, anchor: Date) {
        let cal = Calendar.current
        let startOfToday = cal.startOfDay(for: Date())
        let start = cal.date(byAdding: .day, value: -max(1, days), to: startOfToday) ?? startOfToday
        return (start, start)
    }

    private func statistics(_ type: HKQuantityType, options: HKStatisticsOptions, days: Int) async throws -> HKStatisticsCollection {
        let (start, anchor) = window(days: days)
        let predicate = HKQuery.predicateForSamples(withStart: start, end: Date(), options: .strictStartDate)
        return try await withCheckedThrowingContinuation { cont in
            let q = HKStatisticsCollectionQuery(
                quantityType: type, quantitySamplePredicate: predicate,
                options: options, anchorDate: anchor,
                intervalComponents: DateComponents(day: 1)
            )
            q.initialResultsHandler = { _, result, error in
                if let result { cont.resume(returning: result) }
                else { cont.resume(throwing: error ?? HKError(.errorDatabaseInaccessible)) }
            }
            store.execute(q)
        }
    }

    private func dailySum(_ type: HKQuantityType, unit: HKUnit, type metricType: String, days: Int) async throws -> [[String: Any]] {
        let (start, _) = window(days: days)
        let coll = try await statistics(type, options: .cumulativeSum, days: days)
        var out: [[String: Any]] = []
        coll.enumerateStatistics(from: start, to: Date()) { stat, _ in
            guard let q = stat.sumQuantity() else { return }
            let v = q.doubleValue(for: unit)
            if v > 0 { out.append(["metric_type": metricType, "date": self.dayString(stat.startDate), "value": v]) }
        }
        return out
    }

    private func dailyAverage(_ type: HKQuantityType, unit: HKUnit, type metricType: String, days: Int) async throws -> [[String: Any]] {
        let (start, _) = window(days: days)
        let coll = try await statistics(type, options: .discreteAverage, days: days)
        var out: [[String: Any]] = []
        coll.enumerateStatistics(from: start, to: Date()) { stat, _ in
            guard let q = stat.averageQuantity() else { return }
            let v = q.doubleValue(for: unit)
            if v > 0 { out.append(["metric_type": metricType, "date": self.dayString(stat.startDate), "value": v]) }
        }
        return out
    }

    private func dailySleepHours(days: Int) async throws -> [[String: Any]] {
        let (start, _) = window(days: days)
        let predicate = HKQuery.predicateForSamples(withStart: start, end: Date(), options: .strictStartDate)
        let asleepValues: Set<Int> = [
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
        // Schlaf dem Tag zuordnen, an dem die Schlafphase ENDET (Aufwachen).
        var hoursByDay: [String: Double] = [:]
        for s in samples where asleepValues.contains(s.value) {
            let key = dayString(s.endDate)
            hoursByDay[key, default: 0] += s.endDate.timeIntervalSince(s.startDate) / 3600
        }
        return hoursByDay.compactMap { key, hours in
            hours > 0 ? ["metric_type": "schlaf", "date": key, "value": hours] : nil
        }
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

        let (data, resp) = try await URLSession.shared.data(for: req)
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

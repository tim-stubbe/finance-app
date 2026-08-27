import Foundation
import UserNotifications
import GRDB

/// Lokale Benachrichtigungen (UNUserNotificationCenter, KEIN APNs/Remote-
/// Push - dafür bräuchte es einen eigenen Push-Server-Unterbau, siehe
/// ROADMAP.md "iOS Push-Benachrichtigungen": bewusst weggelassen, kein
/// klarer minimaler Weg ohne Infrastruktur-Alptraum). UserNotifications ist
/// auf iOS und macOS identisch nutzbar, deshalb hier in KiesCore statt pro
/// Plattform dupliziert - Telegram bleibt die server-seitige Haupt-
/// Benachrichtigung (siehe backend/app/telegram_bot.py), das hier ist nur
/// eine Ergänzung direkt auf dem Gerät, für den Fall dass Telegram gerade
/// nicht offen ist.
///
/// Bewusst simpel gehalten (kein Hintergrund-Refresh-Unterbau vorhanden):
/// prüft bei jedem Sync (siehe SyncEngine.run()), was fällig ist, und
/// benachrichtigt einmalig pro Element (dedupliziert über eine ID-Menge in
/// UserDefaults) - kein exaktes "genau um 9 Uhr", sondern "spätestens beim
/// nächsten Öffnen/Sync der App bekommt der Nutzer es mit".
@MainActor
public final class NotificationManager: ObservableObject {
    public static let shared = NotificationManager()

    private static let enabledKey = "kies.notificationsEnabled"
    private static let notifiedIDsKey = "kies.notifiedItemIDs"
    private static let lastErrorNotifiedKey = "kies.lastErrorNotified"

    @Published public var enabled: Bool {
        didSet { UserDefaults.standard.set(enabled, forKey: Self.enabledKey) }
    }
    /// Ergebnis der letzten Berechtigungsabfrage - fürs UI (z.B. Hinweis,
    /// falls der Nutzer die Systemberechtigung verweigert hat).
    @Published public var authorizationDenied = false

    private init() {
        enabled = UserDefaults.standard.bool(forKey: Self.enabledKey)
    }

    public func requestAuthorization() async {
        let center = UNUserNotificationCenter.current()
        do {
            let granted = try await center.requestAuthorization(options: [.alert, .sound, .badge])
            authorizationDenied = !granted
        } catch {
            authorizationDenied = true
        }
    }

    /// Läuft nach jedem Sync (siehe SyncEngine.run) - meldet neu fällige
    /// Todos/Fristen (nicht bereits gemeldete, siehe notifiedIDs) und einen
    /// gerade erst aufgetretenen Sync-Fehler (nicht bei jedem Retry erneut).
    public func checkAndNotify(db: DatabaseQueue, lastError: String?) async {
        guard enabled else { return }
        // Reihenfolge bewusst als Array gehalten (nicht nur als Set) - der
        // Wachstumsdeckel unten (`suffix(500)`) soll die ZULETZT gemeldeten
        // IDs behalten, ein Set hat aber keine stabile Reihenfolge, `suffix`
        // darauf hätte willkürliche statt der neuesten IDs behalten.
        var notifiedOrder = UserDefaults.standard.stringArray(forKey: Self.notifiedIDsKey) ?? []
        let notifiedIDs = Set(notifiedOrder)
        var newNotifications: [(id: String, title: String, body: String)] = []

        let today = DateFormatter.isoDate.string(from: Date())
        let dueTodos = (try? await db.read { db in
            try Todo.filter(Column("done") == false)
                .filter(Column("due_date") <= today && Column("due_date") != nil)
                .fetchAll(db)
        }) ?? []
        for todo in dueTodos {
            let id = "todo-\(todo.id)"
            guard !notifiedIDs.contains(id) else { continue }
            newNotifications.append((id, "Todo fällig", todo.title))
        }

        let contracts = (try? await db.read { db in try Queries.contractRemindersDueSoon(db, withinDays: 0) }) ?? []
        for c in contracts {
            let id = "contract-\(c.id)"
            guard !notifiedIDs.contains(id) else { continue }
            newNotifications.append((id, "Kündigungsfrist", c.label))
        }

        let returns = (try? await db.read { db in try Queries.returnDeadlinesDueSoon(db, withinDays: 0) }) ?? []
        for r in returns {
            let id = "return-\(r.id)"
            guard !notifiedIDs.contains(id) else { continue }
            newNotifications.append((id, "Rückgabefrist", "Frist läuft bald ab"))
        }

        for n in newNotifications {
            await schedule(identifier: n.id, title: n.title, body: n.body)
            notifiedOrder.append(n.id)
        }
        // Wachstumsdeckel: alte IDs (z.B. längst erledigte Todos, deren
        // due_date nicht mehr auftaucht) würden die Liste sonst unbegrenzt
        // wachsen lassen - auf die zuletzt 500 begrenzen statt eine
        // aufwendige Bereinigung zu bauen. `suffix` auf dem geordneten
        // Array (nicht auf notifiedIDs, das Set hat keine stabile
        // Reihenfolge) behält wirklich die zuletzt gemeldeten IDs.
        if notifiedOrder.count > 500 {
            notifiedOrder = Array(notifiedOrder.suffix(500))
        }
        UserDefaults.standard.set(notifiedOrder, forKey: Self.notifiedIDsKey)

        let lastNotifiedError = UserDefaults.standard.string(forKey: Self.lastErrorNotifiedKey)
        if let lastError, lastError != lastNotifiedError {
            await schedule(identifier: "sync-error", title: "Sync fehlgeschlagen", body: lastError)
            UserDefaults.standard.set(lastError, forKey: Self.lastErrorNotifiedKey)
        } else if lastError == nil {
            UserDefaults.standard.removeObject(forKey: Self.lastErrorNotifiedKey)
        }
    }

    private func schedule(identifier: String, title: String, body: String) async {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        // Nahezu sofort statt auf einen exakten künftigen Zeitpunkt geplant
        // (siehe Typkommentar oben) - ein Trigger mit 0 wird von
        // UNUserNotificationCenter abgelehnt, 1 Sekunde ist der kleinste
        // gültige Wert.
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: 1, repeats: false)
        let request = UNNotificationRequest(identifier: identifier, content: content, trigger: trigger)
        try? await UNUserNotificationCenter.current().add(request)
    }
}

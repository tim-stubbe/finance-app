import WidgetKit
import SwiftUI
import KiesCore

/// "Heute"-Widget - Tagesbilanz plus nächstes Todo/nächster Termin, aus
/// derselben lokalen SQLite-DB wie die App (siehe AppDatabase.appGroupID) -
/// kein eigener Netzwerk-Aufruf, das Widget liest nur, was der letzte Sync
/// der App bereits abgelegt hat. Tippen öffnet die App auf dem Heute-Tab
/// (siehe widgetURL/KiesiOSApp.onOpenURL, URL-Schema "kies").
struct KiesTodayEntry: TimelineEntry {
    let date: Date
    let isPaired: Bool
    let income: Double
    let expense: Double
    let nextTodoTitle: String?
    let nextEventTitle: String?
    let nextEventTime: String?
}

struct KiesTodayProvider: TimelineProvider {
    func placeholder(in context: Context) -> KiesTodayEntry {
        KiesTodayEntry(date: Date(), isPaired: true, income: 1200, expense: 430,
                        nextTodoTitle: "Steuererklärung", nextEventTitle: "Zahnarzt", nextEventTime: "14:00")
    }

    func getSnapshot(in context: Context, completion: @escaping (KiesTodayEntry) -> Void) {
        completion(loadEntry())
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<KiesTodayEntry>) -> Void) {
        let entry = loadEntry()
        // WidgetKit begrenzt die Aktualisierungsrate ohnehin (Budget pro Tag,
        // grob alle paar Stunden bei normaler Nutzung) - 30 Minuten ist ein
        // vernünftiger Wunschwert, kein Versprechen. Der eigentliche "frisch
        // nach Sync"-Fall läuft über WidgetCenter.reloadAllTimelines() direkt
        // nach einem erfolgreichen Sync (siehe KiesiOSApp.RootView).
        let nextRefresh = Calendar.current.date(byAdding: .minute, value: 30, to: Date()) ?? Date().addingTimeInterval(1800)
        completion(Timeline(entries: [entry], policy: .after(nextRefresh)))
    }

    private func loadEntry() -> KiesTodayEntry {
        guard PairingStore.shared.isPaired else {
            return KiesTodayEntry(date: Date(), isPaired: false, income: 0, expense: 0, nextTodoTitle: nil, nextEventTitle: nil, nextEventTime: nil)
        }
        let db = AppDatabase.shared
        let balance = (try? db.read { try Queries.todayBalance($0) }) ?? (income: 0, expense: 0)
        let todo = try? db.read { try Queries.nextOpenTodo($0) }
        let event = try? db.read { try Queries.nextUpcomingEvent($0) }
        var eventTime: String?
        if let event, let start = DateFormatter.parseServerDateTime(event.start) {
            eventTime = event.all_day ? "ganztägig" : DateFormatter.eventDisplay.string(from: start)
        }
        return KiesTodayEntry(
            date: Date(), isPaired: true, income: balance.income, expense: balance.expense,
            nextTodoTitle: (todo ?? nil)?.title, nextEventTitle: (event ?? nil)?.title, nextEventTime: eventTime
        )
    }
}

struct KiesTodayWidgetView: View {
    @Environment(\.widgetFamily) var family
    let entry: KiesTodayEntry

    var body: some View {
        if !entry.isPaired {
            VStack(spacing: 4) {
                Image(systemName: "link.badge.plus").font(.title3).foregroundStyle(.secondary)
                Text("Nicht gekoppelt").font(.caption).foregroundStyle(.secondary)
            }
            .containerBackground(.fill.tertiary, for: .widget)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Image(systemName: "sun.max.fill").foregroundStyle(.orange)
                    Text("Heute").font(.headline)
                    Spacer()
                }
                HStack(spacing: 12) {
                    balanceColumn(label: "Ein", value: entry.income, color: .green)
                    balanceColumn(label: "Aus", value: entry.expense, color: .red)
                }
                if family != .systemSmall {
                    Divider()
                    if let title = entry.nextEventTitle {
                        row(icon: "calendar", text: title, detail: entry.nextEventTime)
                    }
                    if let title = entry.nextTodoTitle {
                        row(icon: "checklist", text: title, detail: nil)
                    }
                    if entry.nextEventTitle == nil && entry.nextTodoTitle == nil {
                        Text("Nichts Anstehendes").font(.caption).foregroundStyle(.secondary)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(.vertical, 2)
            .containerBackground(.fill.tertiary, for: .widget)
            .widgetURL(URL(string: "kies://today"))
        }
    }

    private func balanceColumn(label: String, value: Double, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(label).font(.caption2).foregroundStyle(.secondary)
            Text(value, format: .currency(code: "EUR").precision(.fractionLength(0)))
                .font(.subheadline.bold())
                .foregroundStyle(color)
        }
    }

    private func row(icon: String, text: String, detail: String?) -> some View {
        HStack(spacing: 4) {
            Image(systemName: icon).font(.caption2).foregroundStyle(.secondary).frame(width: 14)
            Text(text).font(.caption).lineLimit(1)
            if let detail { Text(detail).font(.caption2).foregroundStyle(.secondary) }
        }
    }
}

struct KiesTodayWidget: Widget {
    let kind: String = "KiesTodayWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: KiesTodayProvider()) { entry in
            KiesTodayWidgetView(entry: entry)
        }
        .configurationDisplayName("Kies Heute")
        .description("Tagesbilanz, nächster Termin und fälliges Todo.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

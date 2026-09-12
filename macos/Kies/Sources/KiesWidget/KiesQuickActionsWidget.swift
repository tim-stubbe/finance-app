import WidgetKit
import SwiftUI
import KiesCore

/// Schnellschalter-Widget: drei Buttons (Buchung/Todo/Check-in), die die App
/// direkt im QuickCapture-Sheet mit vorausgewählter Art öffnen (siehe
/// QuickCaptureRouter/KiesiOSApp.onOpenURL, URL-Schema "kies://quick-
/// capture?kind=..."). Anders als KiesTodayWidget hat dieses Widget keinen
/// eigenen `TimelineProvider`-Zustand aus der DB - die drei Ziele sind
/// statisch, ein einzelner Snapshot reicht (kein periodisches Neuladen
/// nötig).
struct KiesQuickActionsEntry: TimelineEntry {
    let date: Date
    let isPaired: Bool
}

struct KiesQuickActionsProvider: TimelineProvider {
    func placeholder(in context: Context) -> KiesQuickActionsEntry {
        KiesQuickActionsEntry(date: Date(), isPaired: true)
    }

    func getSnapshot(in context: Context, completion: @escaping (KiesQuickActionsEntry) -> Void) {
        completion(KiesQuickActionsEntry(date: Date(), isPaired: PairingStore.shared.isPaired))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<KiesQuickActionsEntry>) -> Void) {
        let entry = KiesQuickActionsEntry(date: Date(), isPaired: PairingStore.shared.isPaired)
        // Statischer Inhalt - Policy .never, ein Reload passiert nur, wenn
        // sich der Pairing-Status ändert (WidgetCenter.reloadAllTimelines()
        // nach erfolgreichem Sync, siehe KiesiOSApp.RootView).
        completion(Timeline(entries: [entry], policy: .never))
    }
}

struct KiesQuickActionsWidgetView: View {
    let entry: KiesQuickActionsEntry

    var body: some View {
        if !entry.isPaired {
            VStack(spacing: 4) {
                Image(systemName: "link.badge.plus").font(.title3).foregroundStyle(.secondary)
                Text("Nicht gekoppelt").font(.caption).foregroundStyle(.secondary)
            }
            .containerBackground(.fill.tertiary, for: .widget)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                Text("Schnell erfassen").font(.headline)
                HStack(spacing: 8) {
                    actionButton(title: "Buchung", icon: "arrow.left.arrow.right", color: .blue, kind: "transaction")
                    actionButton(title: "Todo", icon: "checklist", color: .orange, kind: "todo")
                    actionButton(title: "Check-in", icon: "heart.fill", color: .pink, kind: "checkin")
                }
            }
            .padding(.vertical, 2)
            .containerBackground(.fill.tertiary, for: .widget)
        }
    }

    private func actionButton(title: String, icon: String, color: Color, kind: String) -> some View {
        Link(destination: URL(string: "kies://quick-capture?kind=\(kind)")!) {
            VStack(spacing: 4) {
                Image(systemName: icon).font(.title3).foregroundStyle(color)
                Text(title).font(.caption2).foregroundStyle(.primary).lineLimit(1)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 8)
            .background(color.opacity(0.12), in: RoundedRectangle(cornerRadius: 10))
        }
    }
}

struct KiesQuickActionsWidget: Widget {
    let kind: String = "KiesQuickActionsWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: KiesQuickActionsProvider()) { entry in
            KiesQuickActionsWidgetView(entry: entry)
        }
        .configurationDisplayName("Kies Schnellerfassung")
        .description("Buchung, Todo oder Check-in direkt vom Home-Screen anlegen.")
        .supportedFamilies([.systemMedium])
    }
}

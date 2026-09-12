import ActivityKit
import WidgetKit
import SwiftUI
import KiesCore

/// Rein lokal verwaltete Live Activity (kein APNs im Projekt) - die App
/// `TimerActivityAttributes` kommt aus KiesCore, damit KiesiOS
/// (`LiveActivityManager`) und diese Extension (getrenntes Xcode-Target,
/// kein Source-Sharing) exakt denselben Typ verwenden.
/// startet/beendet sie direkt per `Activity.request`/`.end`, siehe
/// `LiveActivityManager` in KiesiOS.
struct TimerLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: TimerActivityAttributes.self) { context in
            lockScreenView(context: context)
                .activityBackgroundTint(Color.black.opacity(0.85))
                .activitySystemActionForegroundColor(.white)
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    Image(systemName: "clock.fill").foregroundStyle(.orange)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    Text(timerInterval: context.state.startedAt...Date.distantFuture, countsDown: false)
                        .monospacedDigit()
                }
                DynamicIslandExpandedRegion(.center) {
                    Text(context.state.projectName)
                        .font(.headline)
                        .lineLimit(1)
                }
            } compactLeading: {
                Image(systemName: "clock.fill").foregroundStyle(.orange)
            } compactTrailing: {
                Text(timerInterval: context.state.startedAt...Date.distantFuture, countsDown: false)
                    .monospacedDigit()
                    .frame(maxWidth: 44)
            } minimal: {
                Image(systemName: "clock.fill").foregroundStyle(.orange)
            }
            .widgetURL(URL(string: "kies://time-tracking"))
        }
    }

    private func lockScreenView(context: ActivityViewContext<TimerActivityAttributes>) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text("Zeiterfassung läuft")
                    .font(.caption)
                    .foregroundStyle(.white.opacity(0.7))
                Text(context.state.projectName)
                    .font(.headline)
                    .foregroundStyle(.white)
                    .lineLimit(1)
            }
            Spacer()
            Text(timerInterval: context.state.startedAt...Date.distantFuture, countsDown: false)
                .monospacedDigit()
                .font(.title3.weight(.semibold))
                .foregroundStyle(.white)
        }
        .padding(16)
    }
}

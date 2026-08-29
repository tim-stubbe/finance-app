import SwiftUI
import Charts

/// Gesundheits-Verlauf direkt aus Apple Health (kein Server-Roundtrip -
/// funktioniert offline). Vier Kennzahlen als Karten mit Tagesdiagramm,
/// letztem Wert und 7-Tage-Mittel. Der Import zum Kies-Server laeuft weiter
/// ueber HealthKitSync (Einstellungen), das hier ist reine Anzeige.
struct HealthView: View {
    @ObservedObject private var health = HealthKitSync.shared
    @StateObject private var series = Box(HealthSeries())
    @StateObject private var days = Box(90)
    @StateObject private var loading = Box(true)

    var body: some View {
        KScreen {
            Picker("Zeitraum", selection: days.binding) {
                Text("30 Tage").tag(30)
                Text("90 Tage").tag(90)
                Text("1 Jahr").tag(365)
            }
            .pickerStyle(.segmented)

            if !health.isAvailable {
                Text("Apple Health ist auf diesem Gerät nicht verfügbar.")
                    .font(.callout).foregroundStyle(KTheme.muted).kCard()
            } else if loading.value {
                ProgressView().frame(maxWidth: .infinity).padding(.vertical, 40)
            } else if series.value.isEmpty {
                VStack(spacing: 8) {
                    Text("Keine Health-Daten sichtbar.").font(.kSerif(.headline)).foregroundStyle(KTheme.text)
                    Text("Freigabe in iOS-Einstellungen → Datenschutz → Health → Kies prüfen. Der Import zum Server läuft über Einstellungen → „Apple Health synchronisieren“.")
                        .font(.caption).foregroundStyle(KTheme.muted)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .kCard()
            } else {
                metricCard("Schritte", unit: "", points: series.value.steps, kind: .bar, decimals: 0)
                metricCard("Ruhepuls", unit: "bpm", points: series.value.pulse, kind: .line, decimals: 0)
                metricCard("Gewicht", unit: "kg", points: series.value.weight, kind: .line, decimals: 1)
                metricCard("Schlaf", unit: "Std.", points: series.value.sleep, kind: .bar, decimals: 1)
            }
        }
        .navigationTitle("Gesundheit")
        .task { await load() }
        .onChange(of: days.value) { _, _ in Task { await load() } }
        .refreshable { await load() }
    }

    private enum ChartKind { case line, bar }

    @ViewBuilder
    private func metricCard(_ title: String, unit: String, points: [HealthPoint], kind: ChartKind, decimals: Int) -> some View {
        KSection(title: title) {
            if points.isEmpty {
                Text("keine Werte").font(.caption).foregroundStyle(KTheme.muted)
            } else {
                let last = points.last!
                let recent = points.suffix(7)
                let avg = recent.map(\.value).reduce(0, +) / Double(recent.count)
                HStack(alignment: .firstTextBaseline, spacing: 16) {
                    valueBlock("zuletzt", last.value, unit: unit, decimals: decimals)
                    valueBlock("Ø 7 Tage", avg, unit: unit, decimals: decimals)
                    Spacer()
                }
                Chart(points) { p in
                    if kind == .bar {
                        BarMark(x: .value("Tag", p.day, unit: .day), y: .value(title, p.value))
                            .foregroundStyle(KTheme.gold)
                    } else {
                        LineMark(x: .value("Tag", p.day), y: .value(title, p.value))
                            .foregroundStyle(KTheme.gold)
                            .interpolationMethod(.monotone)
                        AreaMark(x: .value("Tag", p.day), y: .value(title, p.value))
                            .foregroundStyle(.linearGradient(
                                colors: [KTheme.gold.opacity(0.22), KTheme.gold.opacity(0.02)],
                                startPoint: .top, endPoint: .bottom))
                            .interpolationMethod(.monotone)
                    }
                }
                .chartYScale(domain: .automatic(includesZero: kind == .bar))
                .frame(height: 120)
            }
        }
    }

    private func valueBlock(_ label: String, _ value: Double, unit: String, decimals: Int) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            KKicker(text: label)
            Text(fmt(value, decimals: decimals) + (unit.isEmpty ? "" : " " + unit))
                .font(.kSerif(.title3)).foregroundStyle(KTheme.text).monospacedDigit()
        }
    }

    private func fmt(_ v: Double, decimals: Int) -> String {
        v.formatted(.number.precision(.fractionLength(decimals)))
    }

    private func load() async {
        loading.value = true
        defer { loading.value = false }
        series.value = (try? await health.series(days: days.value)) ?? HealthSeries()
    }
}

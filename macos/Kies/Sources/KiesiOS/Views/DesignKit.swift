import SwiftUI

/// Gemeinsames visuelles Vokabular der iOS-App: Karten-Container, Kennzahl-
/// Kacheln, Abschnitts-Karten und ein Bildschirm-Wrapper mit einheitlichem
/// Hintergrund/Abstand. Bewusst schlank und ohne eigenes Farbsystem - nutzt
/// die semantischen System-Farben (Dark Mode & Dynamic Type kostenlos).
enum KTheme {
    static let corner: CGFloat = 20
    static let gap: CGFloat = 14

    static let background = Color(uiColor: .systemGroupedBackground)
    static let card = Color(uiColor: .secondarySystemGroupedBackground)
    static let positive = Color.green
    static let negative = Color(uiColor: .systemRed)

    /// Feste Farbreihe für Diagramm-Kategorien (Depot-Aufteilung o.ä.).
    static let chartPalette: [Color] = [
        .blue, .teal, .orange, .purple, .pink, .green, .indigo, .mint, .red, .cyan,
    ]
}

func kEUR(_ value: Double, fraction: Int = 0) -> String {
    value.formatted(.currency(code: "EUR").precision(.fractionLength(fraction)))
}

extension View {
    /// Standard-Kartenlook: Innenabstand, volle Breite, abgerundeter Fond.
    func kCard(_ padding: CGFloat = 16) -> some View {
        self
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(KTheme.card, in: RoundedRectangle(cornerRadius: KTheme.corner, style: .continuous))
    }

    /// Einheitlicher Hintergrund fuer die Screens, die weiter `List` nutzen
    /// (Todos/Ziele/Wuensche/... - dort haengen die Swipe-Aktionen dran).
    /// Zusammen mit `.listRowBackground(KTheme.card)` + versteckten Trennern
    /// ergibt das denselben Karten-Look wie die KScreen-Seiten.
    func kListChrome() -> some View {
        self
            .scrollContentBackground(.hidden)
            .background(KTheme.background.ignoresSafeArea())
    }

    func kListRow() -> some View {
        self
            .listRowBackground(KTheme.card)
            .listRowSeparator(.hidden)
    }
}

/// Scrollbarer Bildschirm mit einheitlichem Hintergrund + Rändern. Ersetzt
/// `List` auf den Übersichts-Screens (Heute/Konten/Investments), damit dort
/// Diagramme und Karten Platz haben. `.refreshable` funktioniert weiterhin.
struct KScreen<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        ScrollView {
            VStack(spacing: KTheme.gap) { content }
                .padding(.horizontal, 16)
                .padding(.top, 8)
                .padding(.bottom, 24)
        }
        .background(KTheme.background.ignoresSafeArea())
    }
}

/// Kompakte Kennzahl (Label oben, großer Wert darunter). In einer HStack
/// nebeneinander ergeben mehrere davon eine Kennzahlen-Reihe.
struct KStatTile: View {
    let label: String
    let value: String
    var tint: Color = .primary
    var caption: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label.uppercased())
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
            Text(value)
                .font(.title3.weight(.semibold))
                .foregroundStyle(tint)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
            if let caption {
                Text(caption).font(.caption2).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .kCard(14)
    }
}

/// Abschnitts-Karte mit Titel (+ optionalem SF-Symbol) und beliebigem Inhalt.
struct KSection<Content: View>: View {
    let title: String
    var systemImage: String? = nil
    var accessory: AnyView? = nil
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 6) {
                if let systemImage { Image(systemName: systemImage) }
                Text(title).font(.subheadline.weight(.semibold))
                Spacer()
                if let accessory { accessory }
            }
            .foregroundStyle(.secondary)
            content
        }
        .kCard()
    }
}

/// Eine schlichte Zeile innerhalb einer KSection (Titel links, Wert rechts).
struct KRow: View {
    let title: String
    var subtitle: String? = nil
    var trailing: String? = nil
    var trailingTint: Color = .secondary

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.callout)
                if let subtitle {
                    Text(subtitle).font(.caption).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 8)
            if let trailing {
                Text(trailing).font(.callout.weight(.medium)).foregroundStyle(trailingTint)
            }
        }
    }
}

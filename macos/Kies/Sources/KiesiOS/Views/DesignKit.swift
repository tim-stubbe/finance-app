import SwiftUI

/// Visuelles Vokabular der iOS-App - angelehnt an das "Alpen Desktop"-Theme
/// der Web-App (frontend/style.css, [data-theme="alpen-desktop"]):
/// warmer, fast schwarzer Grundton, Gold als einzige Akzentfarbe, das
/// Matterhorn-Foto als dezenter Hintergrund, Serifenschrift (System-"New
/// York" via .serif-Design) fuer Ueberschriften und grosse Zahlen. Immer
/// dunkel, scharfe Ecken statt runder Karten.
enum KTheme {
    static let corner: CGFloat = 10
    static let gap: CGFloat = 14

    // #191817 warmes Fast-Schwarz
    static let background = Color(red: 0.098, green: 0.094, blue: 0.090)
    // translucentes Weiss auf dem Grundton (wie --surface-2 im Web-Theme)
    static let card = Color.white.opacity(0.05)
    static let hairline = Color.white.opacity(0.12)

    // Gold: --accent #e1ad66 / --accent-strong #eec089 / --accent-deep #b9884b
    static let gold = Color(red: 0.882, green: 0.678, blue: 0.400)
    static let goldStrong = Color(red: 0.933, green: 0.753, blue: 0.537)
    static let goldDeep = Color(red: 0.725, green: 0.533, blue: 0.294)

    static let text = Color(red: 0.957, green: 0.945, blue: 0.925)      // #f4f1ec
    static let textSecondary = Color(red: 0.957, green: 0.945, blue: 0.925).opacity(0.75)
    static let muted = Color(red: 0.957, green: 0.945, blue: 0.925).opacity(0.5)

    // Gewinn/Verlust bleiben klassisch gruen/rot (wie im Web-Theme bewusst
    // NICHT in Gold-Abstufung).
    static let positive = Color(red: 0.298, green: 0.686, blue: 0.431)  // #4caf6e
    static let negative = Color(red: 0.878, green: 0.361, blue: 0.322)  // #e05c52

    static let chartPalette: [Color] = [
        gold, Color(red: 0.839, green: 0.561, blue: 0.525), Color(red: 0.788, green: 0.827, blue: 0.878),
        Color(red: 0.659, green: 0.710, blue: 0.769), goldStrong, Color(red: 0.541, green: 0.592, blue: 0.678),
        goldDeep, Color(red: 0.604, green: 0.647, blue: 0.694),
    ]
}

func kEUR(_ value: Double, fraction: Int = 0) -> String {
    value.formatted(.currency(code: "EUR").precision(.fractionLength(fraction)))
}

/// Serifen-Titel (System "New York"), wie die Cormorant-Garamond-
/// Ueberschriften im Web-Theme.
extension Font {
    static func kSerif(_ style: Font.TextStyle, weight: Font.Weight = .regular) -> Font {
        .system(style, design: .serif).weight(weight)
    }
}

extension View {
    /// Karten-Look: translucentes Weiss, scharfe Ecke, Haarlinie.
    func kCard(_ padding: CGFloat = 16) -> some View {
        self
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(KTheme.card, in: RoundedRectangle(cornerRadius: KTheme.corner, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: KTheme.corner, style: .continuous)
                    .strokeBorder(KTheme.hairline, lineWidth: 1)
            )
    }

    /// Fuer die Screens, die weiter `List` nutzen (Swipe-Aktionen).
    func kListChrome() -> some View {
        self
            .scrollContentBackground(.hidden)
            .background(AlpenBackdrop())
    }

    func kListRow() -> some View {
        self
            .listRowBackground(
                RoundedRectangle(cornerRadius: KTheme.corner, style: .continuous)
                    .fill(KTheme.card)
                    .strokeBorder(KTheme.hairline, lineWidth: 1)
                    .padding(.vertical, 2)
            )
            .listRowSeparator(.hidden)
    }
}

/// Warmer Grundton + Matterhorn-Foto oben, nach unten ausgeblendet - das
/// gemeinsame Hintergrundbild aller Screens (wie body::before im Web-Theme).
///
/// WICHTIG: `Color` als Basis (fuellt den verfuegbaren Platz) + das Bild als
/// `.overlay` mit `maxWidth:.infinity` + `.clipped()`. `scaledToFill()` ohne
/// begrenzten Rahmen und Clip laesst das 2400px-Bild horizontal ueberlaufen
/// und weitete den umschliessenden ZStack - dadurch war die ganze Oberflaeche
/// zu breit und nach links abgeschnitten.
struct AlpenBackdrop: View {
    var body: some View {
        KTheme.background
            .overlay(alignment: .top) {
                Image("AlpenBackground")
                    .resizable()
                    .scaledToFill()
                    .frame(height: 360)
                    .frame(maxWidth: .infinity)
                    .clipped()
                    .opacity(0.28)
                    .mask(
                        LinearGradient(colors: [.black, .black.opacity(0.65), .clear],
                                       startPoint: .top, endPoint: .bottom)
                    )
                    .allowsHitTesting(false)
            }
            .ignoresSafeArea()
    }
}

/// Scrollbarer Bildschirm fuer die Uebersichten (Heute/Konten/Investments/Mehr).
struct KScreen<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        ScrollView {
            VStack(spacing: KTheme.gap) { content }
                .padding(.horizontal, 16)
                .padding(.top, 8)
                .padding(.bottom, 28)
        }
        .background(AlpenBackdrop())
    }
}

/// Kleine, weit gesperrte Versalzeile ueber einer Ueberschrift.
struct KKicker: View {
    let text: String
    var body: some View {
        Text(text.uppercased())
            .font(.system(size: 10, weight: .regular))
            .tracking(3)
            .foregroundStyle(KTheme.muted)
    }
}

struct KStatTile: View {
    let label: String
    let value: String
    var tint: Color = KTheme.text
    var caption: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            KKicker(text: label)
            Text(value)
                .font(.kSerif(.title3))
                .foregroundStyle(tint)
                .lineLimit(1)
                .minimumScaleFactor(0.5)
                .monospacedDigit()
            if let caption {
                Text(caption).font(.caption2).foregroundStyle(KTheme.muted)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .kCard(14)
    }
}

struct KSection<Content: View>: View {
    let title: String
    var systemImage: String? = nil
    var accessory: AnyView? = nil
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 6) {
                if let systemImage { Image(systemName: systemImage).foregroundStyle(KTheme.gold) }
                Text(title).font(.kSerif(.headline, weight: .medium)).foregroundStyle(KTheme.text)
                Spacer()
                if let accessory { accessory }
            }
            content
        }
        .kCard()
    }
}

struct KRow: View {
    let title: String
    var subtitle: String? = nil
    var trailing: String? = nil
    var trailingTint: Color = KTheme.textSecondary

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.callout).foregroundStyle(KTheme.text)
                if let subtitle {
                    Text(subtitle).font(.caption).foregroundStyle(KTheme.muted)
                }
            }
            Spacer(minLength: 8)
            if let trailing {
                Text(trailing).font(.callout.weight(.medium)).foregroundStyle(trailingTint).monospacedDigit()
            }
        }
    }
}

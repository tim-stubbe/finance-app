import SwiftUI

// MARK: - Design-System
//
// Zentrales visuelles Vokabular der iOS-App. Light Mode ist der Standard
// (sehr helles Off-White, weiße Flächen, Blau als Interaktionsfarbe), Dark
// Mode wird über dynamische Farben vollständig unterstützt. KEIN globales
// Fotohintergrundbild mehr - die App wirkt ruhig und clean.
//
// Views verwenden ausschließlich diese Tokens/Komponenten, keine hart
// codierten Farben. `KTheme` / `Font.kSerif` / `AlpenBackdrop` bleiben als
// dünne Kompatibilitäts-Aliase erhalten, damit bestehende Views ohne
// Sammel-Umbau weiterlaufen.

// MARK: Farben

enum KColor {
    /// Baut eine dynamische Farbe (light/dark) aus zwei Hex-Werten.
    private static func dyn(_ light: UInt32, _ dark: UInt32) -> Color {
        Color(uiColor: UIColor { $0.userInterfaceStyle == .dark ? UIColor(hex: dark) : UIColor(hex: light) })
    }

    static let background        = dyn(0xF7F7F8, 0x111214)
    static let surface           = dyn(0xFFFFFF, 0x1A1C1F)
    static let surfaceSecondary  = dyn(0xF1F2F4, 0x24272B)
    static let primary           = dyn(0x15171A, 0xF5F5F7)   // Primärtext
    static let secondary         = dyn(0x73777D, 0x9B9FA6)   // Sekundärtext
    static let divider           = dyn(0xE5E6E8, 0x303338)

    static let accent            = dyn(0x0A84FF, 0x0A84FF)   // iOS-Blau
    static let positive          = dyn(0x1DA860, 0x30D97A)
    static let negative          = dyn(0xE0393B, 0xFF5A5F)
    static let warning           = dyn(0xF5A623, 0xFFB43A)

    /// Kategorie-/Chart-Palette (blau-zentriert, keine Gold-Dominanz mehr).
    static let chartPalette: [Color] = [
        dyn(0x0A84FF, 0x0A84FF), dyn(0x30B0C7, 0x40C8E0), dyn(0x1DA860, 0x30D97A),
        dyn(0xF5A623, 0xFFB43A), dyn(0xAF52DE, 0xBF5AF2), dyn(0xFF6482, 0xFF7E9B),
        dyn(0x5E5CE6, 0x7D7BFF), dyn(0x8E8E93, 0xA8A8AE),
    ]
}

extension UIColor {
    fileprivate convenience init(hex: UInt32) {
        self.init(
            red:   CGFloat((hex >> 16) & 0xFF) / 255,
            green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue:  CGFloat(hex & 0xFF) / 255,
            alpha: 1
        )
    }
}

// MARK: Abstände / Radien / Schatten

enum KSpacing {
    static let xs: CGFloat = 4
    static let sm: CGFloat = 8
    static let md: CGFloat = 16
    static let lg: CGFloat = 24
    static let xl: CGFloat = 32
}

enum KRadius {
    static let sm: CGFloat = 10
    static let md: CGFloat = 16
    static let lg: CGFloat = 22
}

struct KShadow: ViewModifier {
    func body(content: Content) -> some View {
        content.shadow(color: .black.opacity(0.06), radius: 12, x: 0, y: 4)
    }
}

// MARK: Typografie

enum KFont {
    /// Große monetäre Werte: SF Rounded, halbfett, monospaced digits.
    static func number(_ size: CGFloat, weight: Font.Weight = .semibold) -> Font {
        .system(size: size, weight: weight, design: .rounded).monospacedDigit()
    }
    static let hero      = number(38, weight: .bold)
    static let metric    = number(24)
    static let title      = Font.system(.largeTitle, design: .default).weight(.bold)
    static let sectionH   = Font.system(.subheadline, design: .default).weight(.semibold)
    static let row        = Font.system(.body)
    static let rowSub     = Font.system(.footnote)
    static let caption    = Font.system(.caption)
}

/// Währung ohne Nachkommastellen bei Summary-Werten, mit bei Detailbeträgen.
func kEUR(_ value: Double, fraction: Int = 0) -> String {
    value.formatted(.currency(code: "EUR").precision(.fractionLength(fraction)))
}

/// Kompat-Alias: früher Serifen-Titel, jetzt System-Font (SF Pro).
extension Font {
    static func kSerif(_ style: Font.TextStyle, weight: Font.Weight = .semibold) -> Font {
        .system(style, design: .default).weight(weight)
    }
}

// MARK: Kompatibilitäts-Shim für bestehende Views

enum KTheme {
    static let corner: CGFloat = KRadius.md
    static let gap: CGFloat = KSpacing.md
    static let background = KColor.background
    static let card = KColor.surface
    static let hairline = KColor.divider
    static let accent = KColor.accent
    static let gold = KColor.accent        // Gold ist nicht mehr die Akzentfarbe
    static let goldStrong = KColor.accent
    static let goldDeep = KColor.accent
    static let text = KColor.primary
    static let textSecondary = KColor.secondary
    static let muted = KColor.secondary
    static let positive = KColor.positive
    static let negative = KColor.negative
    static let chartPalette = KColor.chartPalette
}

/// Früher das Matterhorn-Foto - jetzt nur noch die ruhige Hintergrundfläche.
struct AlpenBackdrop: View {
    var body: some View { KColor.background.ignoresSafeArea() }
}

// MARK: Container

/// Scrollbarer Standard-Screen (Übersicht / Konten / Analyse / Mehr).
struct KScreen<Content: View>: View {
    var spacing: CGFloat = KSpacing.lg
    @ViewBuilder var content: Content
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: spacing) { content }
                .padding(.horizontal, KSpacing.md)
                .padding(.top, KSpacing.sm)
                .padding(.bottom, KSpacing.xl + 24)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(KColor.background.ignoresSafeArea())
        .scrollDismissesKeyboard(.interactively)
    }
}

extension View {
    /// Karten-Look: weiße Fläche, sanfter Schatten (keine harte Border),
    /// 16 pt Radius, großzügiges Padding. Karten nur für Summary-Gruppen.
    func kCard(_ padding: CGFloat = KSpacing.md) -> some View {
        self
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(KColor.surface, in: RoundedRectangle(cornerRadius: KRadius.md, style: .continuous))
            .modifier(KShadow())
    }

    /// Für Screens, die native `List` nutzen (Swipe-Aktionen).
    func kListChrome() -> some View {
        self
            .scrollContentBackground(.hidden)
            .background(KColor.background.ignoresSafeArea())
    }

    func kListRow() -> some View {
        self
            .listRowBackground(KColor.surface)
            .listRowSeparatorTint(KColor.divider)
    }
}

// MARK: Bausteine

/// Kleine, weit gesperrte Sekundär-Zeile über einem Titel.
struct KKicker: View {
    let text: String
    var body: some View {
        Text(text.uppercased())
            .font(.system(size: 11, weight: .semibold))
            .tracking(0.8)
            .foregroundStyle(KColor.secondary)
    }
}

/// Abschnitts-Überschrift im Screen-Fluss (kein Karten-Rahmen).
struct KSectionHeader: View {
    let title: String
    var action: (title: String, run: () -> Void)? = nil
    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title).font(KFont.sectionH).foregroundStyle(KColor.primary)
            Spacer()
            if let action {
                Button(action.title, action: action.run)
                    .font(.footnote.weight(.medium))
                    .foregroundStyle(KColor.accent)
            }
        }
    }
}

/// Eine Kennzahl-Kachel (Einnahmen / Ausgaben / Netto …).
struct KStatTile: View {
    let label: String
    let value: String
    var tint: Color = KColor.primary
    var caption: String? = nil
    var body: some View {
        VStack(alignment: .leading, spacing: KSpacing.xs) {
            Text(label).font(.footnote).foregroundStyle(KColor.secondary)
            Text(value).font(KFont.metric).foregroundStyle(tint)
                .lineLimit(1).minimumScaleFactor(0.5)
            if let caption { Text(caption).font(.caption2).foregroundStyle(KColor.secondary) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .kCard(KSpacing.md)
    }
}

typealias KMetricCard = KStatTile

/// Gruppierende Karte mit Titel (für Summary-Bereiche).
struct KSection<Content: View>: View {
    let title: String
    var systemImage: String? = nil
    var accessory: AnyView? = nil
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: KSpacing.md) {
            HStack(spacing: KSpacing.sm) {
                if let systemImage {
                    Image(systemName: systemImage).font(.footnote).foregroundStyle(KColor.accent)
                }
                Text(title).font(KFont.sectionH).foregroundStyle(KColor.primary)
                Spacer()
                if let accessory { accessory }
            }
            content
        }
        .kCard()
    }
}

/// Schlichte Zeile (Titel / Untertitel / Betrag rechts).
struct KRow: View {
    let title: String
    var subtitle: String? = nil
    var trailing: String? = nil
    var trailingTint: Color = KColor.primary
    var body: some View {
        HStack(alignment: .center, spacing: KSpacing.sm) {
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(KFont.row).foregroundStyle(KColor.primary)
                if let subtitle {
                    Text(subtitle).font(KFont.rowSub).foregroundStyle(KColor.secondary)
                }
            }
            Spacer(minLength: KSpacing.sm)
            if let trailing {
                Text(trailing).font(KFont.row.weight(.medium))
                    .foregroundStyle(trailingTint).monospacedDigit()
            }
        }
        .padding(.vertical, 2)
    }
}

/// Konto-Zeile: SF-Symbol, Name, Typ, Betrag, Chevron.
struct KAccountRow: View {
    let icon: String
    let name: String
    let subtitle: String
    let amount: Double
    var body: some View {
        HStack(spacing: KSpacing.md) {
            Image(systemName: icon)
                .font(.callout).foregroundStyle(KColor.accent)
                .frame(width: 30, height: 30)
                .background(KColor.accent.opacity(0.12), in: RoundedRectangle(cornerRadius: KRadius.sm, style: .continuous))
            VStack(alignment: .leading, spacing: 1) {
                Text(name).font(KFont.row).foregroundStyle(KColor.primary)
                Text(subtitle).font(KFont.rowSub).foregroundStyle(KColor.secondary)
            }
            Spacer(minLength: KSpacing.sm)
            Text(kEUR(amount, fraction: 2))
                .font(KFont.row.weight(.semibold)).monospacedDigit()
                .foregroundStyle(amount < 0 ? KColor.negative : KColor.primary)
            Image(systemName: "chevron.right").font(.caption).foregroundStyle(KColor.secondary.opacity(0.6))
        }
        .padding(.vertical, KSpacing.xs)
        .contentShape(Rectangle())
    }
}

/// Transaktions-Zeile: Merchant-Icon, Beschreibung, Kategorie, Betrag.
struct KTransactionRow: View {
    let title: String
    var subtitle: String? = nil
    let amount: Double
    var pending: Bool = false
    private var glyph: String {
        let t = title.lowercased()
        if t.contains("gehalt") || t.contains("lohn") { return "arrow.down.circle.fill" }
        if t.contains("rewe") || t.contains("edeka") || t.contains("aldi") || t.contains("lidl") || t.contains("markt") { return "cart.fill" }
        if t.contains("amazon") || t.contains("paypal") { return "bag.fill" }
        if t.contains("dm") || t.contains("rossmann") || t.contains("drogerie") { return "cross.case.fill" }
        if t.contains("tank") || t.contains("shell") || t.contains("aral") { return "fuelpump.fill" }
        if t.contains("miete") || t.contains("strom") || t.contains("wohn") { return "house.fill" }
        return amount < 0 ? "arrow.up.right" : "arrow.down.left"
    }
    var body: some View {
        HStack(spacing: KSpacing.md) {
            Image(systemName: glyph)
                .font(.footnote).foregroundStyle(KColor.secondary)
                .frame(width: 30, height: 30)
                .background(KColor.surfaceSecondary, in: Circle())
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(KFont.row).foregroundStyle(KColor.primary).lineLimit(1)
                if pending {
                    Text("wird synchronisiert…").font(.caption2).foregroundStyle(KColor.warning)
                } else if let subtitle {
                    Text(subtitle).font(KFont.rowSub).foregroundStyle(KColor.secondary).lineLimit(1)
                }
            }
            Spacer(minLength: KSpacing.sm)
            Text(kEUR(amount, fraction: 2))
                .font(KFont.row.weight(.medium)).monospacedDigit()
                .foregroundStyle(amount > 0 ? KColor.positive : KColor.primary)
        }
        .padding(.vertical, KSpacing.xs)
    }
}

/// Kompakte Insight-Karte (Analyse-Hinweis / KI-Vorschlag).
struct KInsightCard: View {
    var icon: String = "sparkles"
    let title: String
    let message: String
    var actionTitle: String? = nil
    var action: (() -> Void)? = nil
    var body: some View {
        VStack(alignment: .leading, spacing: KSpacing.sm) {
            Label(title, systemImage: icon)
                .font(.footnote.weight(.semibold)).foregroundStyle(KColor.accent)
            Text(message).font(.callout).foregroundStyle(KColor.primary).fixedSize(horizontal: false, vertical: true)
            if let actionTitle, let action {
                Button(action: action) {
                    Text(actionTitle + " →").font(.footnote.weight(.medium)).foregroundStyle(KColor.accent)
                }
                .padding(.top, 2)
            }
        }
        .kCard()
    }
}

/// Hochwertiger Leerzustand mit optionaler Aktion.
struct KEmptyState: View {
    let icon: String
    let title: String
    let message: String
    var actionTitle: String? = nil
    var action: (() -> Void)? = nil
    var body: some View {
        VStack(spacing: KSpacing.sm) {
            Image(systemName: icon)
                .font(.system(size: 34, weight: .regular))
                .foregroundStyle(KColor.secondary.opacity(0.7))
            Text(title).font(.headline).foregroundStyle(KColor.primary)
            Text(message).font(.subheadline).foregroundStyle(KColor.secondary)
                .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .buttonStyle(KPrimaryButtonStyle())
                    .padding(.top, KSpacing.xs)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, KSpacing.xl)
        .padding(.horizontal, KSpacing.md)
    }
}

// MARK: Buttons

struct KPrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.callout.weight(.semibold))
            .foregroundStyle(.white)
            .padding(.vertical, 12).padding(.horizontal, KSpacing.lg)
            .background(KColor.accent, in: RoundedRectangle(cornerRadius: KRadius.sm, style: .continuous))
            .opacity(configuration.isPressed ? 0.85 : 1)
    }
}

struct KSecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.callout.weight(.semibold))
            .foregroundStyle(KColor.accent)
            .padding(.vertical, 12).padding(.horizontal, KSpacing.lg)
            .background(KColor.accent.opacity(0.12), in: RoundedRectangle(cornerRadius: KRadius.sm, style: .continuous))
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

struct KPrimaryButton: View {
    let title: String
    let action: () -> Void
    var body: some View { Button(title, action: action).buttonStyle(KPrimaryButtonStyle()) }
}

struct KSecondaryButton: View {
    let title: String
    let action: () -> Void
    var body: some View { Button(title, action: action).buttonStyle(KSecondaryButtonStyle()) }
}

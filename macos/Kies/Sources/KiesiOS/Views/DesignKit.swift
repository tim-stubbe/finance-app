import SwiftUI

// MARK: - Kies 2026 / Neon-inspired Light Design System
// Single appearance: light mode. The existing Alpine image remains a subtle
// Kies signature while the UI uses a bright Swiss/neon-inspired visual system.

enum KColor {
    static let background = Color(hex: 0xF7F9F4)
    static let surface = Color.white
    static let surfaceSoft = Color(hex: 0xEEF2EA)
    static let surfaceSecondary = surfaceSoft
    static let surfaceTint = Color(hex: 0xF1F7E8)
    static let primary = Color(hex: 0x111411)
    static let secondary = Color(hex: 0x68706A)
    static let tertiary = Color(hex: 0x98A09A)
    static let divider = Color(hex: 0xE2E7E0)
    static let accent = Color(hex: 0xB7F34A)
    static let accentStrong = Color(hex: 0x8BCF00)
    static let accentInk = Color(hex: 0x182000)
    static let cyan = Color(hex: 0x18C7D9)
    static let violet = Color(hex: 0x8D63FF)
    static let positive = Color(hex: 0x159447)
    static let negative = Color(hex: 0xE14B4B)
    static let warning = Color(hex: 0xC77A00)
    static let chartPalette: [Color] = [accentStrong, cyan, violet, Color(hex: 0xFF8A5B), Color(hex: 0x2DAF7A), Color(hex: 0xF0C44A), Color(hex: 0x6C7CFF)]
}

extension Color {
    fileprivate init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255, blue: Double(hex & 0xFF) / 255)
    }
}

enum KSpacing {
    static let xs: CGFloat = 4
    static let sm: CGFloat = 8
    static let md: CGFloat = 16
    static let lg: CGFloat = 24
    static let xl: CGFloat = 32
    static let xxl: CGFloat = 44
}

enum KRadius {
    static let sm: CGFloat = 12
    static let md: CGFloat = 18
    static let lg: CGFloat = 26
    static let pill: CGFloat = 999
}

enum KFont {
    static func number(_ size: CGFloat, weight: Font.Weight = .semibold) -> Font { .system(size: size, weight: weight, design: .rounded).monospacedDigit() }
    static let hero = number(42, weight: .bold)
    static let metric = number(25, weight: .bold)
    static let title = Font.system(size: 34, weight: .bold, design: .rounded)
    static let sectionH = Font.system(size: 17, weight: .bold, design: .rounded)
    static let row = Font.system(size: 16, weight: .medium)
    static let rowSub = Font.system(size: 13, weight: .regular)
}

func kEUR(_ value: Double, fraction: Int = 0) -> String { value.formatted(.currency(code: "EUR").precision(.fractionLength(fraction))) }

extension Font {
    static func kSerif(_ style: Font.TextStyle, weight: Font.Weight = .semibold) -> Font { .system(style, design: .rounded).weight(weight) }
}

enum KTheme {
    static let corner: CGFloat = KRadius.md
    static let gap: CGFloat = KSpacing.md
    static let background = KColor.background
    static let card = KColor.surface
    static let hairline = KColor.divider
    static let accent = KColor.accentStrong
    static let gold = KColor.accentStrong
    static let goldStrong = KColor.accentStrong
    static let goldDeep = KColor.accentStrong
    static let text = KColor.primary
    static let textSecondary = KColor.secondary
    static let muted = KColor.secondary
    static let positive = KColor.positive
    static let negative = KColor.negative
    static let chartPalette = KColor.chartPalette
}

struct NeonBackdrop: View {
    var opacity: Double = 0.18
    var body: some View {
        ZStack {
            KColor.background
            Image("AlpenBackground").resizable().scaledToFill().opacity(opacity)
            LinearGradient(colors: [KColor.background.opacity(0.76), KColor.background.opacity(0.90), KColor.background.opacity(0.98)], startPoint: .top, endPoint: .bottom)
        }
        .ignoresSafeArea()
    }
}

struct AlpenBackdrop: View { var body: some View { NeonBackdrop(opacity: 0.18) } }

struct KScreen<Content: View>: View {
    var spacing: CGFloat = KSpacing.lg
    @ViewBuilder var content: Content
    var body: some View {
        ZStack {
            NeonBackdrop(opacity: 0.12)
            ScrollView {
                VStack(alignment: .leading, spacing: spacing) { content }
                    .padding(.horizontal, KSpacing.md).padding(.top, KSpacing.sm).padding(.bottom, 110)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }.scrollDismissesKeyboard(.interactively)
        }
    }
}

struct KSurface<Content: View>: View {
    let padding: CGFloat
    @ViewBuilder var content: Content
    init(_ padding: CGFloat = KSpacing.md, @ViewBuilder content: () -> Content) { self.padding = padding; self.content = content() }
    var body: some View { content.padding(padding).frame(maxWidth: .infinity, alignment: .leading).background(KColor.surface.opacity(0.96), in: RoundedRectangle(cornerRadius: KRadius.md, style: .continuous)).overlay(RoundedRectangle(cornerRadius: KRadius.md, style: .continuous).stroke(KColor.divider, lineWidth: 1)).shadow(color: Color.black.opacity(0.045), radius: 18, x: 0, y: 8) }
}

extension View {
    func kCard(_ padding: CGFloat = KSpacing.md) -> some View { self.padding(padding).frame(maxWidth: .infinity, alignment: .leading).background(KColor.surface.opacity(0.96), in: RoundedRectangle(cornerRadius: KRadius.md, style: .continuous)).overlay(RoundedRectangle(cornerRadius: KRadius.md, style: .continuous).stroke(KColor.divider, lineWidth: 1)).shadow(color: Color.black.opacity(0.045), radius: 18, x: 0, y: 8) }
    func kListChrome() -> some View { self.scrollContentBackground(.hidden).background(NeonBackdrop(opacity: 0.10)) }
    func kListRow() -> some View { self.listRowBackground(KColor.surface.opacity(0.97)).listRowSeparatorTint(KColor.divider) }
}

struct KKicker: View { let text: String; var body: some View { Text(text.uppercased()).font(.system(size: 11, weight: .bold)).tracking(1.0).foregroundStyle(KColor.secondary) } }

struct KSectionHeader: View {
    let title: String
    var action: (title: String, run: () -> Void)? = nil
    var body: some View { HStack(alignment: .firstTextBaseline) { Text(title).font(KFont.sectionH).foregroundStyle(KColor.primary); Spacer(); if let action { Button(action.title, action: action.run).font(.footnote.weight(.bold)).foregroundStyle(KColor.accentStrong) } } }
}

struct KStatTile: View {
    let label: String; let value: String; var tint: Color = KColor.primary; var caption: String? = nil
    var body: some View { VStack(alignment: .leading, spacing: KSpacing.xs) { Text(label).font(.footnote.weight(.medium)).foregroundStyle(KColor.secondary); Text(value).font(KFont.metric).foregroundStyle(tint).lineLimit(1).minimumScaleFactor(0.5); if let caption { Text(caption).font(.caption2).foregroundStyle(KColor.secondary) } }.frame(maxWidth: .infinity, alignment: .leading).kCard(KSpacing.md) }
}

typealias KMetricCard = KStatTile

struct KSection<Content: View>: View {
    let title: String; var systemImage: String? = nil; var accessory: AnyView? = nil
    @ViewBuilder var content: Content
    var body: some View { VStack(alignment: .leading, spacing: KSpacing.md) { HStack(spacing: KSpacing.sm) { if let systemImage { Image(systemName: systemImage).font(.footnote.weight(.bold)).foregroundStyle(KColor.accentStrong) }; Text(title).font(KFont.sectionH).foregroundStyle(KColor.primary); Spacer(); if let accessory { accessory } }; content }.kCard() }
}

struct KRow: View {
    let title: String; var subtitle: String? = nil; var trailing: String? = nil; var trailingTint: Color = KColor.primary
    var body: some View { HStack(spacing: KSpacing.md) { VStack(alignment: .leading, spacing: 2) { Text(title).font(KFont.row).foregroundStyle(KColor.primary); if let subtitle { Text(subtitle).font(KFont.rowSub).foregroundStyle(KColor.secondary) } }; Spacer(minLength: KSpacing.sm); if let trailing { Text(trailing).font(KFont.row.weight(.semibold)).foregroundStyle(trailingTint).monospacedDigit() } }.padding(.vertical, KSpacing.xs) }
}

struct KAccountRow: View {
    let icon: String; let name: String; let subtitle: String; let amount: Double
    var body: some View { HStack(spacing: KSpacing.md) { Image(systemName: icon).font(.callout.weight(.bold)).foregroundStyle(KColor.accentInk).frame(width: 38, height: 38).background(KColor.accent, in: RoundedRectangle(cornerRadius: KRadius.sm, style: .continuous)); VStack(alignment: .leading, spacing: 2) { Text(name).font(KFont.row).foregroundStyle(KColor.primary); Text(subtitle).font(KFont.rowSub).foregroundStyle(KColor.secondary) }; Spacer(minLength: KSpacing.sm); Text(kEUR(amount, fraction: 2)).font(.system(size: 16, weight: .bold, design: .rounded)).monospacedDigit().foregroundStyle(amount < 0 ? KColor.negative : KColor.primary); Image(systemName: "chevron.right").font(.caption.weight(.bold)).foregroundStyle(KColor.tertiary) }.padding(.vertical, KSpacing.xs).contentShape(Rectangle()) }
}

struct KTransactionRow: View {
    let title: String; var subtitle: String? = nil; let amount: Double; var pending: Bool = false
    private var glyph: String { let t = title.lowercased(); if t.contains("gehalt") || t.contains("lohn") { return "arrow.down.left" }; if t.contains("rewe") || t.contains("edeka") || t.contains("aldi") || t.contains("lidl") || t.contains("markt") { return "cart.fill" }; if t.contains("amazon") || t.contains("paypal") { return "bag.fill" }; if t.contains("dm") || t.contains("rossmann") || t.contains("drogerie") { return "cross.case.fill" }; if t.contains("tank") || t.contains("shell") || t.contains("aral") || t.contains("oil") { return "fuelpump.fill" }; if t.contains("miete") || t.contains("strom") || t.contains("wohn") { return "house.fill" }; return amount < 0 ? "arrow.up.right" : "arrow.down.left" }
    var body: some View { HStack(spacing: KSpacing.md) { Image(systemName: glyph).font(.footnote.weight(.bold)).foregroundStyle(amount > 0 ? KColor.positive : KColor.primary).frame(width: 38, height: 38).background(amount > 0 ? KColor.surfaceTint : KColor.surfaceSoft, in: Circle()); VStack(alignment: .leading, spacing: 2) { Text(title).font(KFont.row).foregroundStyle(KColor.primary).lineLimit(1); if pending { Text("Wird synchronisiert…").font(.caption2).foregroundStyle(KColor.warning) } else if let subtitle { Text(subtitle).font(KFont.rowSub).foregroundStyle(KColor.secondary).lineLimit(1) } }; Spacer(minLength: KSpacing.sm); Text(kEUR(amount, fraction: 2)).font(.system(size: 16, weight: .bold, design: .rounded)).monospacedDigit().foregroundStyle(amount > 0 ? KColor.positive : KColor.primary) }.padding(.vertical, KSpacing.xs) }
}

struct KInsightCard: View {
    var icon: String = "sparkles"; let title: String; let message: String; var actionTitle: String? = nil; var action: (() -> Void)? = nil
    var body: some View { HStack(alignment: .top, spacing: KSpacing.md) { Image(systemName: icon).font(.headline.weight(.bold)).foregroundStyle(KColor.accentInk).frame(width: 42, height: 42).background(KColor.accent, in: Circle()); VStack(alignment: .leading, spacing: 5) { Text(title).font(.footnote.weight(.bold)).foregroundStyle(KColor.primary); Text(message).font(.callout).foregroundStyle(KColor.primary).fixedSize(horizontal: false, vertical: true); if let actionTitle, let action { Button(actionTitle + " →", action: action).font(.footnote.weight(.bold)).foregroundStyle(KColor.accentStrong) } } }.kCard() }
}

struct KEmptyState: View {
    let icon: String; let title: String; let message: String; var actionTitle: String? = nil; var action: (() -> Void)? = nil
    var body: some View { VStack(spacing: KSpacing.md) { Image(systemName: icon).font(.system(size: 34, weight: .medium)).foregroundStyle(KColor.accentStrong).frame(width: 62, height: 62).background(KColor.accent, in: Circle()); Text(title).font(.headline.weight(.bold)).foregroundStyle(KColor.primary); Text(message).font(.callout).foregroundStyle(KColor.secondary).multilineTextAlignment(.center); if let actionTitle, let action { Button(actionTitle, action: action).font(.footnote.weight(.bold)).foregroundStyle(KColor.accentInk).padding(.horizontal, 18).padding(.vertical, 11).background(KColor.accent, in: Capsule()) } }.frame(maxWidth: .infinity).kCard(KSpacing.lg) }
}

struct NeonPill: View {
    let title: String; var active: Bool = false
    var body: some View { Text(title).font(.caption.weight(.bold)).foregroundStyle(active ? KColor.accentInk : KColor.primary).padding(.horizontal, 13).padding(.vertical, 8).background(active ? KColor.accent : KColor.surface, in: Capsule()).overlay(Capsule().stroke(active ? KColor.accent : KColor.divider, lineWidth: 1)) }
}

import SwiftUI
import KiesCore

/// Swiss/neon-inspired feature hub. Calm, bright and deliberately not a card grid.
struct MoreView: View {
    @ObservedObject private var engine = SyncEngine.shared

    var body: some View {
        KScreen(spacing: KSpacing.lg) {
            header
            if !engine.conflicts.isEmpty { conflictBanner }
            financeSection
            lifeSection
            toolsSection
            SyncStatusFooter().font(.caption).foregroundStyle(KColor.secondary)
        }
        .toolbar { SyncStatusToolbarItem() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 5) {
            KKicker(text: "Kies")
            Text("Mehr").font(KFont.title).foregroundStyle(KColor.primary)
            Text("Alles, was über dein tägliches Banking hinausgeht.").font(.subheadline).foregroundStyle(KColor.secondary)
        }
    }

    private var conflictBanner: some View {
        NavigationLink { ConflictsView() } label: {
            HStack(spacing: KSpacing.md) {
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(KColor.warning)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Sync-Konflikte").font(.footnote.weight(.bold)).foregroundStyle(KColor.primary)
                    Text("\(engine.conflicts.count) Konflikt(e) benötigen Aufmerksamkeit.").font(.caption).foregroundStyle(KColor.secondary)
                }
                Spacer()
                Image(systemName: "chevron.right").foregroundStyle(KColor.tertiary)
            }
            .kCard(KSpacing.md)
        }.buttonStyle(.plain)
    }

    private var financeSection: some View {
        featureGroup("Finance", icon: "chart.pie.fill", color: KColor.accent) {
            NavigationLink { InvestmentsView() } label: { feature("Investments", "Portfolio und Positionen", "chart.line.uptrend.xyaxis") }
            NavigationLink { GoalsView() } label: { feature("Ziele", "Sparen mit einem klaren Ziel", "target") }
            NavigationLink { CategoriesView() } label: { feature("Kategorien", "Deine Ausgaben strukturieren", "tag") }
        }
    }

    private var lifeSection: some View {
        featureGroup("Life", icon: "heart.fill", color: KColor.cyan) {
            NavigationLink { LifeAreasView() } label: { feature("Leben", "Persönliche Bereiche und Check-ins", "heart.text.square") }
            if HealthKitSync.shared.isAvailable { NavigationLink { HealthView() } label: { feature("Gesundheit", "Apple Health", "heart.circle") } }
            NavigationLink { WishlistView() } label: { feature("Wünsche", "Was als Nächstes kommen soll", "sparkles") }
        }
    }

    private var toolsSection: some View {
        featureGroup("Tools", icon: "square.grid.2x2.fill", color: KColor.violet) {
            NavigationLink { SearchView() } label: { feature("Suche", "Alles in Kies sofort finden", "magnifyingglass") }
            NavigationLink { SettingsView() } label: { feature("Einstellungen", "Sync, Sicherheit und App", "gearshape") }
        }
    }

    private func featureGroup<Content: View>(_ title: String, icon: String, color: Color, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: KSpacing.sm) {
            HStack(spacing: 8) {
                Image(systemName: icon).font(.caption.weight(.bold)).foregroundStyle(KColor.primary)
                Text(title).font(.footnote.weight(.bold)).foregroundStyle(KColor.secondary)
            }
            VStack(spacing: 0) { content() }
                .padding(.horizontal, KSpacing.md)
                .background(KColor.surface.opacity(0.96), in: RoundedRectangle(cornerRadius: KRadius.md, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: KRadius.md, style: .continuous).stroke(KColor.divider, lineWidth: 1))
        }
    }

    private func feature(_ title: String, _ subtitle: String, _ icon: String) -> some View {
        HStack(spacing: KSpacing.md) {
            Image(systemName: icon).font(.callout.weight(.bold)).foregroundStyle(KColor.primary)
                .frame(width: 38, height: 38).background(KColor.surfaceSoft, in: RoundedRectangle(cornerRadius: 11, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.body.weight(.bold)).foregroundStyle(KColor.primary)
                Text(subtitle).font(.caption).foregroundStyle(KColor.secondary).lineLimit(1)
            }
            Spacer()
            Image(systemName: "chevron.right").font(.caption.weight(.bold)).foregroundStyle(KColor.tertiary)
        }
        .padding(.vertical, 13)
        .contentShape(Rectangle())
    }
}

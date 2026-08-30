import SwiftUI
import KiesCore

/// "Mehr"-Tab: native, gruppierte iOS-Liste (Profil / Finance / Life / Tools)
/// statt Karten-Raster. Trägt die Nebenschauplätze, die keinen eigenen Tab
/// haben (Ziele, Leben, Wünsche, Investments, Kategorien, Suche, Einstellungen).
struct MoreView: View {
    @ObservedObject private var engine = SyncEngine.shared

    var body: some View {
        List {
            if !engine.conflicts.isEmpty {
                Section {
                    NavigationLink { ConflictsView() } label: {
                        Label("\(engine.conflicts.count) Sync-Konflikt(e)", systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(KColor.warning)
                    }
                }
                .listRowBackground(KColor.surface)
            }

            Section("Profil") {
                HStack(spacing: KSpacing.md) {
                    Image(systemName: "person.crop.circle.fill")
                        .font(.system(size: 34)).foregroundStyle(KColor.secondary)
                    VStack(alignment: .leading, spacing: 1) {
                        Text("Privater Bereich").font(.body.weight(.medium)).foregroundStyle(KColor.primary)
                        Text("Kies · lokal & synchronisiert").font(.footnote).foregroundStyle(KColor.secondary)
                    }
                }
                .padding(.vertical, KSpacing.xs)
            }
            .listRowBackground(KColor.surface)

            Section("Finance") {
                row("Investments", "chart.line.uptrend.xyaxis") { InvestmentsView() }
                row("Ziele", "target") { GoalsView() }
                row("Kategorien", "tag") { CategoriesView() }
            }
            .listRowBackground(KColor.surface)

            Section("Life") {
                row("Leben", "heart.text.square") { LifeAreasView() }
                if HealthKitSync.shared.isAvailable {
                    row("Gesundheit", "heart.circle") { HealthView() }
                }
                row("Wünsche", "sparkles") { WishlistView() }
            }
            .listRowBackground(KColor.surface)

            Section("Tools") {
                row("Suche", "magnifyingglass") { SearchView() }
                row("Einstellungen", "gearshape") { SettingsView() }
            }
            .listRowBackground(KColor.surface)

            Section {
                SyncStatusFooter()
            }
            .listRowBackground(Color.clear)
        }
        .listStyle(.insetGrouped)
        .kListChrome()
        .navigationTitle("Mehr")
        .toolbar { SyncStatusToolbarItem() }
    }

    @ViewBuilder
    private func row<D: View>(_ title: String, _ icon: String, @ViewBuilder dest: @escaping () -> D) -> some View {
        NavigationLink { dest() } label: {
            Label {
                Text(title).foregroundStyle(KColor.primary)
            } icon: {
                Image(systemName: icon).foregroundStyle(KColor.accent)
            }
        }
    }
}

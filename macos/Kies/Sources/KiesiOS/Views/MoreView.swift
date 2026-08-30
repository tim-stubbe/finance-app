import SwiftUI
import KiesCore

/// Secondary features use native grouped iOS navigation instead of a card grid.
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
            }

            Section("Finance") {
                NavigationLink { PremiumInvestmentsView() } label: { row("Investments", "chart.line.uptrend.xyaxis") }
                NavigationLink { GoalsView() } label: { row("Ziele", "target") }
                NavigationLink { CategoriesView() } label: { row("Kategorien", "tag") }
            }

            Section("Life") {
                NavigationLink { LifeAreasView() } label: { row("Leben", "heart.text.square") }
                if HealthKitSync.shared.isAvailable {
                    NavigationLink { HealthView() } label: { row("Gesundheit", "heart.circle") }
                }
                NavigationLink { WishlistView() } label: { row("Wünsche", "sparkles") }
            }

            Section("Tools") {
                NavigationLink { SearchView() } label: { row("Suche", "magnifyingglass") }
                NavigationLink { SettingsView() } label: { row("Einstellungen", "gearshape") }
            }

            Section {
                SyncStatusFooter()
            }
        }
        .listStyle(.insetGrouped)
        .scrollContentBackground(.hidden)
        .background(KColor.background)
        .navigationTitle("Mehr")
        .toolbar { SyncStatusToolbarItem() }
    }

    private func row(_ title: String, _ icon: String) -> some View {
        Label {
            Text(title).foregroundStyle(KColor.primary)
        } icon: {
            Image(systemName: icon).foregroundStyle(KColor.accent)
        }
    }
}

import SwiftUI
import KiesCore

/// "Mehr"-Tab: statt zehn Tabs (die iOS sonst in ein haessliches System-
/// "Mehr"-Menue kippt) tragen fuenf Tabs die Kern-Screens, der Rest lebt
/// hier als Karten-Raster mit NavigationLinks. Reihenfolge = Haeufigkeit.
struct MoreView: View {
    @ObservedObject private var engine = SyncEngine.shared

    private struct Entry: Identifiable {
        let id = UUID()
        let title: String
        let icon: String
        let tint: Color
        let dest: AnyView
    }

    private var entries: [Entry] {
        [
            Entry(title: "Ziele", icon: "target", tint: .pink, dest: AnyView(GoalsView())),
            Entry(title: "Leben", icon: "heart.text.square", tint: .red, dest: AnyView(LifeAreasView())),
            Entry(title: "Wünsche", icon: "sparkles", tint: .purple, dest: AnyView(WishlistView())),
            Entry(title: "Investments", icon: "chart.line.uptrend.xyaxis", tint: .green, dest: AnyView(InvestmentsView())),
            Entry(title: "Kategorien", icon: "tag", tint: .orange, dest: AnyView(CategoriesView())),
            Entry(title: "Suche", icon: "magnifyingglass", tint: .blue, dest: AnyView(SearchView())),
        ]
    }

    private let columns = [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)]

    var body: some View {
        KScreen {
            if !engine.conflicts.isEmpty {
                NavigationLink { ConflictsView() } label: {
                    HStack {
                        Label("\(engine.conflicts.count) Sync-Konflikt(e)", systemImage: "exclamationmark.triangle.fill")
                            .font(.subheadline.weight(.semibold))
                        Spacer()
                        Image(systemName: "chevron.right").font(.caption)
                    }
                    .foregroundStyle(.orange)
                    .kCard()
                }
                .buttonStyle(.plain)
            }

            LazyVGrid(columns: columns, spacing: 12) {
                ForEach(entries) { e in
                    NavigationLink { e.dest } label: { tile(e) }
                        .buttonStyle(.plain)
                }
            }

            NavigationLink { SettingsView() } label: {
                HStack(spacing: 12) {
                    Image(systemName: "gearshape.fill").foregroundStyle(.secondary).frame(width: 26)
                    Text("Einstellungen").font(.callout.weight(.medium))
                    Spacer()
                    Image(systemName: "chevron.right").font(.caption).foregroundStyle(.tertiary)
                }
                .kCard()
            }
            .buttonStyle(.plain)

            SyncStatusFooter().padding(.horizontal, 4)
        }
        .navigationTitle("Mehr")
        .toolbar { SyncStatusToolbarItem() }
    }

    private func tile(_ e: Entry) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Image(systemName: e.icon)
                .font(.title2)
                .foregroundStyle(e.tint)
                .frame(width: 44, height: 44)
                .background(e.tint.opacity(0.14), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            Text(e.title).font(.callout.weight(.semibold))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .kCard()
    }
}

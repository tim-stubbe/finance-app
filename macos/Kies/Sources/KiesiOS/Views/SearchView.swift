import SwiftUI
import KiesCore
import GRDB

/// Native, rein lokale Suche über die synchronisierten Daten (GRDB, kein
/// Netzwerk-Aufruf nötig) - siehe Queries.globalSearch für die eigentliche
/// Abfrage. Bewusst ein eigener Tab statt `.searchable` an mehreren Stellen:
/// so bleibt die Suche IMMER erreichbar, unabhängig davon welcher Tab gerade
/// offen ist, und funktioniert genauso offline wie der Rest der App.
///
/// Ergebnis antippen wechselt in den passenden Tab (siehe TabRouter) - die
/// App hat aktuell keine Detail-Screens für einzelne Zeilen (nur Listen),
/// "richtigen Tab öffnen" ist der bestehende Detailgrad überall sonst.
struct SearchView: View {
    @ObservedObject private var query = Box("")
    @ObservedObject private var results = Box<[Queries.SearchResult]>([])
    @ObservedObject private var router = TabRouter.shared

    var body: some View {
        List {
            if query.value.trimmingCharacters(in: .whitespaces).count < 2 {
                ContentUnavailableView(
                    "Suche in Kies", systemImage: "magnifyingglass",
                    description: Text("Mindestens 2 Zeichen - durchsucht Konten, Buchungen, Todos, Ziele, Termine, Wünsche, Lebensbereiche, Kategorien und Investments.")
                )
            } else if results.value.isEmpty {
                ContentUnavailableView.search(text: query.value)
            } else {
                ForEach(Dictionary(grouping: results.value, by: \.kind).sorted(by: { $0.key < $1.key }), id: \.key) { kind, items in
                    Section(kind) {
                        ForEach(items) { item in
                            Button {
                                if let tab = AppTab(rawValue: item.tabKey) {
                                    router.jump(to: tab)
                                }
                            } label: {
                                HStack {
                                    Image(systemName: item.icon)
                                        .foregroundStyle(.secondary)
                                        .frame(width: 24)
                                    VStack(alignment: .leading) {
                                        Text(item.title).foregroundStyle(.primary)
                                        if let subtitle = item.subtitle, !subtitle.isEmpty {
                                            Text(subtitle).font(.caption).foregroundStyle(.secondary)
                                        }
                                    }
                                    Spacer()
                                    Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.tertiary)
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
        }
        .navigationTitle("Suche")
        .searchable(text: query.binding, prompt: "Suchen…")
        .onChange(of: query.value) { _, _ in search() }
    }

    private func search() {
        let q = query.value
        results.value = (try? AppDatabase.shared.read { db in
            try Queries.globalSearch(db, query: q)
        }) ?? []
    }
}

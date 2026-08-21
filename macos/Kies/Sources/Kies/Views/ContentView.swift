import SwiftUI
import KiesCore

struct ContentView: View {
    @ObservedObject var pairing = PairingStore.shared
    @ObservedObject var engine = SyncEngine.shared
    @ObservedObject private var selection = Box<String?>("accounts")

    var body: some View {
        if !pairing.isPaired {
            PairingView()
        } else {
            NavigationSplitView {
                List(selection: selection.binding) {
                    Label("Konten", systemImage: "banknote").tag("accounts" as String?)
                    Label("Buchungen", systemImage: "list.bullet.rectangle").tag("transactions" as String?)
                    Label("Todos", systemImage: "checklist").tag("todos" as String?)
                    Label("Ziele", systemImage: "target").tag("goals" as String?)
                    Label("Leben", systemImage: "heart.text.square").tag("life" as String?)
                }
                .navigationTitle("Kies")
                .safeAreaInset(edge: .bottom) {
                    VStack(alignment: .leading, spacing: 4) {
                        if let last = engine.lastSyncedAt {
                            Text("Zuletzt synchronisiert: \(last.formatted(date: .omitted, time: .shortened))")
                                .font(.caption2).foregroundStyle(.secondary)
                        }
                        if let error = engine.lastError {
                            Text("Fehler: \(error)").font(.caption2).foregroundStyle(.red).lineLimit(2)
                        }
                    }
                    .padding(8)
                }
            } detail: {
                switch selection.value {
                case "accounts": AccountsListView()
                case "transactions": TransactionsListView()
                case "todos": TodosListView()
                case "goals": GoalsListView()
                case "life": LifeAreasListView()
                default: Text("Wähle einen Bereich")
                }
            }
            .task { await engine.run() }
        }
    }
}

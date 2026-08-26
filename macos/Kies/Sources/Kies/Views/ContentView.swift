import SwiftUI
import KiesCore

struct ContentView: View {
    @ObservedObject var pairing = PairingStore.shared
    @ObservedObject var engine = SyncEngine.shared
    @ObservedObject var lock = AppLockStore.shared
    @ObservedObject private var selection = Box<String?>("today")
    @State private var showQuickCapture = false
    @ObservedObject private var pendingOutboxCount = Box(0)

    var body: some View {
        if !pairing.isPaired {
            PairingView()
        } else {
            ZStack {
                NavigationSplitView {
                    List(selection: selection.binding) {
                        Label("Heute", systemImage: "sun.max").tag("today" as String?)
                        Label("Konten", systemImage: "banknote").tag("accounts" as String?)
                        Label("Buchungen", systemImage: "list.bullet.rectangle").tag("transactions" as String?)
                        Label("Todos", systemImage: "checklist").tag("todos" as String?)
                        Label("Ziele", systemImage: "target").tag("goals" as String?)
                        Label("Leben", systemImage: "heart.text.square").tag("life" as String?)
                        Label("Wünsche", systemImage: "heart").tag("wishlist" as String?)
                        Label("Kategorien", systemImage: "tag").tag("categories" as String?)
                        Label("Investments", systemImage: "chart.line.uptrend.xyaxis").tag("investments" as String?)
                        if !engine.conflicts.isEmpty {
                            Label("\(engine.conflicts.count) Konflikte", systemImage: "exclamationmark.triangle.fill")
                                .foregroundStyle(.orange)
                                .tag("conflicts" as String?)
                        }
                    }
                    .navigationTitle("Kies")
                    .toolbar {
                        ToolbarItem {
                            Button {
                                showQuickCapture = true
                            } label: {
                                Label("Erfassen", systemImage: "plus")
                            }
                        }
                    }
                    .safeAreaInset(edge: .bottom) {
                        // Klarerer Sync-Status als vorher (nur Zeitpunkt+Fehler):
                        // zeigt jetzt zusätzlich, ob noch unversendete lokale
                        // Änderungen warten - dieselbe Kennzahl wie in der
                        // iOS-App (SyncStatusBar.swift).
                        VStack(alignment: .leading, spacing: 4) {
                            if let last = engine.lastSyncedAt {
                                Text("Zuletzt synchronisiert: \(last.formatted(date: .omitted, time: .shortened))")
                                    .font(.caption2).foregroundStyle(.secondary)
                            }
                            if pendingOutboxCount.value > 0 {
                                Text("\(pendingOutboxCount.value) Änderung(en) warten auf Upload")
                                    .font(.caption2).foregroundStyle(.orange)
                            }
                            if let error = engine.lastError {
                                Text("Fehler: \(error)").font(.caption2).foregroundStyle(.red).lineLimit(2)
                            }
                        }
                        .padding(8)
                    }
                } detail: {
                    switch selection.value {
                    case "today": TodayListView()
                    case "accounts": AccountsListView()
                    case "transactions": TransactionsListView()
                    case "todos": TodosListView()
                    case "goals": GoalsListView()
                    case "life": LifeAreasListView()
                    case "wishlist": WishlistListView()
                    case "categories": CategoriesListView()
                    case "investments": InvestmentsListView()
                    case "conflicts": ConflictsListView()
                    default: Text("Wähle einen Bereich")
                    }
                }
                .task {
                    await engine.run()
                    lock.lockIfEnabled()
                }
                .onChange(of: engine.lastSyncedAt) { _, _ in
                    Task { pendingOutboxCount.value = await engine.pendingOutboxCount() }
                }
                .sheet(isPresented: $showQuickCapture) {
                    QuickCaptureSheet()
                }

                if lock.isLocked {
                    AppLockView()
                }
            }
        }
    }
}

import SwiftUI
import KiesCore

/// Vier Bereiche für die erste iOS-Version (siehe KiesiOSApp.swift-Kopf-
/// kommentar) - TabView statt der NavigationSplitView der macOS-App, das ist
/// auf dem iPhone der übliche Ort für eine feste, kleine Anzahl Bereiche.
struct RootTabView: View {
    var body: some View {
        TabView {
            NavigationStack { TodayView() }
                .tabItem { Label("Heute", systemImage: "sun.max") }
            NavigationStack { AccountsView() }
                .tabItem { Label("Konten", systemImage: "banknote") }
            NavigationStack { TransactionsView() }
                .tabItem { Label("Buchungen", systemImage: "list.bullet.rectangle") }
            NavigationStack { TodosView() }
                .tabItem { Label("Todos", systemImage: "checklist") }
        }
    }
}

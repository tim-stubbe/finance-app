import SwiftUI
import KiesCore

/// Bereiche der iOS-App (siehe KiesiOSApp.swift-Kopfkommentar) - TabView statt
/// der NavigationSplitView der macOS-App, das ist auf dem iPhone der übliche
/// Ort für eine feste, kleine Anzahl Bereiche. Ziele/Leben kamen später dazu
/// (iOS ab jetzt mehr als reines MVP) - bewusst KEINE Feature-Parität mit der
/// Web-App, siehe die jeweiligen View-Kommentare für das, was fehlt.
struct RootTabView: View {
    @State private var showQuickCapture = false
    @ObservedObject private var router = TabRouter.shared

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            // Bewusst nur fuenf Tabs - ab sechs kippt iOS sie in ein eigenes,
            // ungestyltes "Mehr"-Menue. Die Nebenschauplaetze (Ziele, Leben,
            // Wuensche, Investments, Kategorien, Suche) liegen im MoreView-
            // Kartenraster.
            TabView(selection: $router.selection) {
                NavigationStack { TodayView() }
                    .tabItem { Label("Heute", systemImage: "sun.max") }
                    .tag(AppTab.today)
                NavigationStack { AccountsView() }
                    .tabItem { Label("Konten", systemImage: "banknote") }
                    .tag(AppTab.accounts)
                NavigationStack { TransactionsView() }
                    .tabItem { Label("Buchungen", systemImage: "list.bullet.rectangle") }
                    .tag(AppTab.transactions)
                NavigationStack { TodosView() }
                    .tabItem { Label("Todos", systemImage: "checklist") }
                    .tag(AppTab.todos)
                NavigationStack { MoreView() }
                    .tabItem { Label("Mehr", systemImage: "square.grid.2x2") }
                    .tag(AppTab.more)
            }

            Button {
                showQuickCapture = true
            } label: {
                Image(systemName: "plus")
                    .font(.title2.bold())
                    .foregroundStyle(.white)
                    .frame(width: 56, height: 56)
                    .background(Circle().fill(Color.accentColor))
                    .shadow(radius: 4)
            }
            .padding(.trailing, 20)
            .padding(.bottom, 70)  // über der Tab-Leiste schweben lassen
        }
        .sheet(isPresented: $showQuickCapture) {
            QuickCaptureView()
        }
    }
}

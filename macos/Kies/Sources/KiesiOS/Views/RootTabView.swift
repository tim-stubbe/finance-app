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
                NavigationStack { GoalsView() }
                    .tabItem { Label("Ziele", systemImage: "target") }
                    .tag(AppTab.goals)
                NavigationStack { LifeAreasView() }
                    .tabItem { Label("Leben", systemImage: "heart.text.square") }
                    .tag(AppTab.life)
                NavigationStack { WishlistView() }
                    .tabItem { Label("Wünsche", systemImage: "heart") }
                    .tag(AppTab.wishlist)
                NavigationStack { CategoriesView() }
                    .tabItem { Label("Kategorien", systemImage: "tag") }
                    .tag(AppTab.categories)
                NavigationStack { InvestmentsView() }
                    .tabItem { Label("Investments", systemImage: "chart.line.uptrend.xyaxis") }
                    .tag(AppTab.investments)
                NavigationStack { SearchView() }
                    .tabItem { Label("Suche", systemImage: "magnifyingglass") }
                    .tag(AppTab.search)
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

import SwiftUI
import KiesCore

/// Bereiche der iOS-App (siehe KiesiOSApp.swift-Kopfkommentar) - TabView statt
/// der NavigationSplitView der macOS-App, das ist auf dem iPhone der übliche
/// Ort für eine feste, kleine Anzahl Bereiche. Ziele/Leben kamen später dazu
/// (iOS ab jetzt mehr als reines MVP) - bewusst KEINE Feature-Parität mit der
/// Web-App, siehe die jeweiligen View-Kommentare für das, was fehlt.
struct RootTabView: View {
    @State private var showQuickCapture = false

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            TabView {
                NavigationStack { TodayView() }
                    .tabItem { Label("Heute", systemImage: "sun.max") }
                NavigationStack { AccountsView() }
                    .tabItem { Label("Konten", systemImage: "banknote") }
                NavigationStack { TransactionsView() }
                    .tabItem { Label("Buchungen", systemImage: "list.bullet.rectangle") }
                NavigationStack { TodosView() }
                    .tabItem { Label("Todos", systemImage: "checklist") }
                NavigationStack { GoalsView() }
                    .tabItem { Label("Ziele", systemImage: "target") }
                NavigationStack { LifeAreasView() }
                    .tabItem { Label("Leben", systemImage: "heart.text.square") }
                NavigationStack { WishlistView() }
                    .tabItem { Label("Wünsche", systemImage: "heart") }
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

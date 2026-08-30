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
                    .tabItem { Label("Übersicht", systemImage: "square.grid.2x2") }
                    .tag(AppTab.today)
                NavigationStack { AccountsView() }
                    .tabItem { Label("Konten", systemImage: "creditcard") }
                    .tag(AppTab.accounts)
                NavigationStack { TransactionsView() }
                    .tabItem { Label("Transaktionen", systemImage: "list.bullet") }
                    .tag(AppTab.transactions)
                NavigationStack { TodosView() }
                    .tabItem { Label("Aufgaben", systemImage: "checklist") }
                    .tag(AppTab.todos)
                NavigationStack { MoreView() }
                    .tabItem { Label("Mehr", systemImage: "ellipsis.circle") }
                    .tag(AppTab.more)
            }

            Button {
                showQuickCapture = true
            } label: {
                Image(systemName: "plus")
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 56, height: 56)
                    .background(Circle().fill(KColor.accent))
                    .shadow(color: KColor.accent.opacity(0.4), radius: 10, x: 0, y: 5)
            }
            .accessibilityLabel("Schnell erfassen")
            .padding(.trailing, KSpacing.lg)
            .padding(.bottom, 70)  // über der Tab-Leiste schweben lassen
        }
        .sheet(isPresented: $showQuickCapture) {
            QuickCaptureView()
        }
    }
}

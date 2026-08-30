import SwiftUI
import KiesCore

struct RootTabView: View {
    @State private var showQuickCapture = false
    @ObservedObject private var router = TabRouter.shared

    var body: some View {
        ZStack(alignment: .bottom) {
            TabView(selection: $router.selection) {
                NavigationStack {
                    TodayView()
                        .navigationBarTitleDisplayMode(.inline)
                }
                .tabItem { Label("Übersicht", systemImage: "sparkles") }
                .tag(AppTab.today)

                NavigationStack { AccountsView() }
                    .tabItem { Label("Konten", systemImage: "creditcard") }
                    .tag(AppTab.accounts)

                NavigationStack { TransactionsView() }
                    .tabItem { Label("Buchungen", systemImage: "arrow.left.arrow.right") }
                    .tag(AppTab.transactions)

                NavigationStack { TodosView() }
                    .tabItem { Label("Aufgaben", systemImage: "checklist") }
                    .tag(AppTab.todos)

                NavigationStack { MoreView() }
                    .tabItem { Label("Mehr", systemImage: "square.grid.2x2") }
                    .tag(AppTab.more)
            }
            .tint(KColor.accentStrong)

            // Floating quick action: the single bold neon interaction in the shell.
            Button {
                showQuickCapture = true
            } label: {
                ZStack {
                    Circle()
                        .fill(KColor.accent)
                        .frame(width: 60, height: 60)
                    Image(systemName: "plus")
                        .font(.system(size: 23, weight: .bold))
                        .foregroundStyle(KColor.accentInk)
                }
                .shadow(color: KColor.accentStrong.opacity(0.25), radius: 16, x: 0, y: 8)
            }
            .accessibilityLabel("Schnell erfassen")
            .padding(.bottom, 54)
        }
        .sheet(isPresented: $showQuickCapture) {
            QuickCaptureView()
        }
    }
}

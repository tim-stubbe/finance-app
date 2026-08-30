import SwiftUI
import KiesCore

struct RootTabView: View {
    @State private var showQuickCapture = false
    @ObservedObject private var router = TabRouter.shared

    var body: some View {
        ZStack(alignment: .bottom) {
            TabView(selection: $router.selection) {
                NavigationStack { TodayView().navigationBarTitleDisplayMode(.inline) }
                    .tabItem { Label("Übersicht", systemImage: "house") }
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

            Button {
                showQuickCapture = true
            } label: {
                Image(systemName: "plus")
                    .font(.system(size: 20, weight: .bold))
                    .foregroundStyle(KColor.accentInk)
                    .frame(width: 52, height: 52)
                    .background(KColor.accent, in: Circle())
                    .overlay(Circle().stroke(.white.opacity(0.9), lineWidth: 3))
                    .shadow(color: KColor.accentStrong.opacity(0.20), radius: 12, x: 0, y: 6)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Schnell erfassen")
            .padding(.bottom, 67)
        }
        .sheet(isPresented: $showQuickCapture) {
            QuickCaptureView()
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
    }
}

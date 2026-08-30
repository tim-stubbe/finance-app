import SwiftUI
import KiesCore

/// Premium iOS root navigation. The five primary areas stay native to iOS;
/// secondary features live in Mehr. The dashboard owns its visible heading, so
/// the navigation bar does not duplicate "Übersicht".
struct RootTabView: View {
    @State private var showQuickCapture = false
    @ObservedObject private var router = TabRouter.shared

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            TabView(selection: $router.selection) {
                NavigationStack {
                    TodayView()
                        .navigationTitle("")
                        .navigationBarTitleDisplayMode(.inline)
                }
                .tabItem { Label("Übersicht", systemImage: "house.fill") }
                .tag(AppTab.today)

                NavigationStack { AccountsView() }
                    .tabItem { Label("Konten", systemImage: "creditcard.fill") }
                    .tag(AppTab.accounts)

                NavigationStack { TransactionsView() }
                    .tabItem { Label("Transaktionen", systemImage: "arrow.left.arrow.right") }
                    .tag(AppTab.transactions)

                NavigationStack { TodosView() }
                    .tabItem { Label("Aufgaben", systemImage: "checkmark.circle") }
                    .tag(AppTab.todos)

                NavigationStack { MoreView() }
                    .tabItem { Label("Mehr", systemImage: "ellipsis") }
                    .tag(AppTab.more)
            }
            .tint(KColor.accent)

            // The action button is deliberately anchored to the safe-area
            // edge instead of the content, so it never covers list rows.
            Button {
                showQuickCapture = true
            } label: {
                Image(systemName: "plus")
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 54, height: 54)
                    .background(KColor.accent, in: Circle())
                    .shadow(color: .black.opacity(0.22), radius: 12, x: 0, y: 6)
            }
            .accessibilityLabel("Schnell erfassen")
            .padding(.trailing, 20)
            .padding(.bottom, 76)
        }
        .sheet(isPresented: $showQuickCapture) {
            QuickCaptureView()
        }
    }
}

import SwiftUI
import KiesCore

/// Sperrbildschirm, verdeckt RootTabView solange AppLockStore.isLocked true
/// ist - AppLockStore selbst lebt jetzt in KiesCore (siehe dort), daher der
/// zusätzliche Import.
struct AppLockView: View {
    @ObservedObject var lock = AppLockStore.shared

    var body: some View {
        VStack(spacing: 20) {
            Image(systemName: "lock.shield")
                .font(.system(size: 56))
                .foregroundStyle(.secondary)
            Text("Kies ist gesperrt")
                .font(.kSerif(.title, weight: .medium)).foregroundStyle(KTheme.text)
            if let message = lock.lastErrorMessage {
                Text(message)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
            }
            Button {
                Task { await lock.authenticate() }
            } label: {
                Label("Entsperren", systemImage: "faceid")
                    .font(.headline)
            }
            .buttonStyle(.borderedProminent)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(AlpenBackdrop())
        .task { await lock.authenticate() }
    }
}

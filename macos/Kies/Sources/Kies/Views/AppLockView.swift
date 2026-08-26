import SwiftUI
import KiesCore

/// Sperrbildschirm, verdeckt ContentView solange AppLockStore.isLocked true
/// ist - macOS-Gegenstück zu Sources/KiesiOS/AppLock/AppLockView.swift
/// (identischer Aufbau, AppLockStore selbst lebt jetzt gemeinsam in
/// KiesCore). Kein iOS-spezifischer Code hier, deshalb keine echte
/// Code-Duplikation an Logik, nur an der (trivialen) SwiftUI-Hülle.
struct AppLockView: View {
    @ObservedObject var lock = AppLockStore.shared

    var body: some View {
        VStack(spacing: 20) {
            Image(systemName: "lock.shield")
                .font(.system(size: 56))
                .foregroundStyle(.secondary)
            Text("Kies ist gesperrt")
                .font(.title2.bold())
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
                Label("Entsperren", systemImage: "touchid")
                    .font(.headline)
            }
            .buttonStyle(.borderedProminent)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.regularMaterial)
        .task { await lock.authenticate() }
    }
}

import SwiftUI
import KiesCore

/// Koppelt mit dem Server - gleicher Flow wie beim macOS-Client (Adresse +
/// native_sync_secret aus Kies → Einstellungen → Weitere Verbindungen →
/// Nativer Client), hier als eigenständige, für iOS passende Formularseite
/// statt der macOS-Fenster-Variante (siehe Sources/Kies/Views/PairingView.swift).
struct PairingView: View {
    @ObservedObject var pairing = PairingStore.shared
    @ObservedObject var engine = SyncEngine.shared
    @StateObject private var urlInput = Box("")
    @StateObject private var secretInput = Box("")
    @StateObject private var testing = Box(false)
    @StateObject private var testResult = Box<String?>(nil)

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("Server-Adresse und Secret findest du in Kies (Web-App) unter Einstellungen → Weitere Verbindungen → Nativer Client.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                Section("Verbindung") {
                    TextField("https://100.72.226.91:8000", text: urlInput.binding)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    SecureField("Secret", text: secretInput.binding)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }
                if let result = testResult.value {
                    Section {
                        Text(result).foregroundStyle(result.hasPrefix("✓") ? .green : .red)
                    }
                }
                Section {
                    Button {
                        connect()
                    } label: {
                        HStack {
                            Text("Verbinden")
                            if testing.value {
                                Spacer()
                                ProgressView()
                            }
                        }
                    }
                    .disabled(urlInput.value.trimmingCharacters(in: .whitespaces).isEmpty
                              || secretInput.value.isEmpty || testing.value)
                }
            }
            .scrollContentBackground(.hidden)
            .background(AlpenBackdrop())
            .navigationTitle("Mit Kies koppeln")
            .onAppear {
                urlInput.value = pairing.baseURLString
                secretInput.value = pairing.secret
            }
        }
    }

    private func connect() {
        pairing.baseURLString = urlInput.value.trimmingCharacters(in: .whitespaces)
        pairing.secret = secretInput.value
        Task {
            testing.value = true
            await engine.run()
            testing.value = false
            testResult.value = engine.lastError == nil ? "✓ Verbunden" : "✗ \(engine.lastError ?? "Fehler")"
        }
    }
}

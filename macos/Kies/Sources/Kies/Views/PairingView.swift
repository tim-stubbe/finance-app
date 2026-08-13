import SwiftUI

struct PairingView: View {
    @ObservedObject var pairing = PairingStore.shared
    @ObservedObject var engine = SyncEngine.shared
    @ObservedObject private var urlInput = Box("")
    @ObservedObject private var secretInput = Box("")
    @ObservedObject private var testing = Box(false)
    @ObservedObject private var testResult = Box<String?>(nil)

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Mit Kies koppeln").font(.title2).bold()
            Text("Server-Adresse und Secret aus Kies → Einstellungen → Weitere Verbindungen → Nativer macOS-Client.")
                .foregroundStyle(.secondary)

            TextField("https://100.72.226.91:8000", text: urlInput.binding)
                .textFieldStyle(.roundedBorder)
            SecureField("Secret", text: secretInput.binding)
                .textFieldStyle(.roundedBorder)

            if let result = testResult.value {
                Text(result).foregroundStyle(result.hasPrefix("✓") ? .green : .red)
            }

            HStack {
                Button("Verbinden") {
                    pairing.baseURLString = urlInput.value.trimmingCharacters(in: .whitespaces)
                    pairing.secret = secretInput.value
                    Task {
                        testing.value = true
                        await engine.run()
                        testing.value = false
                        testResult.value = engine.lastError == nil ? "✓ Verbunden" : "✗ \(engine.lastError ?? "Fehler")"
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(urlInput.value.isEmpty || secretInput.value.isEmpty || testing.value)
                if testing.value { ProgressView().controlSize(.small) }
            }
        }
        .padding(32)
        .frame(minWidth: 420)
        .onAppear {
            urlInput.value = pairing.baseURLString
            secretInput.value = pairing.secret
        }
    }
}

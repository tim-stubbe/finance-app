import SwiftUI

public struct AssistantChatView: View {
    @State private var input: String = ""
    @State private var isSending = false
    @State private var errorMessage: String?

    @State private var replyText: String?

    public init() {}

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text(replyText ?? "Schreib eine Frage – der Assistent antwortet.")
                    .font(.body)
                    .fixedSize(horizontal: false, vertical: true)

                if let err = errorMessage {
                    Text(err)
                        .foregroundStyle(.red)
                        .font(.caption)
                }

                TextField("z.B. Wie hoch ist mein Kontostand?", text: $input)
                    .textFieldStyle(.roundedBorder)

                Button {
                    Task { await send() }
                } label: {
                    if isSending {
                        ProgressView()
                    } else {
                        Text("Senden")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(isSending || input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            .padding(18)
        }
    }

    private func send() async {
        isSending = true
        errorMessage = nil
        defer { isSending = false }

        do {
            let resp = try await DeviceAssistantClient.chat(message: input, history: [])
            replyText = resp.reply
            if resp.ok == false {
                errorMessage = resp.reply ?? "Fehler beim Assistenten."
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

// In KiesCore absichtlich ohne DesignKit-Abhängigkeit, damit KiesCore als
// Library-Produkt in iOS und macOS ohne SwiftUI-Design-System weiter genutzt
// werden kann.

#warning("AssistantChatView (KiesCore) ist eine Minimalansicht für den Device-Auth Roundtrip.")

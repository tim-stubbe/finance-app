import AppIntents
import Foundation
import KiesCore

/// Siri-Shortcut / App-Intent: einen Befehl oder eine Frage an Kies schicken.
///
/// Ruft `POST {baseURL}/api/sync/command` mit dem geteilten Sync-Secret auf
/// (derselbe Auth-Weg wie pull/push - ein nativer Client hat keinen
/// Browser-Cookie). Serverseitig routet das durch `hub_command.route`, deckt
/// also Smart Home, To-do, Wunschliste, Kalender, Fragen usw. ab.
///
/// Nicht im Xcode-Projekt, bis `xcodegen` neu laeuft (die Datei liegt aber
/// unter Sources/KiesiOS/, wird also automatisch mit aufgenommen). App
/// Intents brauchen iOS 16+.
@available(iOS 16.0, *)
struct KiesAskIntent: AppIntent {
    static var title: LocalizedStringResource = "Kies fragen"
    static var description = IntentDescription(
        "Schickt einen Befehl oder eine Frage an Kies – Smart Home, To-do, Wunschliste, Kalender oder eine Auskunft."
    )
    static var openAppWhenRun: Bool = false

    @Parameter(title: "Befehl oder Frage")
    var text: String

    static var parameterSummary: some ParameterSummary {
        Summary("Sag Kies \(\.$text)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let store = PairingStore.shared
        guard store.isPaired else {
            return .result(dialog: "Kies ist noch nicht mit dem Server gekoppelt.")
        }
        var base = store.baseURLString
        if base.hasSuffix("/") { base.removeLast() }
        guard let url = URL(string: base + "/api/sync/command") else {
            return .result(dialog: "Die Serveradresse von Kies ist ungültig.")
        }

        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 20
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue(store.secret, forHTTPHeaderField: "X-Sync-Secret")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["text": text])

        do {
            let (data, resp) = try await KiesHTTP.session.data(for: req)
            guard let http = resp as? HTTPURLResponse else {
                return .result(dialog: "Keine Antwort vom Kies-Server.")
            }
            let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            if http.statusCode == 403 {
                return .result(dialog: "Kies hat den Zugriff abgelehnt – Kopplung prüfen.")
            }
            if http.statusCode != 200 {
                return .result(dialog: IntentDialog(stringLiteral: (obj?["detail"] as? String) ?? "Kies konnte das nicht verarbeiten."))
            }
            let reply = (obj?["reply"] as? String) ?? "Erledigt."
            return .result(dialog: IntentDialog(stringLiteral: reply))
        } catch {
            return .result(dialog: "Kies ist gerade nicht erreichbar.")
        }
    }
}

@available(iOS 16.0, *)
struct KiesShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: KiesAskIntent(),
            // Freitext-Parameter (String) dürfen NICHT in die Phrasen
            // interpoliert werden (nur AppEntity/AppEnum) - Siri fragt den
            // Befehl nach dem Auslösen der Phrase ab (parameterSummary oben).
            phrases: [
                "Sag \(.applicationName) etwas",
                "Frag \(.applicationName)",
                "\(.applicationName) fragen",
            ],
            shortTitle: "Kies fragen",
            systemImageName: "house.fill"
        )
    }
}

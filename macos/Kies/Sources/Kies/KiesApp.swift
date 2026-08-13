import SwiftUI

@main
struct KiesApp: App {
    init() {
        // Für Skript-/Testaufbau (z.B. lokaler Docker-Server): Pairing per
        // Umgebungsvariablen setzen. Läuft im eigenen Prozess, deshalb kein
        // Cross-App-Keychain-Zugriffsdialog wie beim externen Befüllen des
        // Keychains von einem anderen Programm aus.
        let env = ProcessInfo.processInfo.environment
        if let url = env["KIES_BASE_URL"], let secret = env["KIES_SYNC_SECRET"] {
            PairingStore.shared.baseURLString = url
            PairingStore.shared.secret = secret
        }
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}

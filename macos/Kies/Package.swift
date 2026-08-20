// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Kies",
    // iOS dazu, damit KiesCore (siehe unten) multiplatform ist - Foundation/
    // GRDB/Security/Combine sind auf beiden Plattformen verfügbar, keine
    // AppKit-Abhängigkeit im geteilten Code. Kies (macOS-GUI) und KiesCLI
    // bleiben bewusst macOS-only (AppKit- bzw. Terminal-Werkzeug); KiesiOS
    // ist das neue, iOS-only App-Target.
    platforms: [.macOS(.v14), .iOS(.v17)],
    dependencies: [
        .package(url: "https://github.com/groue/GRDB.swift.git", from: "6.29.0"),
    ],
    targets: [
        // Datenbank + Sync-Engine, ohne SwiftUI-Abhängigkeit - läuft dadurch
        // auch als reines Kommandozeilen-Tool (KiesCLI), unabhängig von einer
        // aktiven Display-Session/NSApplication. Genau das macht sie für
        // Tests brauchbar: die GUI-App (Kies) wird von macOS bei gesperrtem
        // Bildschirm/App Nap stark gedrosselt, ein Kommandozeilen-Prozess nicht.
        //
        // Multiplatform (macOS + iOS): dieselbe Bibliothek trägt jetzt auch
        // die neue iOS-App (KiesiOS) - Models, lokale SQLite, Sync-Engine,
        // Pairing und Keychain sind für beide Plattformen identisch, nur die
        // SwiftUI-Oberfläche ist pro Plattform eigenständig (siehe
        // Sources/Kies vs. Sources/KiesiOS).
        .target(
            name: "KiesCore",
            dependencies: [.product(name: "GRDB", package: "GRDB.swift")],
            path: "Sources/KiesCore"
        ),
        .executableTarget(
            name: "Kies",
            dependencies: ["KiesCore"],
            path: "Sources/Kies"
        ),
        .executableTarget(
            name: "KiesCLI",
            dependencies: ["KiesCore"],
            path: "Sources/KiesCLI"
        ),
        // iOS-App - eigenes Target statt eines Plattform-Zweigs in "Kies",
        // weil die Oberfläche bewusst eigenständig für iOS gebaut ist
        // (TabView/NavigationStack statt NavigationSplitView, siehe
        // Sources/KiesiOS/README im Kopfkommentar von KiesiOSApp.swift).
        // In Xcode: Package.swift öffnen, Schema "KiesiOS" + einen iOS-
        // Simulator als Ziel wählen, Run.
        .executableTarget(
            name: "KiesiOS",
            dependencies: ["KiesCore"],
            path: "Sources/KiesiOS"
        ),
    ]
)

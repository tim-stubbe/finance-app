// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Kies",
    platforms: [.macOS(.v14)],
    dependencies: [
        .package(url: "https://github.com/groue/GRDB.swift.git", from: "6.29.0"),
    ],
    targets: [
        // Datenbank + Sync-Engine, ohne SwiftUI-Abhängigkeit - läuft dadurch
        // auch als reines Kommandozeilen-Tool (KiesCLI), unabhängig von einer
        // aktiven Display-Session/NSApplication. Genau das macht sie für
        // Tests brauchbar: die GUI-App (Kies) wird von macOS bei gesperrtem
        // Bildschirm/App Nap stark gedrosselt, ein Kommandozeilen-Prozess nicht.
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
    ]
)

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
    // KiesCore als Library-Produkt exportiert - ab jetzt gebraucht vom
    // xcodegen-erzeugten Kies.xcodeproj (siehe project.yml): die Widget-
    // Extension (KiesWidget) und die Share-Extension (KiesShare) sind ECHTE
    // Xcode-App-Extension-Targets (SPM allein kann keine App-Extension-
    // Bundles erzeugen, siehe project.yml-Kopfkommentar), binden KiesCore
    // deshalb nicht als SPM-Sibling-Target, sondern als Swift-Package-
    // Abhängigkeit ein - das braucht einen benannten Produkt-Eintrag.
    // Innerhalb dieses Manifests ändert sich für Kies/KiesCLI/KiesiOS
    // nichts, die referenzieren "KiesCore" weiterhin direkt als Zieltarget.
    products: [
        .library(name: "KiesCore", targets: ["KiesCore"]),
    ],
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
        //
        // Zwei Wege, dieselben Sources/KiesiOS-Quellen zu bauen:
        // 1. Schnell/ohne Widget: Package.swift öffnen, Schema "KiesiOS" +
        //    einen iOS-Simulator als Ziel wählen, Run - baut GENAU dieses
        //    SPM-Target hier, unverändert seit den ersten iOS-Scheiben.
        // 2. Mit Widget/Share-Extension: Kies.xcodeproj öffnen (siehe
        //    project.yml, per `xcodegen generate` erzeugt) - dort ist
        //    KiesiOS ein echtes Xcode-App-Target (Voraussetzung fürs
        //    Einbetten von App-Extensions), das dieselben Sources/KiesiOS-
        //    Dateien kompiliert und KiesCore als Package-Produkt einbindet.
        .executableTarget(
            name: "KiesiOS",
            dependencies: ["KiesCore"],
            path: "Sources/KiesiOS"
        ),
    ]
)

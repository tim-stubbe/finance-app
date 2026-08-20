import SwiftUI

/// Ersatz für `@State` in diesem Package - siehe der ausführliche Kommentar
/// in Sources/Kies/Views/Box.swift (macOS-Target) für die Begründung (nur
/// Command Line Tools installiert, `@State`s Makro-Plugin fehlt dadurch).
/// SPM-Executable-Targets exportieren kein Modul, das ein anderes Target
/// importieren könnte - deshalb hier eine eigene, identische Kopie statt
/// eines Imports aus dem "Kies"-Target. Sobald mit vollem Xcode gebaut wird,
/// kann dies durch `@State` ersetzt werden, ist aber funktional gleichwertig.
final class Box<T>: ObservableObject {
    @Published var value: T
    init(_ value: T) { self.value = value }

    var binding: Binding<T> {
        Binding(get: { self.value }, set: { self.value = $0 })
    }
}

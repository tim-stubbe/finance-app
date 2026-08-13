import SwiftUI

/// Ersatz für `@State` in diesem Projekt: das hier verfügbare Swift-
/// Toolchain sind nur die Command Line Tools (kein volles Xcode installiert)
/// - `@State`s Makro-Implementierung (SwiftUIMacros-Plugin) liegt aber nur
/// in Xcode selbst, nicht in den Command Line Tools, und schlägt beim
/// Kompilieren fehl ("plugin for module 'SwiftUIMacros' not found").
/// `@ObservedObject`/`@Published`/`@Environment` sind NICHT betroffen (reines
/// Combine, kein Makro) - `Box` bündelt lokalen, veränderlichen View-Zustand
/// deshalb in einer ObservableObject-Klasse statt im (hier unbaubaren)
/// `@State`. Sobald volles Xcode installiert ist, kann das durch `@State`
/// ersetzt werden, ist aber funktional gleichwertig.
final class Box<T>: ObservableObject {
    @Published var value: T
    init(_ value: T) { self.value = value }

    var binding: Binding<T> {
        Binding(get: { self.value }, set: { self.value = $0 })
    }
}

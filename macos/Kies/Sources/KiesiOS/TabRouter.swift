import Foundation

/// Bereiche der TabView (siehe RootTabView) - eigener Typ statt roher Ints/
/// Strings, damit ein Tab-Ziel von überall her (Such-Ergebnis antippen,
/// Widget-Deep-Link) eindeutig benannt werden kann.
public enum AppTab: String, CaseIterable {
    case today, accounts, transactions, todos, more
    // Nebenschauplaetze - eigene Tags fuer Deep-Links/Suche, aber kein
    // eigener Tab mehr (siehe RootTabView / MoreView). jump(to:) leitet sie
    // auf den "Mehr"-Tab um.
    case goals, life, wishlist, categories, investments, search

    var primaryTab: AppTab {
        switch self {
        case .today, .accounts, .transactions, .todos: return self
        default: return .more
        }
    }
}

/// Zentrale Stelle, um programmatisch den aktiven Tab zu wechseln - genutzt
/// von SearchView (Ergebnis antippen -> richtiger Tab) und vom Widget-
/// Deep-Link (kies://today, siehe KiesiOSApp.onOpenURL). Bewusst kein
/// NavigationPath/Deep-Link zu einzelner Zeile: die App hat aktuell nirgends
/// eigene Detail-Screens für einzelne Buchungen/Todos/Ziele (siehe die
/// jeweiligen Views - reine Listen), "richtigen Tab öffnen" ist der
/// bestehende Detailgrad.
@MainActor
public final class TabRouter: ObservableObject {
    public static let shared = TabRouter()
    @Published public var selection: AppTab = .today

    private init() {}

    public func jump(to tab: AppTab) {
        selection = tab.primaryTab
    }
}

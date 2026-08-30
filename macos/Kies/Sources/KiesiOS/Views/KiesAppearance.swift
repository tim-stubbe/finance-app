import SwiftUI
import UIKit

/// UIKit-Appearance für Navigations- und Tab-Leiste - bewusst zurückhaltend:
/// System-Material als Hintergrund (passt sich Light/Dark an), Blau als
/// Auswahlfarbe, System-Font (SF Pro). Kein warmer Ton, keine Serifen mehr.
enum KiesAppearance {
    static func apply() {
        let accent = UIColor(KColor.accent)

        let nav = UINavigationBarAppearance()
        nav.configureWithDefaultBackground()
        nav.shadowColor = .clear
        nav.largeTitleTextAttributes = [.foregroundColor: UIColor(KColor.primary)]
        nav.titleTextAttributes = [.foregroundColor: UIColor(KColor.primary)]
        UINavigationBar.appearance().standardAppearance = nav
        UINavigationBar.appearance().scrollEdgeAppearance = nav
        UINavigationBar.appearance().compactAppearance = nav
        UINavigationBar.appearance().tintColor = accent

        let tab = UITabBarAppearance()
        tab.configureWithDefaultBackground()
        for item in [tab.stackedLayoutAppearance, tab.inlineLayoutAppearance, tab.compactInlineLayoutAppearance] {
            item.selected.iconColor = accent
            item.selected.titleTextAttributes = [.foregroundColor: accent]
        }
        UITabBar.appearance().standardAppearance = tab
        UITabBar.appearance().scrollEdgeAppearance = tab
    }
}

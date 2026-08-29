import SwiftUI
import UIKit

/// UIKit-Appearance fuer Navigations- und Tab-Leiste passend zum "Alpen
/// Desktop"-Look: warmer, fast schwarzer, leicht durchscheinender Grund,
/// Gold als Auswahlfarbe, Serifenschrift ("New York") fuer die Titel.
enum KiesAppearance {
    static func apply() {
        let warm = UIColor(KTheme.background)
        let gold = UIColor(KTheme.gold)
        let text = UIColor(KTheme.text)

        // ---- Navigation Bar ----
        let nav = UINavigationBarAppearance()
        nav.configureWithOpaqueBackground()
        nav.backgroundColor = warm.withAlphaComponent(0.7)
        nav.shadowColor = UIColor.white.withAlphaComponent(0.12)

        let large = UIFontDescriptor.preferredFontDescriptor(withTextStyle: .largeTitle)
            .withDesign(.serif) ?? UIFontDescriptor.preferredFontDescriptor(withTextStyle: .largeTitle)
        let inline = UIFontDescriptor.preferredFontDescriptor(withTextStyle: .headline)
            .withDesign(.serif) ?? UIFontDescriptor.preferredFontDescriptor(withTextStyle: .headline)
        nav.largeTitleTextAttributes = [
            .foregroundColor: text,
            .font: UIFont(descriptor: large, size: 0),
        ]
        nav.titleTextAttributes = [
            .foregroundColor: text,
            .font: UIFont(descriptor: inline, size: 0),
        ]

        UINavigationBar.appearance().standardAppearance = nav
        UINavigationBar.appearance().scrollEdgeAppearance = nav
        UINavigationBar.appearance().compactAppearance = nav
        UINavigationBar.appearance().tintColor = gold

        // ---- Tab Bar ----
        let tab = UITabBarAppearance()
        tab.configureWithOpaqueBackground()
        tab.backgroundColor = warm.withAlphaComponent(0.82)
        tab.shadowColor = UIColor.white.withAlphaComponent(0.12)
        for item in [tab.stackedLayoutAppearance, tab.inlineLayoutAppearance, tab.compactInlineLayoutAppearance] {
            item.selected.iconColor = gold
            item.selected.titleTextAttributes = [.foregroundColor: gold]
            item.normal.iconColor = UIColor(KTheme.muted)
            item.normal.titleTextAttributes = [.foregroundColor: UIColor(KTheme.muted)]
        }
        UITabBar.appearance().standardAppearance = tab
        UITabBar.appearance().scrollEdgeAppearance = tab
    }
}

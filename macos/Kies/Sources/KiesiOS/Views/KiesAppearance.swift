import SwiftUI
import UIKit

enum KiesAppearance {
    static func apply() {
        let accent = UIColor(KColor.accentStrong)

        let nav = UINavigationBarAppearance()
        nav.configureWithDefaultBackground()
        nav.backgroundColor = UIColor(KColor.surface)
        nav.shadowColor = UIColor(KColor.divider)
        nav.largeTitleTextAttributes = [.foregroundColor: UIColor(KColor.primary)]
        nav.titleTextAttributes = [.foregroundColor: UIColor(KColor.primary)]
        UINavigationBar.appearance().standardAppearance = nav
        UINavigationBar.appearance().scrollEdgeAppearance = nav
        UINavigationBar.appearance().compactAppearance = nav
        UINavigationBar.appearance().tintColor = accent

        let tab = UITabBarAppearance()
        tab.configureWithDefaultBackground()
        tab.backgroundColor = UIColor(KColor.surface)
        tab.shadowColor = UIColor(KColor.divider)
        for item in [tab.stackedLayoutAppearance, tab.inlineLayoutAppearance, tab.compactInlineLayoutAppearance] {
            item.selected.iconColor = accent
            item.selected.titleTextAttributes = [.foregroundColor: accent]
            item.normal.iconColor = UIColor(KColor.tertiary)
            item.normal.titleTextAttributes = [.foregroundColor: UIColor(KColor.secondary)]
        }
        UITabBar.appearance().standardAppearance = tab
        UITabBar.appearance().scrollEdgeAppearance = tab
    }
}

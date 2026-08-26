import WidgetKit
import SwiftUI

/// Einstiegspunkt der Widget-Extension (siehe project.yml: NSExtensionPoint-
/// Identifier com.apple.widgetkit-extension) - @main reicht hier, anders als
/// bei einer Share-Extension (siehe Sources/KiesShare) braucht WidgetKit
/// keinen NSExtensionPrincipalClass-Eintrag im Info.plist.
@main
struct KiesWidgetBundle: WidgetBundle {
    var body: some Widget {
        KiesTodayWidget()
    }
}

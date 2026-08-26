import UIKit
import SwiftUI
import UniformTypeIdentifiers
import KiesCore

/// Einstiegspunkt der Share-Extension (siehe project.yml: NSExtensionMain-
/// StoryboardExtensionPointIdentifier com.apple.share-services + NSExtension-
/// PrincipalClass) - kein SwiftUI-@main hier möglich (Share-Extensions sind
/// UIKit-Extension-Points), deshalb ein schlanker UIViewController, der die
/// eigentliche Oberfläche als UIHostingController einbettet. Extrahiert
/// Text/URL aus dem geteilten Inhalt (Safari/Mail/Banking-Apps) und übergibt
/// sie an ShareComposeView zur Bearbeitung, bevor per SyncEngine.createXOffline
/// (derselbe Outbox-Pfad wie Quick Capture in der Haupt-App) gespeichert wird.
final class ShareViewController: UIViewController {
    override func viewDidLoad() {
        super.viewDidLoad()
        extractSharedContent { [weak self] text, url in
            guard let self else { return }
            let composeView = ShareComposeView(
                initialText: text, initialURL: url,
                onSave: { [weak self] in self?.finish() },
                onCancel: { [weak self] in self?.finish() }
            )
            let hosting = UIHostingController(rootView: composeView)
            self.addChild(hosting)
            hosting.view.frame = self.view.bounds
            hosting.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
            self.view.addSubview(hosting.view)
            hosting.didMove(toParent: self)
        }
    }

    private func finish() {
        extensionContext?.completeRequest(returningItems: nil)
    }

    /// Liest Text bzw. URL aus dem ersten Attachment des geteilten Inhalts -
    /// Safari teilt i.d.R. eine URL, Mail/Notizen/Banking-Apps oft reinen
    /// Text (z.B. markierter Betrag/Buchungstext). Beides wird versucht,
    /// URL zuerst (spezifischerer Typ).
    private func extractSharedContent(completion: @escaping (String?, URL?) -> Void) {
        guard let item = extensionContext?.inputItems.first as? NSExtensionItem,
              let attachment = item.attachments?.first else {
            completion(nil, nil)
            return
        }
        if attachment.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
            attachment.loadItem(forTypeIdentifier: UTType.url.identifier) { data, _ in
                DispatchQueue.main.async {
                    completion(item.attributedContentText?.string, data as? URL)
                }
            }
        } else if attachment.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
            attachment.loadItem(forTypeIdentifier: UTType.plainText.identifier) { data, _ in
                DispatchQueue.main.async {
                    completion(data as? String ?? item.attributedContentText?.string, nil)
                }
            }
        } else {
            completion(item.attributedContentText?.string, nil)
        }
    }
}

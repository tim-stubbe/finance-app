import SwiftUI
import KiesCore
import GRDB

/// Schlanke Erfassungsmaske der Share-Extension - Buchung oder Todo aus
/// geteiltem Text/einer URL anlegen. Nutzt dieselben Offline-Anlege-Pfade
/// wie QuickCaptureView in der Haupt-App (SyncEngine.createTransactionOffline/
/// createTodoOffline -> Outbox), kein eigener Speicherweg. Die App-Group-DB
/// (siehe AppDatabase.appGroupID) macht das sofort für die App sichtbar,
/// auch bevor diese als nächstes geöffnet wird - der eigentliche Push zum
/// Server läuft dann beim nächsten Start/Sync der Haupt-App.
enum ShareKind: String, CaseIterable, Identifiable {
    case transaction = "Buchung"
    case todo = "Todo"
    var id: String { rawValue }
}

struct ShareComposeView: View {
    let onSave: () -> Void
    let onCancel: () -> Void

    @State private var kind: ShareKind = .transaction
    @State private var title: String = ""
    @State private var amountText: String = ""
    @State private var accounts: [Account] = []
    @State private var selectedAccountID: Int64?
    @State private var saveError: String?
    @State private var isPaired = PairingStore.shared.isPaired

    init(initialText: String?, initialURL: URL?, onSave: @escaping () -> Void, onCancel: @escaping () -> Void) {
        self.onSave = onSave
        self.onCancel = onCancel
        let text = initialText?.trimmingCharacters(in: .whitespacesAndNewlines)
        _title = State(initialValue: text?.isEmpty == false ? text! : (initialURL?.host ?? ""))
        _amountText = State(initialValue: Self.detectAmount(in: text ?? ""))
    }

    var body: some View {
        NavigationStack {
            Form {
                if !isPaired {
                    Section {
                        Text("Kies ist auf diesem Gerät noch nicht mit dem Server gekoppelt - bitte zuerst die Kies-App öffnen und koppeln.")
                            .foregroundStyle(.secondary)
                    }
                } else {
                    Section {
                        Picker("Art", selection: $kind) {
                            ForEach(ShareKind.allCases) { Text($0.rawValue).tag($0) }
                        }
                        .pickerStyle(.segmented)
                    }
                    Section(kind == .transaction ? "Buchung" : "Todo") {
                        TextField(kind == .transaction ? "Beschreibung" : "Titel", text: $title)
                        if kind == .transaction {
                            TextField("Betrag (negativ = Ausgabe)", text: $amountText)
                                .keyboardType(.decimalPad)
                            if !accounts.isEmpty {
                                Picker("Konto", selection: $selectedAccountID) {
                                    ForEach(accounts) { account in
                                        Text(account.name).tag(account.id as Int64?)
                                    }
                                }
                            } else {
                                Text("Kein Konto lokal synchronisiert - bitte erst die Kies-App einmal öffnen.")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                    if let saveError {
                        Section { Text(saveError).foregroundStyle(.red).font(.caption) }
                    }
                }
            }
            .navigationTitle("Mit Kies teilen")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Abbrechen", action: onCancel)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Sichern", action: save)
                        .disabled(!isPaired || title.trimmingCharacters(in: .whitespaces).isEmpty || (kind == .transaction && accounts.isEmpty))
                }
            }
            .onAppear(perform: loadAccounts)
        }
    }

    private func loadAccounts() {
        isPaired = PairingStore.shared.isPaired
        guard isPaired else { return }
        accounts = (try? AppDatabase.shared.read { db in try Account.order(Column("name")).fetchAll(db) }) ?? []
        selectedAccountID = accounts.first?.id
    }

    @MainActor
    private func save() {
        let trimmedTitle = title.trimmingCharacters(in: .whitespaces)
        guard !trimmedTitle.isEmpty else { return }
        do {
            switch kind {
            case .transaction:
                guard let accountID = selectedAccountID else { return }
                let amount = Double(amountText.replacingOccurrences(of: ",", with: ".")) ?? 0
                let today = DateFormatter.isoDate.string(from: Date())
                try SyncEngine.shared.createTransactionOffline(accountID: accountID, date: today, amount: amount, description: trimmedTitle)
            case .todo:
                try SyncEngine.shared.createTodoOffline(title: trimmedTitle, dueDate: nil)
            }
            onSave()
        } catch {
            saveError = "Konnte nicht gespeichert werden: \(error.localizedDescription)"
        }
    }

    /// Sehr einfache Heuristik für "Betragsähnliches" im geteilten Text -
    /// findet die erste Zahl mit Dezimaltrennzeichen (12,34 oder 12.34),
    /// optional mit €/EUR/CHF davor oder danach. Kein Anspruch auf
    /// Vollständigkeit (kein NLP), nur ein Vorschlag, den der Nutzer vor dem
    /// Sichern jederzeit korrigieren kann.
    static func detectAmount(in text: String) -> String {
        guard let regex = try? NSRegularExpression(pattern: #"(\d+[.,]\d{2})"#) else { return "" }
        let range = NSRange(text.startIndex..., in: text)
        guard let match = regex.firstMatch(in: text, range: range), let matchRange = Range(match.range(at: 1), in: text) else {
            return ""
        }
        return String(text[matchRange]).replacingOccurrences(of: ",", with: ".")
    }
}

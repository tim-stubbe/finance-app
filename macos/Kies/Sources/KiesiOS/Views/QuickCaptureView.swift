import SwiftUI
import GRDB
import KiesCore

/// Zentrale schnelle Erfassung (Buchung/Todo/Life-Check-in), erreichbar über
/// den Plus-Button in RootTabView - nutzt dieselben Offline-Anlege-Pfade wie
/// die bestehenden Tab-eigenen Formulare (SyncEngine.create*Offline), keine
/// eigene Schreiblogik.
struct QuickCaptureView: View {
    enum Kind: String, CaseIterable, Identifiable {
        case transaction = "Buchung"
        case todo = "Todo"
        case checkin = "Check-in"
        var id: String { rawValue }
    }

    @Environment(\.dismiss) private var dismiss
    @State private var kind: Kind = .transaction

    // Buchung
    @ObservedObject private var accounts = Box<[Account]>([])
    @State private var accountID: Int64?
    @State private var amountText = ""
    @State private var txDescription = ""

    // Todo
    @State private var todoTitle = ""
    @State private var hasDueDate = false
    @State private var dueDate = Date()

    // Check-in
    @ObservedObject private var lifeAreas = Box<[LifeArea]>([])
    @State private var checkinAreaID: Int64?
    @State private var checkinNote = ""

    var body: some View {
        NavigationStack {
            Form {
                Picker("Art", selection: $kind) {
                    ForEach(Kind.allCases) { k in Text(k.rawValue).tag(k) }
                }
                .pickerStyle(.segmented)

                switch kind {
                case .transaction: transactionFields
                case .todo: todoFields
                case .checkin: checkinFields
                }
            }
            .navigationTitle("Erfassen")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Abbrechen") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Speichern") { save() }
                        .disabled(!canSave)
                }
            }
            .task {
                accounts.value = (try? AppDatabase.shared.read { db in try Account.order(Column("name")).fetchAll(db) }) ?? []
                lifeAreas.value = (try? AppDatabase.shared.read { db in try LifeArea.filter(Column("active") == true).order(Column("name")).fetchAll(db) }) ?? []
                accountID = accounts.value.first?.id
                checkinAreaID = lifeAreas.value.first?.id
            }
        }
    }

    @ViewBuilder private var transactionFields: some View {
        Section {
            Picker("Konto", selection: $accountID) {
                ForEach(accounts.value) { account in
                    Text(account.name).tag(Optional(account.id))
                }
            }
            TextField("Betrag", text: $amountText)
                .keyboardType(.decimalPad)
            TextField("Beschreibung (optional)", text: $txDescription)
        }
    }

    @ViewBuilder private var todoFields: some View {
        Section {
            TextField("Titel", text: $todoTitle)
            Toggle("Fällig am", isOn: $hasDueDate)
            if hasDueDate {
                DatePicker("Datum", selection: $dueDate, displayedComponents: .date)
                    .datePickerStyle(.compact)
            }
        }
    }

    @ViewBuilder private var checkinFields: some View {
        if lifeAreas.value.isEmpty {
            Section {
                Text("Noch keine Lebensbereiche synchronisiert.").foregroundStyle(.secondary)
            }
        } else {
            Section {
                Picker("Lebensbereich", selection: $checkinAreaID) {
                    ForEach(lifeAreas.value) { area in
                        Text(area.name).tag(Optional(area.id))
                    }
                }
                TextField("Notiz (optional)", text: $checkinNote)
            }
        }
    }

    private var canSave: Bool {
        switch kind {
        case .transaction:
            return accountID != nil && Double(amountText.replacingOccurrences(of: ",", with: ".")) != nil
        case .todo:
            return !todoTitle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case .checkin:
            return checkinAreaID != nil
        }
    }

    private func save() {
        switch kind {
        case .transaction:
            guard let accountID, let amount = Double(amountText.replacingOccurrences(of: ",", with: ".")) else { return }
            let date = DateFormatter.isoDate.string(from: Date())
            let description = txDescription.trimmingCharacters(in: .whitespacesAndNewlines)
            try? SyncEngine.shared.createTransactionOffline(
                accountID: accountID, date: date, amount: amount,
                description: description.isEmpty ? nil : description
            )
        case .todo:
            let title = todoTitle.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !title.isEmpty else { return }
            let due = hasDueDate ? DateFormatter.isoDate.string(from: dueDate) : nil
            try? SyncEngine.shared.createTodoOffline(title: title, dueDate: due)
        case .checkin:
            guard let checkinAreaID else { return }
            let note = checkinNote.trimmingCharacters(in: .whitespacesAndNewlines)
            try? SyncEngine.shared.createLifeCheckInOffline(areaID: checkinAreaID, note: note.isEmpty ? "Erledigt" : note)
        }
        dismiss()
        Task { await SyncEngine.shared.run() }
    }
}

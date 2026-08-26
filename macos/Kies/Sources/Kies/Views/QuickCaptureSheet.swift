import SwiftUI
import KiesCore
import GRDB

/// Schnelle Erfassung (Buchung/Todo/Check-in) fürs macOS-Detail-Pane -
/// macOS-Gegenstück zu KiesiOS/Views/QuickCaptureView.swift, dieselben
/// Offline-Anlege-Pfade (SyncEngine.create*Offline). Ohne `.keyboardType`
/// (UIKit-only, gibt es unter macOS nicht) - sonst inhaltlich identisch.
struct QuickCaptureSheet: View {
    enum Kind: String, CaseIterable, Identifiable {
        case transaction = "Buchung"
        case todo = "Todo"
        case checkin = "Check-in"
        var id: String { rawValue }
    }

    @Environment(\.dismiss) private var dismiss
    @State private var kind: Kind = .transaction

    @ObservedObject private var accounts = Box<[Account]>([])
    @State private var accountID: Int64?
    @State private var amountText = ""
    @State private var txDescription = ""

    @State private var todoTitle = ""
    @State private var hasDueDate = false
    @State private var dueDate = Date()

    @ObservedObject private var lifeAreas = Box<[LifeArea]>([])
    @State private var checkinAreaID: Int64?
    @State private var checkinNote = ""

    var body: some View {
        VStack(spacing: 0) {
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
            .padding()

            Divider()

            HStack {
                Button("Abbrechen") { dismiss() }
                Spacer()
                Button("Speichern") { save() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(!canSave)
            }
            .padding()
        }
        .frame(width: 380)
        .task {
            accounts.value = (try? AppDatabase.shared.read { db in try Account.order(Column("name")).fetchAll(db) }) ?? []
            lifeAreas.value = (try? AppDatabase.shared.read { db in try LifeArea.filter(Column("active") == true).order(Column("name")).fetchAll(db) }) ?? []
            accountID = accounts.value.first?.id
            checkinAreaID = lifeAreas.value.first?.id
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
            TextField("Beschreibung (optional)", text: $txDescription)
        }
    }

    @ViewBuilder private var todoFields: some View {
        Section {
            TextField("Titel", text: $todoTitle)
            Toggle("Fällig am", isOn: $hasDueDate)
            if hasDueDate {
                DatePicker("Datum", selection: $dueDate, displayedComponents: .date)
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

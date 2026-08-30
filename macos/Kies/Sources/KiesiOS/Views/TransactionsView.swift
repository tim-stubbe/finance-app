import SwiftUI
import KiesCore
import GRDB

/// Buchungsliste mit grobem Filter (Konto, "nur letzte 30 Tage") - kein
/// vollständiger Filter-/Suchapparat wie in der Web-App, das ist für die
/// erste iOS-Scheibe bewusst zu viel (siehe ROADMAP.md).
struct TransactionsView: View {
    @ObservedObject var engine = SyncEngine.shared
    @StateObject private var transactions = Box<[TransactionRecord]>([])
    @StateObject private var accountsByID = Box<[Int64: Account]>([:])
    @StateObject private var accountFilter = Box<Int64?>(nil)
    @StateObject private var onlyLast30Days = Box(false)
    @StateObject private var showNewSheet = Box(false)
    @State private var editingTransaction: TransactionRecord?

    var body: some View {
        List {
            Section {
                Picker("Konto", selection: accountFilter.binding) {
                    Text("Alle Konten").tag(Int64?.none)
                    ForEach(Array(accountsByID.value.values).sorted { $0.name < $1.name }) { a in
                        Text(a.name).tag(a.id as Int64?)
                    }
                }
                Toggle("Nur letzte 30 Tage", isOn: onlyLast30Days.binding)
            }
            .listRowBackground(KColor.surface)

            if filteredTransactions.isEmpty {
                Section {
                    KEmptyState(icon: "list.bullet.rectangle",
                                title: "Keine Transaktionen",
                                message: "Noch nichts synchronisiert – oder der Filter ist zu eng gesetzt.")
                    .listRowBackground(Color.clear)
                }
            }

            ForEach(groupedTransactions, id: \.key) { group in
                Section {
                    ForEach(group.items) { tx in
                        KTransactionRow(title: tx.description ?? "–",
                                        subtitle: accountsByID.value[tx.account_id]?.name ?? "Konto \(tx.account_id)",
                                        amount: tx.amount,
                                        pending: tx.pending_client_id != nil)
                        .listRowBackground(KColor.surface)
                        .swipeActions(edge: .trailing) {
                            Button { editingTransaction = tx } label: {
                                Label("Bearbeiten", systemImage: "pencil")
                            }
                            .tint(KColor.accent)
                            .disabled(tx.id < 0)
                        }
                    }
                } header: {
                    Text(group.label).font(.footnote.weight(.semibold)).foregroundStyle(KColor.secondary)
                }
            }
        }
        .listStyle(.insetGrouped)
        .kListChrome()
        .navigationTitle("Transaktionen")
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button { showNewSheet.value = true } label: { Image(systemName: "plus") }
            }
            SyncStatusToolbarItem()
        }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
        .sheet(isPresented: showNewSheet.binding) {
            NewTransactionSheet(accounts: Array(accountsByID.value.values).sorted { $0.name < $1.name }) {
                reload()
                showNewSheet.value = false
            }
        }
        .sheet(item: $editingTransaction) { tx in
            EditTransactionSheet(transaction: tx) {
                reload()
                editingTransaction = nil
            }
        }
    }

    private var filteredTransactions: [TransactionRecord] {
        var result = transactions.value
        if let accountID = accountFilter.value {
            result = result.filter { $0.account_id == accountID }
        }
        if onlyLast30Days.value {
            let cutoff = DateFormatter.isoDate.string(from: Calendar.current.date(byAdding: .day, value: -30, to: Date())!)
            result = result.filter { $0.date >= cutoff }
        }
        return result
    }

    private struct TxGroup { let key: String; let label: String; let items: [TransactionRecord] }

    /// Nach Datum gruppiert, "Heute" / "Gestern" / ausgeschriebenes Datum.
    private var groupedTransactions: [TxGroup] {
        let today = DateFormatter.isoDate.string(from: Date())
        let yesterday = DateFormatter.isoDate.string(from: Calendar.current.date(byAdding: .day, value: -1, to: Date())!)
        let order = filteredTransactions.map(\.date)
        var seen = Set<String>()
        let keys = order.filter { seen.insert($0).inserted }
        return keys.map { key in
            let label: String
            if key == today { label = "Heute" }
            else if key == yesterday { label = "Gestern" }
            else if let d = DateFormatter.isoDate.date(from: key) {
                label = d.formatted(.dateTime.weekday(.wide).day().month(.wide).year())
            } else { label = key }
            return TxGroup(key: key, label: label, items: filteredTransactions.filter { $0.date == key })
        }
    }

    private func reload() {
        let db = AppDatabase.shared
        transactions.value = (try? db.read { db in
            try TransactionRecord.order(Column("date").desc).fetchAll(db)
        }) ?? []
        let accounts = (try? db.read { db in try Account.fetchAll(db) }) ?? []
        accountsByID.value = Dictionary(uniqueKeysWithValues: accounts.map { ($0.id, $0) })
    }
}

/// Neue Buchung anlegen - dieselbe Offline-Logik wie beim macOS-Client
/// (SyncEngine.createTransactionOffline, siehe dort für die Begründung der
/// Platzhalter-ID), nur die Formularoberfläche ist iOS-eigen.
struct NewTransactionSheet: View {
    let accounts: [Account]
    let onSaved: () -> Void

    @StateObject private var accountID = Box<Int64?>(nil)
    @StateObject private var amountText = Box("")
    @StateObject private var description = Box("")
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Picker("Konto", selection: accountID.binding) {
                    ForEach(accounts) { a in Text(a.name).tag(a.id as Int64?) }
                }
                TextField("Betrag (negativ = Ausgabe)", text: amountText.binding)
                    .keyboardType(.numbersAndPunctuation)
                TextField("Beschreibung", text: description.binding)
            }
            .navigationTitle("Neue Buchung")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Abbrechen") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Speichern") { save() }
                        .disabled(accountID.value == nil || parsedAmount == nil)
                }
            }
            .onAppear { if accountID.value == nil { accountID.value = accounts.first?.id } }
        }
    }

    private var parsedAmount: Double? {
        Double(amountText.value.replacingOccurrences(of: ",", with: "."))
    }

    private func save() {
        guard let accID = accountID.value, let amount = parsedAmount else { return }
        let today = DateFormatter.isoDate.string(from: Date())
        try? SyncEngine.shared.createTransactionOffline(
            accountID: accID, date: today, amount: amount,
            description: description.value.isEmpty ? nil : description.value
        )
        onSaved()
        dismiss()
    }
}

/// Betrag/Beschreibung einer bestehenden Buchung grob bearbeiten (Konto/
/// Datum/Kategorie bleiben unangetastet - dafür bleibt die Web-App der Ort,
/// siehe SyncEngine.updateTransactionOffline-Kommentar).
struct EditTransactionSheet: View {
    let transaction: TransactionRecord
    let onSaved: () -> Void

    @State private var amountText: String
    @State private var description: String
    @Environment(\.dismiss) private var dismiss

    init(transaction: TransactionRecord, onSaved: @escaping () -> Void) {
        self.transaction = transaction
        self.onSaved = onSaved
        _amountText = State(initialValue: String(transaction.amount).replacingOccurrences(of: ".", with: ","))
        _description = State(initialValue: transaction.description ?? "")
    }

    var body: some View {
        NavigationStack {
            Form {
                TextField("Betrag (negativ = Ausgabe)", text: $amountText)
                    .keyboardType(.numbersAndPunctuation)
                TextField("Beschreibung", text: $description)
            }
            .navigationTitle("Buchung bearbeiten")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Abbrechen") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Speichern") { save() }
                        .disabled(parsedAmount == nil)
                }
            }
        }
    }

    private var parsedAmount: Double? {
        Double(amountText.replacingOccurrences(of: ",", with: "."))
    }

    private func save() {
        guard let amount = parsedAmount else { return }
        try? SyncEngine.shared.updateTransactionOffline(
            id: transaction.id, amount: amount, description: description.isEmpty ? nil : description
        )
        onSaved()
        dismiss()
        Task { await SyncEngine.shared.run() }
    }
}

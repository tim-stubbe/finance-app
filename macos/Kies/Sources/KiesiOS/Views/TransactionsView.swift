import SwiftUI
import KiesCore
import GRDB

/// Buchungsliste mit grobem Filter (Konto, "nur letzte 30 Tage") - kein
/// vollständiger Filter-/Suchapparat wie in der Web-App, das ist für die
/// erste iOS-Scheibe bewusst zu viel (siehe ROADMAP.md).
struct TransactionsView: View {
    @ObservedObject var engine = SyncEngine.shared
    @ObservedObject private var transactions = Box<[TransactionRecord]>([])
    @ObservedObject private var accountsByID = Box<[Int64: Account]>([:])
    @ObservedObject private var accountFilter = Box<Int64?>(nil)
    @ObservedObject private var onlyLast30Days = Box(false)
    @ObservedObject private var showNewSheet = Box(false)

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

            if filteredTransactions.isEmpty {
                ContentUnavailableView("Keine Buchungen", systemImage: "list.bullet.rectangle", description: Text("Noch keine Buchungen synchronisiert oder Filter zu eng."))
            }
            Section {
                ForEach(filteredTransactions) { tx in
                    HStack {
                        VStack(alignment: .leading) {
                            Text(tx.description ?? "–")
                            Text(accountsByID.value[tx.account_id]?.name ?? "Konto \(tx.account_id)")
                                .font(.caption).foregroundStyle(.secondary)
                            if tx.pending_client_id != nil {
                                Text("wird synchronisiert…").font(.caption2).foregroundStyle(.orange)
                            }
                        }
                        Spacer()
                        Text(tx.amount, format: .currency(code: "EUR"))
                            .foregroundStyle(tx.amount < 0 ? Color.primary : Color.green)
                    }
                }
            }
        }
        .navigationTitle("Buchungen")
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

    @ObservedObject private var accountID = Box<Int64?>(nil)
    @ObservedObject private var amountText = Box("")
    @ObservedObject private var description = Box("")
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

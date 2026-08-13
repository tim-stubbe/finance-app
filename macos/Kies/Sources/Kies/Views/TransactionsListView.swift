import SwiftUI
import GRDB

struct TransactionsListView: View {
    @ObservedObject var engine = SyncEngine.shared
    @ObservedObject private var transactions = Box<[TransactionRecord]>([])
    @ObservedObject private var accountsByID = Box<[Int64: Account]>([:])
    @ObservedObject private var showNewSheet = Box(false)

    var body: some View {
        List(transactions.value) { (tx: TransactionRecord) in
            HStack {
                VStack(alignment: .leading) {
                    Text(tx.description ?? "–").font(.body)
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
        .navigationTitle("Buchungen")
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .toolbar {
            ToolbarItem { Button { showNewSheet.value = true } label: { Label("Neu", systemImage: "plus") } }
            ToolbarItem {
                Button {
                    Task { await engine.run() }
                } label: {
                    if engine.isSyncing {
                        ProgressView().controlSize(.small)
                    } else {
                        Label("Sync", systemImage: "arrow.triangle.2.circlepath")
                    }
                }
                .disabled(engine.isSyncing)
            }
        }
        .sheet(isPresented: showNewSheet.binding) {
            NewTransactionSheet(accounts: Array(accountsByID.value.values)) {
                reload()
                showNewSheet.value = false
            }
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

struct NewTransactionSheet: View {
    let accounts: [Account]
    let onSaved: () -> Void

    @ObservedObject private var accountID = Box<Int64?>(nil)
    @ObservedObject private var amountText = Box("")
    @ObservedObject private var description = Box("")
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Neue Buchung").font(.headline)
            Picker("Konto", selection: accountID.binding) {
                ForEach(accounts) { a in Text(a.name).tag(a.id as Int64?) }
            }
            TextField("Betrag (negativ = Ausgabe)", text: amountText.binding)
            TextField("Beschreibung", text: description.binding)
            HStack {
                Button("Abbrechen") { dismiss() }
                Spacer()
                Button("Speichern") {
                    guard let accID = accountID.value, let amount = Double(amountText.value.replacingOccurrences(of: ",", with: ".")) else { return }
                    let today = ISO8601DateFormatter().string(from: Date()).prefix(10)
                    try? SyncEngine.shared.createTransactionOffline(
                        accountID: accID, date: String(today), amount: amount,
                        description: description.value.isEmpty ? nil : description.value
                    )
                    onSaved()
                    dismiss()
                }
                .buttonStyle(.borderedProminent)
                .disabled(accountID.value == nil || Double(amountText.value.replacingOccurrences(of: ",", with: ".")) == nil)
            }
        }
        .padding(24)
        .frame(minWidth: 360)
        .onAppear { if accountID.value == nil { accountID.value = accounts.first?.id } }
    }
}

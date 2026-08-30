import SwiftUI
import KiesCore
import GRDB

/// 2026 transaction feed: fast filters, clean rows and native swipe actions.
struct TransactionsView: View {
    @ObservedObject var engine = SyncEngine.shared
    @StateObject private var transactions = Box<[TransactionRecord]>([])
    @StateObject private var accountsByID = Box<[Int64: Account]>([:])
    @StateObject private var accountFilter = Box<Int64?>(nil)
    @StateObject private var onlyLast30Days = Box(false)
    @StateObject private var showNewSheet = Box(false)
    @State private var editingTransaction: TransactionRecord?
    @State private var search = ""

    var body: some View {
        KScreen(spacing: KSpacing.lg) {
            header
            filterBar
            transactionList
        }
        .toolbar { SyncStatusToolbarItem() }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
        .sheet(isPresented: showNewSheet.binding) {
            NewTransactionSheet(accounts: Array(accountsByID.value.values).sorted { $0.name < $1.name }) { reload(); showNewSheet.value = false }
        }
        .sheet(item: $editingTransaction) { tx in
            EditTransactionSheet(transaction: tx) { reload(); editingTransaction = nil }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            KKicker(text: "Aktivität")
            HStack(alignment: .lastTextBaseline) {
                Text("Buchungen").font(KFont.title).foregroundStyle(KColor.primary)
                Spacer()
                Button { showNewSheet.value = true } label: {
                    Image(systemName: "plus").font(.headline.weight(.bold)).foregroundStyle(KColor.accentInk)
                        .frame(width: 40, height: 40).background(KColor.accent, in: Circle())
                }
            }
            Text("Alles, was auf deinen Konten passiert.").font(.subheadline).foregroundStyle(KColor.secondary)
        }
    }

    private var filterBar: some View {
        VStack(spacing: KSpacing.sm) {
            HStack(spacing: 10) {
                Image(systemName: "magnifyingglass").foregroundStyle(KColor.secondary)
                TextField("Buchungen suchen", text: $search)
                    .textInputAutocapitalization(.never)
                if !search.isEmpty { Button { search = "" } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(KColor.tertiary) } }
            }
            .padding(.horizontal, 14).padding(.vertical, 12)
            .background(KColor.surface, in: Capsule())
            .overlay(Capsule().stroke(KColor.divider, lineWidth: 1))

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 7) {
                    NeonPill(title: "Alle", active: accountFilter.value == nil)
                        .onTapGesture { accountFilter.value = nil }
                    ForEach(Array(accountsByID.value.values).sorted { $0.name < $1.name }) { account in
                        NeonPill(title: account.name, active: accountFilter.value == account.id)
                            .onTapGesture { accountFilter.value = account.id }
                    }
                    NeonPill(title: "30 Tage", active: onlyLast30Days.value)
                        .onTapGesture { onlyLast30Days.value.toggle() }
                }
            }
        }
    }

    private var transactionList: some View {
        VStack(alignment: .leading, spacing: KSpacing.md) {
            if filteredTransactions.isEmpty {
                KEmptyState(icon: "list.bullet.rectangle", title: "Keine Buchungen", message: "Keine Buchungen passen zu deiner Suche oder deinem Filter.")
            } else {
                ForEach(groupedTransactions, id: \.key) { group in
                    VStack(alignment: .leading, spacing: KSpacing.sm) {
                        Text(group.label).font(.caption.weight(.bold)).foregroundStyle(KColor.secondary)
                        VStack(spacing: 0) {
                            ForEach(group.items) { tx in
                                Button { if tx.id >= 0 { editingTransaction = tx } } label: {
                                    KTransactionRow(title: tx.description ?? "Buchung", subtitle: accountsByID.value[tx.account_id]?.name, amount: tx.amount, pending: tx.pending_client_id != nil)
                                }
                                .buttonStyle(.plain)
                                .contextMenu {
                                    if tx.id >= 0 { Button("Bearbeiten") { editingTransaction = tx } }
                                }
                                if tx.id != group.items.last?.id { Divider().overlay(KColor.divider) }
                            }
                        }
                        .padding(.horizontal, KSpacing.md)
                        .background(KColor.surface.opacity(0.96), in: RoundedRectangle(cornerRadius: KRadius.md, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: KRadius.md, style: .continuous).stroke(KColor.divider, lineWidth: 1))
                    }
                }
            }
        }
    }

    private var filteredTransactions: [TransactionRecord] {
        var result = transactions.value
        if let accountID = accountFilter.value { result = result.filter { $0.account_id == accountID } }
        if onlyLast30Days.value {
            let cutoff = DateFormatter.isoDate.string(from: Calendar.current.date(byAdding: .day, value: -30, to: Date())!)
            result = result.filter { $0.date >= cutoff }
        }
        if !search.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            let q = search.lowercased()
            result = result.filter { ($0.description ?? "").lowercased().contains(q) || (accountsByID.value[$0.account_id]?.name.lowercased().contains(q) ?? false) }
        }
        return result
    }

    private struct TxGroup { let key: String; let label: String; let items: [TransactionRecord] }
    private var groupedTransactions: [TxGroup] {
        let today = DateFormatter.isoDate.string(from: Date())
        let yesterday = DateFormatter.isoDate.string(from: Calendar.current.date(byAdding: .day, value: -1, to: Date())!)
        var seen = Set<String>()
        let keys = filteredTransactions.map(\.date).filter { seen.insert($0).inserted }
        return keys.map { key in
            let label: String
            if key == today { label = "Heute" }
            else if key == yesterday { label = "Gestern" }
            else if let d = DateFormatter.isoDate.date(from: key) { label = d.formatted(.dateTime.weekday(.wide).day().month(.wide)) }
            else { label = key }
            return TxGroup(key: key, label: label, items: filteredTransactions.filter { $0.date == key })
        }
    }

    private func reload() {
        let db = AppDatabase.shared
        transactions.value = (try? db.read { db in try TransactionRecord.order(Column("date").desc).fetchAll(db) }) ?? []
        let accounts = (try? db.read { db in try Account.fetchAll(db) }) ?? []
        accountsByID.value = Dictionary(uniqueKeysWithValues: accounts.map { ($0.id, $0) })
    }
}

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
                Picker("Konto", selection: accountID.binding) { ForEach(accounts) { Text($0.name).tag($0.id as Int64?) } }
                TextField("Betrag (negativ = Ausgabe)", text: amountText.binding).keyboardType(.numbersAndPunctuation)
                TextField("Beschreibung", text: description.binding)
            }
            .navigationTitle("Neue Buchung")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Abbrechen") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("Speichern") { save() }.disabled(accountID.value == nil || parsedAmount == nil) }
            }
            .onAppear { if accountID.value == nil { accountID.value = accounts.first?.id } }
        }
    }

    private var parsedAmount: Double? { Double(amountText.value.replacingOccurrences(of: ",", with: ".")) }
    private func save() {
        guard let accID = accountID.value, let amount = parsedAmount else { return }
        try? SyncEngine.shared.createTransactionOffline(accountID: accID, date: DateFormatter.isoDate.string(from: Date()), amount: amount, description: description.value.isEmpty ? nil : description.value)
        onSaved(); dismiss()
    }
}

struct EditTransactionSheet: View {
    let transaction: TransactionRecord
    let onSaved: () -> Void
    @State private var amountText: String
    @State private var description: String
    @Environment(\.dismiss) private var dismiss

    init(transaction: TransactionRecord, onSaved: @escaping () -> Void) {
        self.transaction = transaction; self.onSaved = onSaved
        _amountText = State(initialValue: String(transaction.amount).replacingOccurrences(of: ".", with: ","))
        _description = State(initialValue: transaction.description ?? "")
    }

    var body: some View {
        NavigationStack {
            Form {
                TextField("Betrag (negativ = Ausgabe)", text: $amountText).keyboardType(.numbersAndPunctuation)
                TextField("Beschreibung", text: $description)
            }
            .navigationTitle("Buchung bearbeiten")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Abbrechen") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("Speichern") { save() }.disabled(parsedAmount == nil) }
            }
        }
    }

    private var parsedAmount: Double? { Double(amountText.replacingOccurrences(of: ",", with: ".")) }
    private func save() {
        guard let amount = parsedAmount else { return }
        try? SyncEngine.shared.updateTransactionOffline(id: transaction.id, amount: amount, description: description.isEmpty ? nil : description)
        onSaved(); dismiss(); Task { await SyncEngine.shared.run() }
    }
}

import SwiftUI
import GRDB
import KiesCore

/// Kategorien: lesend + umbenennen (kein Anlegen/Löschen/Typ-Ändern in
/// dieser iOS-Scheibe, dafür bleibt die Web-App der Ort).
/// `KiesCore.Category` explizit qualifiziert - der bloße Name "Category"
/// ist im iOS-SDK mehrdeutig (kollidiert mit einem Systemtyp, der unter
/// macOS nicht sichtbar war - dort compilierte derselbe Typname anstandslos).
struct CategoriesView: View {
    @ObservedObject var engine = SyncEngine.shared
    @ObservedObject private var categories = Box<[KiesCore.Category]>([])
    @State private var editingCategory: KiesCore.Category?
    @State private var editedName = ""

    var body: some View {
        List {
            if categories.value.isEmpty {
                ContentUnavailableView("Keine Kategorien", systemImage: "tag", description: Text("Wird beim nächsten Sync geladen."))
            }
            ForEach(categories.value) { category in
                HStack {
                    Text(category.name)
                    Spacer()
                    Text(category.type).font(.caption).foregroundStyle(.secondary)
                }
                .swipeActions(edge: .trailing) {
                    Button {
                        editingCategory = category
                        editedName = category.name
                    } label: {
                        Label("Umbenennen", systemImage: "pencil")
                    }
                    .tint(.blue)
                }
            }
        }
        .navigationTitle("Kategorien")
        .toolbar { SyncStatusToolbarItem() }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
        .sheet(item: $editingCategory) { category in
            NavigationStack {
                Form {
                    TextField("Name", text: $editedName)
                }
                .navigationTitle("Umbenennen")
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Abbrechen") { editingCategory = nil }
                    }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Speichern") { save(category) }
                            .disabled(editedName.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
            }
        }
    }

    private func reload() {
        categories.value = (try? AppDatabase.shared.read { db in
            try KiesCore.Category.order(Column("name")).fetchAll(db)
        }) ?? []
    }

    private func save(_ category: KiesCore.Category) {
        let name = editedName.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }
        try? SyncEngine.shared.renameCategoryOffline(id: category.id, name: name)
        editingCategory = nil
        reload()
        Task { await SyncEngine.shared.run() }
    }
}

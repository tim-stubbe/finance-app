import SwiftUI
import KiesCore
import GRDB

/// Kategorien: lesend + umbenennen - analog zu
/// KiesiOS/Views/CategoriesView.swift (kein Anlegen/Löschen/Typ-Ändern,
/// dafür bleibt die Web-App der Ort).
/// `KiesCore.Category` explizit qualifiziert - der bloße Name "Category"
/// ist im neueren macOS-SDK mehrdeutig (objc/runtime.h definiert ebenfalls
/// einen Typ namens "Category").
struct CategoriesListView: View {
    @ObservedObject var engine = SyncEngine.shared
    @ObservedObject private var categories = Box<[KiesCore.Category]>([])
    @ObservedObject private var editingID = Box<Int64?>(nil)
    @ObservedObject private var editedName = Box("")

    var body: some View {
        List(categories.value) { (category: KiesCore.Category) in
            HStack {
                if editingID.value == category.id {
                    TextField("Name", text: editedName.binding)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit { save(category) }
                    Button("Speichern") { save(category) }
                        .disabled(editedName.value.trimmingCharacters(in: .whitespaces).isEmpty)
                    Button("Abbrechen") { editingID.value = nil }
                } else {
                    Text(category.name)
                    Spacer()
                    Text(category.type).font(.caption).foregroundStyle(.secondary)
                    Button {
                        editingID.value = category.id
                        editedName.value = category.name
                    } label: {
                        Image(systemName: "pencil")
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .navigationTitle("Kategorien")
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .toolbar {
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
    }

    private func reload() {
        categories.value = (try? AppDatabase.shared.read { db in
            try KiesCore.Category.order(Column("name")).fetchAll(db)
        }) ?? []
    }

    private func save(_ category: KiesCore.Category) {
        let name = editedName.value.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }
        try? SyncEngine.shared.renameCategoryOffline(id: category.id, name: name)
        editingID.value = nil
        reload()
        Task { await SyncEngine.shared.run() }
    }
}

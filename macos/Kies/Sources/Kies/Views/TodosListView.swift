import SwiftUI
import KiesCore
import GRDB

struct TodosListView: View {
    @ObservedObject var engine = SyncEngine.shared
    @ObservedObject private var todos = Box<[Todo]>([])
    @ObservedObject private var newTitle = Box("")

    var body: some View {
        VStack(spacing: 0) {
            List(todos.value) { (todo: Todo) in
                HStack {
                    Button {
                        toggle(todo)
                    } label: {
                        Image(systemName: todo.done ? "checkmark.circle.fill" : "circle")
                            .foregroundStyle(todo.done ? Color.green : Color.secondary)
                    }
                    .buttonStyle(.plain)
                    .disabled(todo.id < 0)

                    VStack(alignment: .leading) {
                        Text(todo.title)
                            .strikethrough(todo.done)
                            .foregroundStyle(todo.done ? Color.secondary : Color.primary)
                        if todo.id < 0 {
                            Text("wird synchronisiert…").font(.caption2).foregroundStyle(.orange)
                        } else if let due = todo.due_date {
                            Text("fällig \(due)").font(.caption2).foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                }
            }
            Divider()
            HStack {
                TextField("Neues To-Do…", text: newTitle.binding)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { addTodo() }
                Button("Hinzufügen") { addTodo() }
                    .disabled(newTitle.value.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .padding(8)
        }
        .navigationTitle("Todos")
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

    private func addTodo() {
        let title = newTitle.value.trimmingCharacters(in: .whitespaces)
        guard !title.isEmpty else { return }
        try? SyncEngine.shared.createTodoOffline(title: title, dueDate: nil)
        newTitle.value = ""
        reload()
    }

    private func toggle(_ todo: Todo) {
        guard todo.id > 0 else { return }
        try? SyncEngine.shared.setTodoDoneOffline(id: todo.id, done: !todo.done)
        reload()
    }

    private func reload() {
        todos.value = (try? AppDatabase.shared.read { db in
            try Todo.filter(Column("done") == false).order(Column("created_at").desc).fetchAll(db)
        }) ?? []
    }
}

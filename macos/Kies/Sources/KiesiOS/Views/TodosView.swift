import SwiftUI
import KiesCore
import GRDB

/// Todo-Liste - abhaken (nur für bereits synchronisierte Todos, siehe
/// SyncEngine.setTodoDoneOffline-Kommentar) und neue anlegen. Überfällige
/// Todos (due_date in der Vergangenheit) werden rot hervorgehoben statt
/// separat "markiert" - eine eigene Mutation dafür gäbe es serverseitig
/// nicht und wäre für diese erste Scheibe unnötige Komplexität.
struct TodosView: View {
    @ObservedObject var engine = SyncEngine.shared
    @StateObject private var todos = Box<[Todo]>([])
    @StateObject private var newTitle = Box("")

    var body: some View {
        List {
            if todos.value.isEmpty {
                ContentUnavailableView("Nichts offen", systemImage: "checklist", description: Text("Noch keine Todos synchronisiert oder alles erledigt."))
            }
            Section {
                ForEach(todos.value) { todo in
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
                                Text("fällig \(due)")
                                    .font(.caption2)
                                    .foregroundStyle(isOverdue(due) ? Color.red : Color.secondary)
                            }
                        }
                        Spacer()
                    }
                    .swipeActions(edge: .trailing) {
                        Button {
                            toggle(todo)
                        } label: {
                            Label("Erledigt", systemImage: "checkmark")
                        }
                        .tint(.green)
                        .disabled(todo.id < 0)
                    }
                }
            }
            Section {
                HStack {
                    TextField("Neues To-Do…", text: newTitle.binding)
                        .onSubmit { addTodo() }
                    Button("Hinzufügen") { addTodo() }
                        .disabled(newTitle.value.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
        .navigationTitle("Todos")
        .toolbar { SyncStatusToolbarItem() }
        .task { reload() }
        .onChange(of: engine.lastSyncedAt) { _, _ in reload() }
        .refreshable { await engine.run() }
    }

    private func isOverdue(_ due: String) -> Bool {
        due < DateFormatter.isoDate.string(from: Date())
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

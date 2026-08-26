// ================= NOTIZEN (kontextbezogen) =================
// Ein generisches Modal statt eines eigenen Notizfelds pro Objekt - siehe
// models.Note. entity_type "search" ist ein virtueller Modus: kein neues
// Objekt, sondern die globale Volltextsuche über alle Notizen.
const NOTE_ENTITY_LABELS = {
  goal: "Ziel", todo: "To-Do", business_project: "Projekt",
  life_area: "Lebensbereich", schweiz: "Schweiz-Tab",
};
const NOTE_ENTITY_JUMP = { goal: "goals", todo: "goals", business_project: "projects", life_area: "life", schweiz: "schweiz" };
let notesModalState = { entityType: null, entityId: null };

async function openNotesModal(entityType, entityId, label) {
  notesModalState = { entityType, entityId };
  document.getElementById("notes-modal-title").textContent = `Notizen – ${label}`;
  document.getElementById("notes-add-form").classList.remove("hidden");
  document.getElementById("notes-add-text").value = "";
  document.getElementById("notes-modal").classList.remove("hidden");
  await renderNotesList();
}

async function renderNotesList() {
  const list = document.getElementById("notes-modal-list");
  list.innerHTML = `<p class="page-sub">Lade …</p>`;
  const { entityType, entityId } = notesModalState;
  const notes = await api(`/notes?entity_type=${encodeURIComponent(entityType)}&entity_id=${entityId}`);
  if (!notes.length) {
    list.innerHTML = `<p class="page-sub">Noch keine Notizen.</p>`;
    return;
  }
  list.innerHTML = notes.map(n => `
    <div class="todo-row">
      <span class="todo-title" style="white-space:pre-wrap">${esc(n.text)}<br><span class="page-sub">${fmtDateTime(n.created_at)}</span></span>
      <button type="button" class="link-btn" data-note-delete="${n.id}">Löschen</button>
    </div>`).join("");
}

document.getElementById("notes-modal-close").addEventListener("click", () => {
  document.getElementById("notes-modal").classList.add("hidden");
});
document.getElementById("notes-add-form").addEventListener("submit", async e => {
  e.preventDefault();
  const textEl = document.getElementById("notes-add-text");
  const text = textEl.value.trim();
  if (!text) return;
  await api("/notes", {
    method: "POST",
    body: JSON.stringify({ entity_type: notesModalState.entityType, entity_id: notesModalState.entityId, text }),
  });
  textEl.value = "";
  await renderNotesList();
});
document.getElementById("notes-modal-list").addEventListener("click", async e => {
  const id = e.target.closest("[data-note-delete]")?.dataset.noteDelete;
  if (!id) return;
  await api(`/notes/${id}`, { method: "DELETE" });
  await renderNotesList();
});

// Delegierter, globaler Klick-Handler statt einer Bindung je Tab - Notiz-
// Buttons tauchen an vielen verschiedenen Stellen auf (Ziele, To-Dos,
// Projekte, Lebensbereiche, Schweiz-Tab), die alle unabhängig neu gerendert
// werden.
document.addEventListener("click", e => {
  const btn = e.target.closest("[data-notes-entity]");
  if (!btn) return;
  openNotesModal(btn.dataset.notesEntity, parseInt(btn.dataset.notesId, 10), btn.dataset.notesLabel);
});

// Globale Notizsuche über die Command-Palette - eigener Suchmodus statt eines
// zusätzlichen Suchfelds irgendwo im UI, passend zur bestehenden ⌘K-Konvention.
async function openNotesSearchModal() {
  document.getElementById("notes-modal-title").textContent = "Notizen durchsuchen";
  document.getElementById("notes-add-form").classList.add("hidden");
  const list = document.getElementById("notes-modal-list");
  list.innerHTML = `
    <input type="text" id="notes-search-input" placeholder="Suchbegriff (mind. 2 Zeichen) …" style="width:100%;margin-bottom:10px">
    <div id="notes-search-results"></div>`;
  document.getElementById("notes-modal").classList.remove("hidden");
  const input = document.getElementById("notes-search-input");
  input.focus();
  const runSearch = async () => {
    const q = input.value.trim();
    const results = document.getElementById("notes-search-results");
    if (q.length < 2) {
      results.innerHTML = `<p class="page-sub">Mindestens 2 Zeichen eingeben.</p>`;
      return;
    }
    results.innerHTML = `<p class="page-sub">Suche …</p>`;
    const hits = await api(`/notes/search?q=${encodeURIComponent(q)}`);
    results.innerHTML = hits.length
      ? hits.map(n => `
        <button type="button" class="hub-list-row" data-note-jump="${n.entity_type}" style="display:block;text-align:left">
          <strong>${esc(NOTE_ENTITY_LABELS[n.entity_type] || n.entity_type)}${n.entity_label ? `: ${esc(n.entity_label)}` : ""}</strong>
          <div class="page-sub" style="white-space:pre-wrap">${esc(n.text)}</div>
        </button>`).join("")
      : `<p class="page-sub">Keine Notizen gefunden.</p>`;
  };
  input.addEventListener("input", runSearch);
  document.getElementById("notes-search-results").addEventListener("click", e => {
    const type = e.target.closest("[data-note-jump]")?.dataset.noteJump;
    if (!type) return;
    document.getElementById("notes-modal").classList.add("hidden");
    goToTab(NOTE_ENTITY_JUMP[type] || "hub");
  });
}
CMDK_ACTIONS.push({ label: "Notizen durchsuchen", icon: "file-text", run: openNotesSearchModal });
CMDK_ACTIONS.push({ label: "KI-Vorschläge prüfen", icon: "sparkles", run: () => goToTab("ai") });

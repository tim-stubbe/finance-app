// ================= SETTINGS: ENABLE BANKING =================
async function loadEnableBankingSettings() {
  const s = await api("/settings/enablebanking");
  document.getElementById("eb-app-id").value = s.app_id || "";
  document.getElementById("eb-redirect-base").value = s.redirect_base_url || "";
  document.getElementById("eb-key-status").textContent = s.private_key_set
    ? "Privater Schlüssel ist hinterlegt (wird aus Sicherheitsgründen nicht wieder angezeigt)."
    : "Noch kein privater Schlüssel hinterlegt.";
  const base = s.redirect_base_url || location.origin;
  document.getElementById("eb-redirect-hint").textContent = base + "/api/enablebanking/callback";
}

document.getElementById("eb-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const app_id = document.getElementById("eb-app-id").value;
  const private_key = document.getElementById("eb-private-key").value;
  const redirect_base_url = document.getElementById("eb-redirect-base").value.trim();
  if (!private_key.trim()) {
    alert("Bitte den privaten Schlüssel (PEM) einfügen.");
    return;
  }
  await api("/settings/enablebanking", { method: "PUT", body: JSON.stringify({ app_id, private_key, redirect_base_url: redirect_base_url || null }) });
  document.getElementById("eb-private-key").value = "";
  loadEnableBankingSettings();
  toast("Enable-Banking-Zugang gespeichert.");
});

document.getElementById("eb-load-banks").addEventListener("click", async () => {
  const country = document.getElementById("eb-country").value;
  const sel = document.getElementById("eb-aspsp");
  sel.innerHTML = '<option value="">Lädt …</option>';
  try {
    const aspsps = await api(`/enablebanking/aspsps?country=${country}`);
    sel.innerHTML = "";
    if (aspsps.length === 0) sel.innerHTML = '<option value="">Keine Banken gefunden</option>';
    aspsps.forEach(a => {
      const opt = document.createElement("option");
      opt.value = a.name; opt.dataset.country = a.country; opt.textContent = a.name;
      sel.appendChild(opt);
    });
  } catch (e) {
    sel.innerHTML = '<option value="">Fehler beim Laden</option>';
  }
});

function populateEbAccountSelect() {
  const sel = document.getElementById("eb-account");
  sel.innerHTML = "";
  accountsCache.forEach(a => {
    const opt = document.createElement("option");
    opt.value = a.id; opt.textContent = a.name;
    sel.appendChild(opt);
  });
}

const EB_STATUS_LABELS = { pending: "Autorisierung ausstehend", linked: "Verbunden", error: "Fehler" };

async function loadEnableBankingConnections() {
  if (!accountsCache.length) await loadAccounts();
  populateEbAccountSelect();
  const conns = await api("/enablebanking/connections");
  const tbody = document.getElementById("eb-conn-list");
  tbody.innerHTML = "";
  if (conns.length === 0) {
    tbody.innerHTML = emptyRow(4, "landmark", "Noch keine Verbindung angelegt.");
  }
  conns.forEach(c => {
    const tr = document.createElement("tr");
    const lastSync = c.last_sync_at ? new Date(c.last_sync_at).toLocaleString("de-DE") : "noch nie";
    tr.innerHTML = `
      <td>${c.aspsp_name} (${c.aspsp_country})</td>
      <td>${EB_STATUS_LABELS[c.status] || c.status}${c.last_sync_status ? `<br><span class="page-sub">${c.last_sync_status}</span>` : ""}</td>
      <td>${lastSync}</td>
      <td>
        ${c.status === "linked" ? `<button class="link-btn" onclick="syncEbConnection(${c.id})">Jetzt synchronisieren</button>` : ""}
        <button class="link-btn" onclick="deleteEbConnection(${c.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });
}

document.getElementById("eb-conn-form").addEventListener("submit", async e => {
  e.preventDefault();
  const sel = document.getElementById("eb-aspsp");
  const opt = sel.selectedOptions[0];
  if (!opt || !opt.value) { alert("Bitte zuerst Banken laden und eine Bank auswählen."); return; }
  const payload = {
    aspsp_name: opt.value,
    aspsp_country: opt.dataset.country,
    account_id: parseInt(document.getElementById("eb-account").value),
  };
  const result = await api("/enablebanking/connections", { method: "POST", body: JSON.stringify(payload) });
  loadEnableBankingConnections();
  window.open(result.url, "_blank");
});

window.syncEbConnection = async id => {
  const result = await api(`/enablebanking/connections/${id}/sync`, { method: "POST" });
  if (result.error) {
    alert("Sync-Fehler: " + result.error);
  } else {
    alert(`Sync abgeschlossen: ${result.imported} neue Buchung(en), ${result.skipped} bereits vorhanden.`);
    loadTransactions();
    loadAccounts();
  }
  loadEnableBankingConnections();
};

window.deleteEbConnection = async id => {
  if (!confirm("Verbindung wirklich löschen? Bereits importierte Buchungen bleiben erhalten.")) return;
  await api(`/enablebanking/connections/${id}`, { method: "DELETE" });
  loadEnableBankingConnections();
};

function handleEnableBankingReturn() {
  const params = new URLSearchParams(location.search);
  const done = params.get("enablebanking_done");
  const err = params.get("enablebanking_error");
  if (!done && !err) return;
  history.replaceState({}, "", location.pathname);
  const settingsBtn = document.querySelector('.nav-btn[data-tab="settings"]');
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
  settingsBtn.classList.add("active");
  document.getElementById("tab-settings").classList.add("active");
  moveNavIndicator(settingsBtn);
  loadSettingsTab().then(() => {
    if (err) alert("Enable-Banking-Autorisierung fehlgeschlagen: " + err);
  });
}

// ---------- eBay ----------
async function loadEbaySettings() {
  const s = await api("/settings/ebay");
  document.getElementById("ebay-app-id").value = s.app_id || "";
  document.getElementById("ebay-ru-name").value = s.ru_name || "";
  document.getElementById("ebay-key-status").textContent = s.cert_id_set
    ? "Cert-ID ist hinterlegt (wird aus Sicherheitsgründen nicht wieder angezeigt)."
    : "Noch keine Cert-ID hinterlegt.";
  document.getElementById("ebay-redirect-hint").textContent = location.origin + "/api/ebay/callback";
}

document.getElementById("ebay-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const app_id = document.getElementById("ebay-app-id").value;
  const cert_id = document.getElementById("ebay-cert-id").value;
  const ru_name = document.getElementById("ebay-ru-name").value;
  if (!cert_id.trim()) {
    alert("Bitte die Cert-ID (Client-Secret) eingeben.");
    return;
  }
  await api("/settings/ebay", { method: "PUT", body: JSON.stringify({ app_id, cert_id, ru_name }) });
  document.getElementById("ebay-cert-id").value = "";
  loadEbaySettings();
  toast("eBay-Zugang gespeichert.");
});

function populateEbayAccountSelect() {
  const sel = document.getElementById("ebay-account");
  sel.innerHTML = "";
  accountsCache.forEach(a => {
    const opt = document.createElement("option");
    opt.value = a.id; opt.textContent = a.name;
    sel.appendChild(opt);
  });
}

const EBAY_STATUS_LABELS = { pending: "Autorisierung ausstehend", connected: "Verbunden", error: "Fehler" };

async function loadEbayConnections() {
  if (!accountsCache.length) await loadAccounts();
  populateEbayAccountSelect();
  const conns = await api("/ebay/connections");
  const tbody = document.getElementById("ebay-conn-list");
  tbody.innerHTML = "";
  if (conns.length === 0) {
    tbody.innerHTML = emptyRow(4, "shopping-cart", "Noch keine Verbindung angelegt.");
  }
  conns.forEach(c => {
    const account = accountsCache.find(a => a.id === c.account_id);
    const lastSync = c.last_sync_at ? new Date(c.last_sync_at).toLocaleString("de-DE") : "noch nie";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${account ? esc(account.name) : c.account_id}</td>
      <td>${EBAY_STATUS_LABELS[c.status] || c.status}${c.last_sync_status ? `<br><span class="page-sub">${esc(c.last_sync_status)}</span>` : ""}</td>
      <td>${lastSync}</td>
      <td>
        ${c.status === "connected" ? `<button class="link-btn" onclick="syncEbayConnection(${c.id})">Jetzt synchronisieren</button>` : ""}
        <button class="link-btn" onclick="deleteEbayConnection(${c.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });
}

document.getElementById("ebay-conn-form").addEventListener("submit", async e => {
  e.preventDefault();
  const payload = { account_id: parseInt(document.getElementById("ebay-account").value) };
  const result = await api("/ebay/connections", { method: "POST", body: JSON.stringify(payload) });
  loadEbayConnections();
  window.open(result.url, "_blank");
});

window.syncEbayConnection = async id => {
  const result = await api(`/ebay/connections/${id}/sync`, { method: "POST" });
  if (result.error) {
    alert("Sync-Fehler: " + result.error);
  } else {
    alert(`Sync abgeschlossen: ${result.imported} neue Buchung(en), ${result.skipped} bereits vorhanden.`);
    loadTransactions();
    loadAccounts();
  }
  loadEbayConnections();
};

window.deleteEbayConnection = async id => {
  if (!confirm("Verbindung wirklich löschen? Bereits importierte Buchungen bleiben erhalten.")) return;
  await api(`/ebay/connections/${id}`, { method: "DELETE" });
  loadEbayConnections();
};

function handleEbayReturn() {
  const params = new URLSearchParams(location.search);
  const done = params.get("ebay_done");
  const err = params.get("ebay_error");
  if (!done && !err) return;
  history.replaceState({}, "", location.pathname);
  const settingsBtn = document.querySelector('.nav-btn[data-tab="settings"]');
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
  settingsBtn.classList.add("active");
  document.getElementById("tab-settings").classList.add("active");
  moveNavIndicator(settingsBtn);
  loadSettingsTab().then(() => {
    if (err) alert("eBay-Autorisierung fehlgeschlagen: " + err);
  });
}

// ---------- Radicale-Einstellungen ----------
async function loadRadicaleSettings() {
  const s = await api("/settings/radicale");
  document.getElementById("radicale-url").value = s.url || "";
  document.getElementById("radicale-username").value = s.username || "";
  document.getElementById("radicale-calendar-url").value = s.calendar_url || "";
  document.getElementById("radicale-status").textContent = s.password_set
    ? "Zugangsdaten sind hinterlegt (Passwort wird aus Sicherheitsgründen nicht wieder angezeigt)."
    : "Noch keine Zugangsdaten hinterlegt.";
}

document.getElementById("radicale-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const url = document.getElementById("radicale-url").value.trim();
  const username = document.getElementById("radicale-username").value.trim();
  const password = document.getElementById("radicale-password").value;
  const calendar_url = document.getElementById("radicale-calendar-url").value.trim();
  if (!url || !password) {
    alert("Bitte Adresse und Passwort eingeben.");
    return;
  }
  await api("/settings/radicale", { method: "PUT", body: JSON.stringify({ url, username, password, calendar_url }) });
  document.getElementById("radicale-password").value = "";
  loadRadicaleSettings();
  toast("Radicale-Zugang gespeichert.");
});

document.getElementById("radicale-test").addEventListener("click", async () => {
  const statusEl = document.getElementById("radicale-status");
  statusEl.textContent = "Teste Verbindung …";
  const r = await api("/radicale/test", { method: "POST" });
  statusEl.textContent = r.ok
    ? `✓ Verbunden – ${r.todo_count} To-Do(s) auf dem Server gefunden.`
    : `✗ ${r.error}`;
});

// ---------- Fahrzeit-Einstellungen ----------
async function loadTravelSettings() {
  const s = await api("/settings/travel");
  document.getElementById("travel-home-address").value = s.home_address || "";
  document.getElementById("travel-api-key").placeholder = s.api_key_set
    ? "gespeichert – leer lassen behält den bisherigen"
    : "wird verschlüsselt gespeichert";
  const status = document.getElementById("travel-status");
  if (!s.home_address) {
    status.textContent = "";
  } else if (!s.home_geocoded) {
    status.textContent = "⚠️ Adresse konnte nicht gefunden werden - bitte prüfen (Straße Hausnummer, PLZ Ort).";
  } else {
    status.textContent = "✓ Adresse gefunden.";
  }
}

document.getElementById("travel-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const body = {
    home_address: document.getElementById("travel-home-address").value.trim(),
    api_key: document.getElementById("travel-api-key").value.trim() || null,
  };
  await api("/settings/travel", { method: "PUT", body: JSON.stringify(body) });
  document.getElementById("travel-api-key").value = "";
  await loadTravelSettings();
  toast("Fahrzeit-Einstellungen gespeichert.");
});

// ---------- To-Dos ----------
let todosCache = [];

async function loadTodos() {
  const list = document.getElementById("todo-list");
  try {
    todosCache = await api("/todos");
  } catch (e) {
    list.innerHTML = `<p class="page-sub">${esc(e.message)}</p>`;
    return;
  }
  renderTodos();
}

function renderTodos() {
  const list = document.getElementById("todo-list");
  if (!todosCache.length) {
    list.innerHTML = `<p class="page-sub">Noch keine To-Dos.</p>`;
    return;
  }
  list.innerHTML = todosCache.map(t => `
    <label class="todo-row ${t.done ? "is-done" : ""}">
      <input type="checkbox" data-todo-toggle="${t.id}" ${t.done ? "checked" : ""}>
      <span class="todo-title">${esc(t.title)}</span>
      ${t.due_date ? `<span class="todo-due">${fmtDate(t.due_date)}</span>` : ""}
      <button type="button" class="link-btn" data-notes-entity="todo" data-notes-id="${t.id}" data-notes-label="${esc(t.title)}">📝</button>
      <button type="button" class="link-btn" data-todo-delete="${t.id}">Löschen</button>
    </label>`).join("");
}

document.getElementById("todo-form").addEventListener("submit", async e => {
  e.preventDefault();
  const titleInput = document.getElementById("todo-title");
  const dueInput = document.getElementById("todo-due-date");
  const title = titleInput.value.trim();
  if (!title) return;
  await api("/todos", { method: "POST", body: JSON.stringify({ title, due_date: dueInput.value || null }) });
  titleInput.value = "";
  dueInput.value = "";
  await loadTodos();
});

document.getElementById("todo-list").addEventListener("click", async e => {
  const delId = e.target.closest("[data-todo-delete]")?.dataset.todoDelete;
  if (delId) {
    await api(`/todos/${delId}`, { method: "DELETE" });
    await loadTodos();
  }
});

document.getElementById("todo-list").addEventListener("change", async e => {
  const toggleId = e.target.closest("[data-todo-toggle]")?.dataset.todoToggle;
  if (toggleId) {
    await api(`/todos/${toggleId}`, { method: "PATCH", body: JSON.stringify({ done: e.target.checked }) });
    await loadTodos();
  }
});


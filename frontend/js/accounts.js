// ================= ACCOUNTS =================
async function loadAccounts() {
  accountsCache = await api("/accounts");
  const tbody = document.getElementById("acc-list");
  tbody.innerHTML = "";
  if (accountsCache.length === 0) {
    tbody.innerHTML = emptyRow(4, "landmark", "Noch keine Konten angelegt. Leg dein erstes Konto an!");
  }
  accountsCache.forEach(a => {
    const tr = document.createElement("tr");
    const icon = ACCOUNT_TYPE_ICONS[a.type] || "folder";
    tr.innerHTML = `<td><span class="row-name"><span class="row-icon">${svgIcon(icon)}</span>${a.name}${a.is_business ? ' <span class="goal-chip">💼 Geschäftlich</span>' : ""}</span></td><td>${a.type}</td>
      <td class="${a.current_balance >= 0 ? "row-amount-pos" : "row-amount-neg"}">${eur(a.current_balance)}</td>
      <td>
        <button class="link-btn" onclick="editAccount(${a.id})">Bearbeiten</button>
        <button class="link-btn" onclick="deleteAccount(${a.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });
  populateAccountSelects();
  loadBalanceLog();
}

async function loadBalanceLog() {
  const panel = document.getElementById("balance-log-panel");
  let log = [];
  try {
    log = await api("/accounts/balance-log");
  } catch (e) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.toggle("hidden", log.length === 0);
  if (!log.length) return;
  const sourceLabel = { app: "App", telegram: "Telegram" };
  document.getElementById("balance-log-list").innerHTML = log.map(l => `
    <tr>
      <td>${esc(l.account_name)}</td>
      <td>${eur(l.old_balance)}</td>
      <td>${eur(l.new_balance)}</td>
      <td>${sourceLabel[l.source] || l.source}</td>
      <td>${new Date(l.created_at).toLocaleString("de-DE")}</td>
    </tr>`).join("");
}

function populateAccountSelects() {
  const selects = [
    document.getElementById("tx-account"),
    document.getElementById("tx-filter-account"),
  ];
  selects.forEach(sel => {
    const keepFirst = sel.id === "tx-filter-account";
    sel.innerHTML = keepFirst ? '<option value="">Alle Konten</option>' : "";
    accountsCache.forEach(a => {
      const opt = document.createElement("option");
      opt.value = a.id; opt.textContent = a.name;
      sel.appendChild(opt);
    });
  });
}

document.getElementById("acc-form").addEventListener("submit", async e => {
  e.preventDefault();
  const payload = {
    name: document.getElementById("acc-name").value,
    type: document.getElementById("acc-type").value,
    is_business: document.getElementById("acc-business").checked,
  };
  if (editingAccId) {
    // Beim Bearbeiten wird statt des Startsaldos der aktuelle Kontostand gezeigt/korrigiert -
    // rechnerisch bleibt initial_balance die Stellschraube (siehe crud.set_balance_by_name).
    const a = accountsCache.find(x => x.id === editingAccId);
    const newCurrentBalance = parseFloat(document.getElementById("acc-current-balance").value || 0);
    payload.initial_balance = round2(a.initial_balance - a.current_balance + newCurrentBalance);
    await api(`/accounts/${editingAccId}`, { method: "PUT", body: JSON.stringify(payload) });
  } else {
    payload.initial_balance = parseFloat(document.getElementById("acc-balance").value || 0);
    await api("/accounts", { method: "POST", body: JSON.stringify(payload) });
  }
  resetAccForm();
  closeAccModal();
  loadAccounts();
  loadGlobalTopbar();
});

function round2(n) {
  return Math.round(n * 100) / 100;
}

function openAccModal() {
  document.getElementById("acc-modal").classList.remove("hidden");
}
function closeAccModal() {
  document.getElementById("acc-modal").classList.add("hidden");
}

window.editAccount = async id => {
  const a = accountsCache.find(x => x.id === id);
  editingAccId = id;
  document.getElementById("acc-name").value = a.name;
  document.getElementById("acc-type").value = a.type;
  document.getElementById("acc-current-balance").value = a.current_balance;
  document.getElementById("acc-business").checked = a.is_business;
  document.getElementById("acc-balance-label").classList.add("hidden");
  document.getElementById("acc-current-balance-label").classList.remove("hidden");
  document.getElementById("acc-current-balance-hint").classList.remove("hidden");
  document.getElementById("acc-cancel").classList.remove("hidden");
  document.getElementById("acc-submit").textContent = "Änderungen speichern";
  document.getElementById("acc-modal-title").textContent = "Konto bearbeiten";
  openAccModal();
};
document.getElementById("acc-new-btn").addEventListener("click", () => {
  resetAccForm();
  document.getElementById("acc-modal-title").textContent = "Neues Konto";
  openAccModal();
});
document.getElementById("acc-modal-close").addEventListener("click", closeAccModal);
document.getElementById("acc-cancel").addEventListener("click", () => {
  resetAccForm();
  closeAccModal();
});
function resetAccForm() {
  editingAccId = null;
  document.getElementById("acc-form").reset();
  document.getElementById("acc-balance-label").classList.remove("hidden");
  document.getElementById("acc-current-balance-label").classList.add("hidden");
  document.getElementById("acc-current-balance-hint").classList.add("hidden");
  document.getElementById("acc-cancel").classList.add("hidden");
  document.getElementById("acc-submit").textContent = "Speichern";
}
window.deleteAccount = async id => {
  if (!confirm("Konto wirklich löschen? Zugehörige Buchungen werden mitgelöscht.")) return;
  await api(`/accounts/${id}`, { method: "DELETE" });
  loadAccounts();
};


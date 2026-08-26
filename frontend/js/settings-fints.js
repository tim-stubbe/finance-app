// ================= SETTINGS: FINTS BANK-SYNC =================
async function loadFintsSettings() {
  const s = await api("/settings/fints");
  document.getElementById("fints-product-id").value = s.fints_product_id || "";
}

document.getElementById("fints-product-form").addEventListener("submit", async e => {
  e.preventDefault();
  const fints_product_id = document.getElementById("fints-product-id").value;
  await api("/settings/fints", { method: "PUT", body: JSON.stringify({ fints_product_id }) });
  toast("FinTS-Produkt-ID gespeichert.");
});

function populateBankAccountSelect() {
  const sel = document.getElementById("bank-account");
  sel.innerHTML = "";
  accountsCache.forEach(a => {
    const opt = document.createElement("option");
    opt.value = a.id; opt.textContent = a.name;
    sel.appendChild(opt);
  });
}

async function loadBankConnections() {
  if (!accountsCache.length) await loadAccounts();
  populateBankAccountSelect();
  const conns = await api("/bank-connections");
  const tbody = document.getElementById("bank-conn-list");
  tbody.innerHTML = "";
  if (conns.length === 0) {
    tbody.innerHTML = emptyRow(5, "landmark", "Noch keine Bank-Verbindung angelegt.");
  }
  conns.forEach(c => {
    const tr = document.createElement("tr");
    const lastSync = c.last_sync_at ? new Date(c.last_sync_at).toLocaleString("de-DE") : "noch nie";
    tr.innerHTML = `
      <td>${c.name}</td>
      <td>${c.iban || "–"}</td>
      <td>${lastSync}</td>
      <td>${c.last_sync_status || "–"}</td>
      <td>
        <button class="link-btn" onclick="syncBankConnection(${c.id})">Jetzt synchronisieren</button>
        <button class="link-btn" onclick="deleteBankConnection(${c.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
    const tanRow = document.createElement("tr");
    tanRow.id = `tan-row-${c.id}`;
    tanRow.style.display = "none";
    tanRow.innerHTML = `<td colspan="5">
      <div class="filter-row">
        <span id="tan-challenge-${c.id}" class="page-sub"></span>
        <input type="text" id="tan-input-${c.id}" placeholder="TAN eingeben">
        <button class="btn-primary" onclick="submitTan(${c.id})">TAN bestätigen</button>
      </div>
    </td>`;
    tbody.appendChild(tanRow);
  });
}

document.getElementById("bank-conn-form").addEventListener("submit", async e => {
  e.preventDefault();
  const payload = {
    name: document.getElementById("bank-name").value,
    blz: document.getElementById("bank-blz").value,
    fints_url: document.getElementById("bank-fints-url").value,
    login: document.getElementById("bank-login").value,
    pin: document.getElementById("bank-pin").value,
    iban: document.getElementById("bank-iban").value,
    account_id: parseInt(document.getElementById("bank-account").value),
  };
  await api("/bank-connections", { method: "POST", body: JSON.stringify(payload) });
  document.getElementById("bank-conn-form").reset();
  loadBankConnections();
});

window.deleteBankConnection = async id => {
  if (!confirm("Bank-Verbindung wirklich löschen? Bereits importierte Buchungen bleiben erhalten.")) return;
  await api(`/bank-connections/${id}`, { method: "DELETE" });
  loadBankConnections();
};

function handleSyncResult(id, result) {
  const tanRow = document.getElementById(`tan-row-${id}`);
  if (result.tan_required) {
    document.getElementById(`tan-challenge-${id}`).textContent = result.challenge || "TAN erforderlich";
    tanRow.style.display = "table-row";
  } else {
    tanRow.style.display = "none";
    if (result.error) {
      alert("Sync-Fehler: " + result.error);
    } else {
      alert(`Sync abgeschlossen: ${result.imported} neue Buchung(en), ${result.skipped} bereits vorhanden.`);
      loadTransactions();
      loadAccounts();
    }
    loadBankConnections();
  }
}

window.syncBankConnection = async id => {
  const result = await api(`/bank-connections/${id}/sync`, { method: "POST" });
  handleSyncResult(id, result);
};

window.submitTan = async id => {
  const tan = document.getElementById(`tan-input-${id}`).value;
  if (!tan) return;
  const result = await api(`/bank-connections/${id}/submit-tan`, { method: "POST", body: JSON.stringify({ tan }) });
  handleSyncResult(id, result);
};


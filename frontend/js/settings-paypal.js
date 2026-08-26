// ================= SETTINGS: PAYPAL =================
function populatePaypalAccountSelect() {
  const sel = document.getElementById("paypal-account");
  sel.innerHTML = "";
  accountsCache.forEach(a => {
    const opt = document.createElement("option");
    opt.value = a.id; opt.textContent = a.name;
    sel.appendChild(opt);
  });
}

async function loadPaypalConnections() {
  if (!accountsCache.length) await loadAccounts();
  populatePaypalAccountSelect();
  const conns = await api("/paypal-connections");
  const tbody = document.getElementById("paypal-conn-list");
  tbody.innerHTML = "";
  if (conns.length === 0) {
    tbody.innerHTML = emptyRow(4, "credit-card", "Noch keine PayPal-Verbindung angelegt.");
  }
  conns.forEach(c => {
    const tr = document.createElement("tr");
    const lastSync = c.last_sync_at ? new Date(c.last_sync_at).toLocaleString("de-DE") : "noch nie";
    tr.innerHTML = `
      <td>${c.name}</td>
      <td>${lastSync}</td>
      <td>${c.last_sync_status || "–"}</td>
      <td>
        <button class="link-btn" onclick="syncPaypalConnection(${c.id})">Jetzt synchronisieren</button>
        <button class="link-btn" onclick="deletePaypalConnection(${c.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });
}

document.getElementById("paypal-form").addEventListener("submit", async e => {
  e.preventDefault();
  const payload = {
    name: document.getElementById("paypal-name").value,
    client_id: document.getElementById("paypal-client-id").value,
    client_secret: document.getElementById("paypal-client-secret").value,
    account_id: parseInt(document.getElementById("paypal-account").value),
  };
  await api("/paypal-connections", { method: "POST", body: JSON.stringify(payload) });
  document.getElementById("paypal-form").reset();
  loadPaypalConnections();
});

window.syncPaypalConnection = async id => {
  const result = await api(`/paypal-connections/${id}/sync`, { method: "POST" });
  if (result.error) {
    alert("Sync-Fehler: " + result.error);
  } else {
    alert(`Sync abgeschlossen: ${result.imported} neue Buchung(en), ${result.skipped} bereits vorhanden.`);
    loadTransactions();
    loadAccounts();
  }
  loadPaypalConnections();
};

window.deletePaypalConnection = async id => {
  if (!confirm("PayPal-Verbindung wirklich löschen? Bereits importierte Buchungen bleiben erhalten.")) return;
  await api(`/paypal-connections/${id}`, { method: "DELETE" });
  loadPaypalConnections();
};


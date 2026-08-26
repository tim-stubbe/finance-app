// ================= SETTINGS: BITVAVO =================
async function loadBitvavoConnections() {
  const conns = await api("/bitvavo-connections");
  const tbody = document.getElementById("bitvavo-conn-list");
  tbody.innerHTML = "";
  if (conns.length === 0) {
    tbody.innerHTML = emptyRow(4, "coins", "Noch keine Bitvavo-Verbindung angelegt.");
  }
  conns.forEach(c => {
    const tr = document.createElement("tr");
    const lastSync = c.last_sync_at ? new Date(c.last_sync_at).toLocaleString("de-DE") : "noch nie";
    tr.innerHTML = `
      <td>${c.name}</td>
      <td>${lastSync}</td>
      <td>${c.last_sync_status || "–"}</td>
      <td>
        <button class="link-btn" onclick="syncBitvavoConnection(${c.id})">Jetzt synchronisieren</button>
        <button class="link-btn" onclick="deleteBitvavoConnection(${c.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });
}

document.getElementById("bitvavo-form").addEventListener("submit", async e => {
  e.preventDefault();
  const payload = {
    name: document.getElementById("bitvavo-name").value,
    api_key: document.getElementById("bitvavo-key").value,
    api_secret: document.getElementById("bitvavo-secret").value,
  };
  await api("/bitvavo-connections", { method: "POST", body: JSON.stringify(payload) });
  document.getElementById("bitvavo-form").reset();
  loadBitvavoConnections();
});

window.syncBitvavoConnection = async id => {
  const result = await api(`/bitvavo-connections/${id}/sync`, { method: "POST" });
  if (result.error) {
    alert("Sync-Fehler: " + result.error);
  } else {
    alert(`Sync abgeschlossen: ${result.created} neue Position(en), ${result.updated} aktualisiert.`
      + (result.failed.length ? "\nOhne Kurs:\n" + result.failed.join("\n") : ""));
    loadHoldings();
  }
  loadBitvavoConnections();
};

window.deleteBitvavoConnection = async id => {
  if (!confirm("Bitvavo-Verbindung wirklich löschen?")) return;
  await api(`/bitvavo-connections/${id}`, { method: "DELETE" });
  loadBitvavoConnections();
};


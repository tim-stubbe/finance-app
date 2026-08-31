// ================= SETTINGS: AUTOMATISCHE BACKUPS =================
function fmtBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

async function loadBackupSettings() {
  const sel = document.getElementById("backup-hour");
  if (!sel.options.length) {
    for (let h = 0; h < 24; h++) {
      const opt = document.createElement("option");
      opt.value = h;
      opt.textContent = `${String(h).padStart(2, "0")}:00 Uhr`;
      sel.appendChild(opt);
    }
  }
  const s = await api("/settings/backup");
  document.getElementById("backup-enabled").checked = s.enabled;
  sel.value = s.hour;
  document.getElementById("backup-retention").value = s.retention;
}

async function loadBackupsList() {
  const backups = await api("/backups");
  const tbody = document.getElementById("backup-list");
  tbody.innerHTML = "";
  if (backups.length === 0) {
    tbody.innerHTML = emptyRow(3, "database", "Noch kein automatisches Backup erstellt.");
  }
  backups.forEach(b => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${new Date(b.created_at).toLocaleString("de-DE")}</td>
      <td>${fmtBytes(b.size_bytes)}</td>
      <td>
        <a class="link-btn" href="${API}/backups/${encodeURIComponent(b.filename)}">Herunterladen</a>
        <button class="link-btn" onclick="deleteBackupFile('${b.filename}')">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });
}

document.getElementById("backup-schedule-form").addEventListener("submit", async e => {
  e.preventDefault();
  const payload = {
    enabled: document.getElementById("backup-enabled").checked,
    hour: parseInt(document.getElementById("backup-hour").value),
    retention: parseInt(document.getElementById("backup-retention").value),
  };
  await api("/settings/backup", { method: "PUT", body: JSON.stringify(payload) });
  toast(payload.enabled
    ? `Gespeichert – Backup täglich um ${String(payload.hour).padStart(2, "0")}:00 Uhr, ${payload.retention} Stück werden aufbewahrt.`
    : "Gespeichert – automatische Backups sind ausgeschaltet.");
});

document.getElementById("backup-run-now").addEventListener("click", async () => {
  await api("/backups/run", { method: "POST" });
  await loadBackupsList();
});

window.deleteBackupFile = async filename => {
  if (!confirm("Dieses Backup wirklich löschen?")) return;
  await api(`/backups/${encodeURIComponent(filename)}`, { method: "DELETE" });
  await loadBackupsList();
};

document.getElementById("backup-btn").addEventListener("click", () => {
  window.location.href = API + "/backup";
});

async function loadBackupEncryption() {
  const el = document.getElementById("backup-enc-status");
  if (!el) return;
  try {
    const s = await api("/settings/backup-encryption");
    el.textContent = s.configured
      ? "Aktiv – Backups werden als verschlüsselter .kies-Container gespeichert."
      : "Backups werden unverschlüsselt als ZIP gespeichert.";
  } catch { /* Panel evtl. nicht sichtbar */ }
}

document.getElementById("backup-enc-save")?.addEventListener("click", async () => {
  const inp = document.getElementById("backup-enc-passphrase");
  const pw = inp.value;
  if (pw.length < 8) { toast("Passphrase muss mindestens 8 Zeichen haben."); return; }
  try {
    await api("/settings/backup-encryption", { method: "PUT", body: JSON.stringify({ passphrase: pw }) });
    inp.value = "";
    toast("Backup-Verschlüsselung aktiviert. Passphrase gut aufbewahren!");
    loadBackupEncryption();
  } catch { toast("Konnte nicht gespeichert werden."); }
});

document.getElementById("backup-enc-clear")?.addEventListener("click", async () => {
  if (!confirm("Verschlüsselung abschalten? Künftige Backups sind wieder unverschlüsselte ZIPs.")) return;
  await api("/settings/backup-encryption", { method: "DELETE" });
  toast("Backup-Verschlüsselung ausgeschaltet.");
  loadBackupEncryption();
});

document.getElementById("restore-btn").addEventListener("click", async () => {
  const fileInput = document.getElementById("restore-file");
  const resultEl = document.getElementById("restore-result");
  if (!fileInput.files.length) {
    resultEl.textContent = "Bitte zuerst eine Backup-ZIP-Datei auswählen.";
    return;
  }
  if (!confirm("Achtung: Das überschreibt ALLE aktuellen Daten unwiderruflich mit dem Inhalt des Backups. Fortfahren?")) return;
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  const pwEl = document.getElementById("restore-passphrase");
  if (pwEl && pwEl.value) fd.append("passphrase", pwEl.value);
  try {
    const result = await api("/restore", { method: "POST", body: fd });
    resultEl.textContent = result.message;
    fileInput.value = "";
    if (pwEl) pwEl.value = "";
  } catch (e) {
    resultEl.textContent = (e && e.message) || "Wiederherstellung fehlgeschlagen (Passphrase korrekt?).";
  }
});


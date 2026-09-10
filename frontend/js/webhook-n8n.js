// ================= EINGEHENDER WEBHOOK (n8n) =================
async function loadWebhookSettings() {
  const s = await api("/settings/webhook");
  // s.secret kommt vom GET absichtlich nie mehr im Klartext (siehe Backend) -
  // nur direkt nach "Neu generieren" unten wird das Feld einmalig befüllt.
  document.getElementById("webhook-secret").value = "";
  document.getElementById("webhook-secret").placeholder = s.configured
    ? "•••••••••••••••••••••••••••••• (zum Anzeigen: neu generieren)"
    : "Noch kein Secret erzeugt";
  document.getElementById("webhook-remove").classList.toggle("hidden", !s.configured);
}

document.getElementById("webhook-regenerate").addEventListener("click", async () => {
  if (
    document.getElementById("webhook-secret").value &&
    !confirm("Neues Secret erzeugen? Das alte funktioniert danach nicht mehr, bestehende n8n-Workflows müssen angepasst werden.")
  ) return;
  const s = await api("/settings/webhook/regenerate", { method: "POST" });
  document.getElementById("webhook-secret").value = s.secret || "";
  document.getElementById("webhook-remove").classList.remove("hidden");
  toast("Neues Secret erzeugt.");
});

document.getElementById("webhook-copy").addEventListener("click", () => {
  const input = document.getElementById("webhook-secret");
  if (!input.value) return;
  navigator.clipboard.writeText(input.value);
  toast("Secret kopiert.");
});

document.getElementById("webhook-remove").addEventListener("click", async () => {
  if (!confirm("Webhook deaktivieren? Eingehende Meldungen werden danach abgelehnt.")) return;
  await api("/settings/webhook", { method: "DELETE" });
  await loadWebhookSettings();
  toast("Webhook deaktiviert.");
});

async function loadScalableSettings() {
  const s = await api("/settings/scalable");
  document.getElementById("scalable-enabled").checked = !!s.enabled;
  const status = document.getElementById("scalable-status");
  status.textContent = s.last_sync_at
    ? `Zuletzt synchronisiert: ${new Date(s.last_sync_at).toLocaleString("de-DE")}${s.last_sync_status ? " · " + s.last_sync_status : ""}`
    : "Noch nicht synchronisiert.";
}

document.getElementById("scalable-enabled").addEventListener("change", async e => {
  await api("/settings/scalable", { method: "PUT", body: JSON.stringify({ enabled: e.target.checked }) });
  toast(e.target.checked ? "Scalable Capital aktiviert." : "Scalable Capital deaktiviert.");
});

document.getElementById("scalable-sync-now").addEventListener("click", async () => {
  const btn = document.getElementById("scalable-sync-now");
  btn.disabled = true;
  try {
    const result = await api("/scalable/sync", { method: "POST" });
    if (result.error) {
      toast(`Fehler: ${result.error}`);
    } else {
      toast(`Sync abgeschlossen: ${result.created} neu, ${result.updated} aktualisiert, ${result.lots_added} Lot(s).`);
    }
    await loadScalableSettings();
  } catch (e) {
    toast(`Fehler: ${e.message}`);
  } finally {
    btn.disabled = false;
  }
});

async function loadNativeSyncSettings() {
  const s = await api("/settings/native-sync");
  // Gleiche Begründung wie bei loadWebhookSettings oben.
  document.getElementById("native-sync-secret").value = "";
  document.getElementById("native-sync-secret").placeholder = s.configured
    ? "•••••••••••••••••••••••••••••• (zum Anzeigen: neu generieren)"
    : "Noch kein Secret erzeugt";
  document.getElementById("native-sync-remove").classList.toggle("hidden", !s.configured);
}

document.getElementById("native-sync-regenerate").addEventListener("click", async () => {
  if (
    document.getElementById("native-sync-secret").value &&
    !confirm("Neues Secret erzeugen? Das alte funktioniert danach nicht mehr, die native App muss neu gekoppelt werden.")
  ) return;
  const s = await api("/settings/native-sync/regenerate", { method: "POST" });
  document.getElementById("native-sync-secret").value = s.secret || "";
  document.getElementById("native-sync-remove").classList.remove("hidden");
  toast("Neues Secret erzeugt.");
});

document.getElementById("native-sync-copy").addEventListener("click", () => {
  const input = document.getElementById("native-sync-secret");
  if (!input.value) return;
  navigator.clipboard.writeText(input.value);
  toast("Secret kopiert.");
});

document.getElementById("native-sync-remove").addEventListener("click", async () => {
  if (!confirm("Sync deaktivieren? Die native App kann sich danach nicht mehr verbinden.")) return;
  await api("/settings/native-sync", { method: "DELETE" });
  await loadNativeSyncSettings();
  toast("Sync deaktiviert.");
});

async function loadDevices() {
  const tbody = document.getElementById("devices-tbody");
  if (!tbody) return;
  tbody.replaceChildren();
  const devices = await api("/devices");
  if (!devices.length) {
    const row = tbody.insertRow();
    const cell = row.insertCell();
    cell.colSpan = 4;
    cell.className = "page-sub";
    cell.textContent = "Noch keine Geräte gekoppelt.";
    return;
  }
  devices.forEach(d => {
    const row = tbody.insertRow();
    const nameCell = row.insertCell();
    nameCell.textContent = d.name || "";
    if (d.revoked) {
      const mark = document.createElement("em");
      mark.textContent = " (widerrufen)";
      nameCell.appendChild(mark);
    }
    row.insertCell().textContent = d.created_at ? new Date(d.created_at).toLocaleString("de-DE") : "–";
    row.insertCell().textContent = d.last_seen_at ? new Date(d.last_seen_at).toLocaleString("de-DE") : "–";
    const actionCell = row.insertCell();
    if (!d.revoked) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn-ghost btn-sm";
      btn.dataset.revokeDevice = String(d.id);
      btn.textContent = "Widerrufen";
      actionCell.appendChild(btn);
    }
  });
}

document.getElementById("device-create").addEventListener("click", async () => {
  const nameInput = document.getElementById("device-new-name");
  const name = (nameInput.value || "").trim();
  if (!name) { toast("Gerätename fehlt."); return; }
  const created = await api("/devices", { method: "POST", body: JSON.stringify({ name }) });
  nameInput.value = "";
  const once = document.getElementById("device-token-once");
  document.getElementById("device-token-value").textContent = created.token || "";
  once.classList.remove("hidden");
  await loadDevices();
  toast("Gerät gekoppelt – Token jetzt kopieren.");
});

document.getElementById("device-token-copy").addEventListener("click", () => {
  const value = document.getElementById("device-token-value").textContent;
  if (!value) return;
  navigator.clipboard.writeText(value);
  toast("Gerätetoken kopiert.");
});

document.getElementById("devices-tbody").addEventListener("click", async e => {
  const btn = e.target.closest("[data-revoke-device]");
  if (!btn) return;
  if (!confirm("Dieses Gerät widerrufen? Der Assistent auf dem Gerät funktioniert danach sofort nicht mehr.")) return;
  await api(`/devices/${btn.dataset.revokeDevice}`, { method: "DELETE" });
  await loadDevices();
  toast("Gerät widerrufen.");
});


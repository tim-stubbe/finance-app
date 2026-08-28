// ================= EINSTELLUNGEN → SMART HOME (Home Assistant) =================
// Endpunkte in backend/app/routers/smarthome.py (/api/smarthome/settings).
// Der Token wird nie zurückgeliefert (nur token_set: bool) - leeres Feld beim
// Speichern lässt ihn unverändert.

async function loadSmartHomeSettingsPanel() {
  let s;
  try {
    s = await api("/smarthome/settings");
  } catch {
    return;
  }
  document.getElementById("smarthome-cfg-url").value = s.url || "";
  document.getElementById("smarthome-cfg-token").placeholder =
    s.token_set ? "gesetzt – leer lassen = unverändert" : "leer lassen = unverändert";
  document.getElementById("smarthome-cfg-domains").value = s.allowed_domains || "";
  document.getElementById("smarthome-cfg-areas").value = s.allowed_areas || "";
  document.getElementById("smarthome-cfg-extra").value = s.extra_services || "";
  document.getElementById("smarthome-cfg-confirm").checked = !!s.require_confirmation;
  document.getElementById("smarthome-cfg-dry").checked = !!s.dry_run;
  document.getElementById("smarthome-cfg-wake").value = s.wake_word || "hey_jarvis";
}

document.getElementById("smarthome-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const statusEl = document.getElementById("smarthome-cfg-status");
  const tokenField = document.getElementById("smarthome-cfg-token");
  const payload = {
    url: document.getElementById("smarthome-cfg-url").value.trim(),
    allowed_domains: document.getElementById("smarthome-cfg-domains").value.trim(),
    allowed_areas: document.getElementById("smarthome-cfg-areas").value.trim(),
    extra_services: document.getElementById("smarthome-cfg-extra").value.trim(),
    require_confirmation: document.getElementById("smarthome-cfg-confirm").checked,
    dry_run: document.getElementById("smarthome-cfg-dry").checked,
    wake_word: document.getElementById("smarthome-cfg-wake").value.trim(),
  };
  // Token nur mitschicken, wenn wirklich etwas eingegeben wurde - sonst bleibt
  // der gespeicherte unangetastet (Backend: token === undefined -> unverändert).
  if (tokenField.value !== "") payload.token = tokenField.value;

  try {
    await api("/smarthome/settings", { method: "PUT", body: JSON.stringify(payload) });
    tokenField.value = "";
    statusEl.textContent = "Gespeichert.";
    loadSmartHomeSettingsPanel();
    if (typeof loadIntegrationStatus === "function") loadIntegrationStatus();
  } catch (err) {
    statusEl.textContent = "Fehler: " + (err.message || err);
  }
});

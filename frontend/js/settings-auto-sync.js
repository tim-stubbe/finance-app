// ================= SETTINGS: AUTOMATISCHER SYNC =================
async function loadSyncSchedule() {
  const sel = document.getElementById("sync-hour");
  if (!sel.options.length) {
    for (let h = 0; h < 24; h++) {
      const opt = document.createElement("option");
      opt.value = h;
      opt.textContent = `${String(h).padStart(2, "0")}:00 Uhr`;
      sel.appendChild(opt);
    }
  }
  const s = await api("/settings/sync-schedule");
  sel.value = s.hour;
}

async function loadAutoCategorizeSettings() {
  const s = await api("/settings/auto-categorize");
  document.getElementById("auto-categorize-enabled").checked = s.enabled;
}

document.getElementById("auto-categorize-form").addEventListener("submit", async e => {
  e.preventDefault();
  const enabled = document.getElementById("auto-categorize-enabled").checked;
  await api("/settings/auto-categorize", { method: "PUT", body: JSON.stringify({ enabled }) });
  toast(enabled ? "Gespeichert – Buchungen werden künftig automatisch kategorisiert." : "Gespeichert – automatische Kategorisierung ist ausgeschaltet.");
});

document.getElementById("auto-categorize-run-now").addEventListener("click", async () => {
  const statusEl = document.getElementById("auto-categorize-status");
  const btn = document.getElementById("auto-categorize-run-now");
  statusEl.textContent = "Läuft …";
  btn.disabled = true;
  try {
    const r = await api("/ai/auto-categorize/run-now", { method: "POST" });
    let msg = `${r.transfers_marked} Buchung(en) als Umbuchung markiert, ${r.categorized} kategorisiert, `
      + `${r.queued} zur Bestätigung vorgeschlagen, ${r.skipped} übersprungen.`;
    if (r.error) msg += ` Hinweis: ${r.error}`;
    statusEl.textContent = msg;
    await loadTransactions();
    await loadGlobalTopbar();
    await loadCategorySuggestions();
  } catch (e) {
    // api() zeigt den Fehler bereits per alert() an
  }
  btn.disabled = false;
});

async function loadWebSearchSettings() {
  const s = await api("/settings/websearch");
  document.getElementById("websearch-provider").value = s.provider;
  document.getElementById("websearch-brave-panel").classList.toggle("hidden", s.provider !== "brave");
  document.getElementById("websearch-searxng-panel").classList.toggle("hidden", s.provider !== "searxng");
  document.getElementById("websearch-remove").classList.toggle("hidden", !s.api_key_set);
  document.getElementById("websearch-api-key").placeholder = s.api_key_set
    ? "gespeichert – zum Ändern neuen Key eingeben" : "wird verschlüsselt gespeichert";
  document.getElementById("searxng-url").value = s.searxng_url || "";
}

document.getElementById("websearch-provider").addEventListener("change", async e => {
  const provider = e.target.value;
  document.getElementById("websearch-brave-panel").classList.toggle("hidden", provider !== "brave");
  document.getElementById("websearch-searxng-panel").classList.toggle("hidden", provider !== "searxng");
  await api("/settings/websearch/provider", {
    method: "PUT",
    body: JSON.stringify({ provider, searxng_url: document.getElementById("searxng-url").value.trim() || null }),
  });
  toast(provider === "searxng" ? "SearXNG als Web-Suche aktiv." : "Brave Search als Web-Suche aktiv.");
});

document.getElementById("websearch-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const input = document.getElementById("websearch-api-key");
  const api_key = input.value.trim();
  if (!api_key) return;
  await api("/settings/websearch", { method: "PUT", body: JSON.stringify({ api_key }) });
  input.value = "";
  toast("Gespeichert – der KI-Chat kann jetzt im Internet suchen.");
  loadWebSearchSettings();
});

document.getElementById("websearch-remove").addEventListener("click", async () => {
  await api("/settings/websearch", { method: "DELETE" });
  toast("Web-Suche entfernt.");
  loadWebSearchSettings();
});

document.getElementById("searxng-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const url = document.getElementById("searxng-url").value.trim();
  if (!url) return;
  await api("/settings/websearch/provider", {
    method: "PUT", body: JSON.stringify({ provider: "searxng", searxng_url: url }),
  });
  toast("SearXNG-Adresse gespeichert.");
});

async function loadNotificationSettings() {
  const s = await api("/settings/notifications");
  document.getElementById("notifications-enabled").checked = s.enabled;
  document.getElementById("proactive-assistant-enabled").checked = !!s.proactive_assistant_enabled;
  document.getElementById("telegram-remove").classList.toggle("hidden", !s.telegram_configured);
  document.getElementById("telegram-bot-token").placeholder = s.telegram_configured
    ? "gespeichert – zum Ändern neuen Token eingeben" : "wird verschlüsselt gespeichert";
  document.getElementById("telegram-chat-id").placeholder = s.telegram_configured
    ? "gespeichert" : "z.B. 123456789";
  loadNotificationLog();
}

async function loadNotificationLog() {
  const ul = document.getElementById("notifications-log");
  if (!ul) return;
  let rows = [];
  try { rows = await api("/notifications/log?limit=40"); } catch { return; }
  if (!rows.length) { ul.innerHTML = `<li class="page-sub">Noch nichts gemeldet.</li>`; return; }
  ul.innerHTML = rows.map(r => {
    const when = new Date(r.created_at + (r.created_at.endsWith("Z") ? "" : "Z"))
      .toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    const badge = r.sent ? "" : ` <span class="notif-log-muted">(Ruhezeit – nicht gesendet)</span>`;
    return `<li><span class="notif-log-when">${when}</span> ${esc(r.text)}${badge}</li>`;
  }).join("");
}

document.getElementById("notifications-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const tokenInput = document.getElementById("telegram-bot-token");
  const chatIdInput = document.getElementById("telegram-chat-id");
  const payload = {
    enabled: document.getElementById("notifications-enabled").checked,
    proactive_assistant_enabled: document.getElementById("proactive-assistant-enabled").checked,
    telegram_bot_token: tokenInput.value.trim() || null,
    telegram_chat_id: chatIdInput.value.trim() || null,
  };
  await api("/settings/notifications", { method: "PUT", body: JSON.stringify(payload) });
  tokenInput.value = "";
  chatIdInput.value = "";
  toast("Gespeichert.");
  loadNotificationSettings();
});

document.getElementById("notifications-test").addEventListener("click", async () => {
  const statusEl = document.getElementById("notifications-status");
  statusEl.textContent = "Sende …";
  try {
    const r = await api("/notifications/test", { method: "POST" });
    statusEl.textContent = r.message;
  } catch (e) {
    // api() zeigt den Fehler bereits per alert() an
  }
});

document.getElementById("notifications-test-proactive").addEventListener("click", async () => {
  const statusEl = document.getElementById("notifications-status");
  statusEl.textContent = "Erzeuge proaktive Meldung (kann kurz dauern) …";
  try {
    const r = await api("/notifications/test-proactive", { method: "POST" });
    statusEl.textContent = r.message;
    loadNotificationLog();
  } catch (e) {
    // api() zeigt den Fehler bereits per alert() an
  }
});

document.getElementById("telegram-remove").addEventListener("click", async () => {
  await api("/settings/notifications/telegram", { method: "DELETE" });
  toast("Telegram entfernt.");
  loadNotificationSettings();
});


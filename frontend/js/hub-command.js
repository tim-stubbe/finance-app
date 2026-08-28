// ================= UNIVERSELLE HUB-KOMMANDOZEILE =================
// Ein Eingabefeld, das per Ollama-Intent in die passende Domäne routet
// (Smart Home, To-do, Kalender, Wunschliste, Ausgabe, Frage, Navigation).
// Backend: backend/app/hub_command.py, Endpunkt /api/hub/command.

async function hubCommandSend(text, confirm) {
  const replyEl = document.getElementById("hub-command-reply");
  const confirmEl = document.getElementById("hub-command-confirm");
  replyEl.classList.remove("hidden", "reply-error");
  replyEl.textContent = "…";
  confirmEl.classList.add("hidden");

  let res;
  try {
    res = await api("/hub/command", { method: "POST", body: JSON.stringify({ text, confirm }) });
  } catch (err) {
    replyEl.textContent = "Fehler: " + (err.message || err);
    replyEl.classList.add("reply-error");
    return;
  }

  // Smart-Home-Rückfrage (Bestätigung)
  if (res.needs_confirmation && res.intent === "control") {
    document.getElementById("hub-command-confirm-text").textContent = res.reply || "Ausführen?";
    confirmEl.classList.remove("hidden");
    replyEl.classList.add("hidden");
    return;
  }

  replyEl.textContent = res.reply || (res.ok ? "Erledigt." : "Das hat nicht geklappt.");
  replyEl.classList.toggle("reply-error", !res.ok);

  if (res.domain === "navigation" && res.tab && typeof goToTab === "function") {
    goToTab(res.tab);
  } else if (res.route === "expense") {
    // Geld nie still buchen: nur zum Buchungs-Formular navigieren.
    if (typeof goToTab === "function") {
      goToTab("transactions");
      setTimeout(() => document.getElementById("tx-new-btn")?.click(), 200);
    }
  }
  // Nach schreibenden Aktionen die Hub-Panels auffrischen
  if (["todo", "termin", "wunschliste", "smarthome"].includes(res.domain) && typeof loadHubTab === "function") {
    setTimeout(loadHubTab, 400);
  }
}

document.getElementById("hub-command-form").addEventListener("submit", e => {
  e.preventDefault();
  const input = document.getElementById("hub-command-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  hubCommandSend(text, false);
});
document.getElementById("hub-command-confirm-yes").addEventListener("click", () => {
  document.getElementById("hub-command-confirm").classList.add("hidden");
  hubCommandSend("ja", true);
});
document.getElementById("hub-command-confirm-no").addEventListener("click", () => {
  document.getElementById("hub-command-confirm").classList.add("hidden");
  hubCommandSend("nein", false);
});

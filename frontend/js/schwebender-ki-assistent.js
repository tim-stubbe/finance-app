// ================= KIES ASSISTENT (global, jede Seite) =================
// Der globale Assistent nutzt den Agent-Core statt des alten Finance-Chat-
// Endpunkts. Private Daten werden damit nur noch über gezielte Tools geladen.
let globalAiHistory = [];

document.getElementById("global-ai-fab").addEventListener("click", () => {
  document.getElementById("global-ai-panel").classList.toggle("hidden");
});
document.getElementById("global-ai-close").addEventListener("click", () => {
  document.getElementById("global-ai-panel").classList.add("hidden");
});

function appendAgentSources(sources) {
  if (!Array.isArray(sources) || !sources.length) return;
  const unique = sources.filter((s, i, all) => s && s.url && all.findIndex(x => x && x.url === s.url) === i);
  if (!unique.length) return;
  const lines = unique.slice(0, 5).map((s, i) => `${i + 1}. ${s.title || s.url} — ${s.url}`);
  appendChatBubble("system", `🌐 Quellen\n${lines.join("\n")}`, "global-ai-log");
}

function appendAgentActions(actions) {
  if (!Array.isArray(actions)) return;
  actions.forEach(action => {
    if (!action || !action.type) return;
    if (action.type === "todo_created") {
      appendChatBubble("system", `✓ Aufgabe angelegt: ${action.title || "To-do"}`, "global-ai-log");
    } else if (action.type === "calendar_event_created") {
      appendChatBubble("system", `✓ Termin angelegt: ${action.title || "Termin"}`, "global-ai-log");
    } else if (action.type === "finance_proposal") {
      appendChatBubble("system", `⚠ Finanzänderung nicht ausgeführt. Vorschlag: ${action.summary || "Änderung prüfen"}`, "global-ai-log");
    }
  });
}

document.getElementById("global-ai-form").addEventListener("submit", async e => {
  e.preventDefault();
  const input = document.getElementById("global-ai-message");
  const message = input.value.trim();
  if (!message) return;

  appendChatBubble("user", message, "global-ai-log");
  const statusEl = document.getElementById("global-ai-status");
  const sendBtn = document.getElementById("global-ai-send");
  statusEl.textContent = "";
  sendBtn.disabled = true;
  input.value = "";
  showChatTyping("global-ai-log");

  try {
    const result = await api("/jarvis/chat", {
      method: "POST",
      body: JSON.stringify({ message, history: globalAiHistory.slice(-10) }),
    });
    hideChatTyping("global-ai-log");

    if (!result.ok) {
      appendChatBubble("assistant", result.reply || "Der Assistent konnte die Anfrage nicht bearbeiten.", "global-ai-log");
    } else {
      appendChatBubble("assistant", result.reply || "Ok.", "global-ai-log");
      appendAgentSources(result.sources || []);
      appendAgentActions(result.actions || []);

      globalAiHistory.push({ role: "user", content: message });
      globalAiHistory.push({ role: "assistant", content: result.reply || "Ok." });
      // Clientseitig ebenfalls begrenzen; serverseitig gilt zusätzlich ein
      // eigenes Limit. So wächst ein lange geöffnetes Browserfenster nicht.
      if (globalAiHistory.length > 20) globalAiHistory = globalAiHistory.slice(-20);
    }
  } catch (e) {
    hideChatTyping("global-ai-log");
    // api() zeigt Netzwerk-/HTTP-Fehler bereits zentral an.
  } finally {
    statusEl.textContent = "";
    sendBtn.disabled = false;
    input.focus();
  }
});

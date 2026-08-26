// ================= SCHWEBENDER KI-ASSISTENT (global, jede Seite) =================
let globalAiHistory = [];

document.getElementById("global-ai-fab").addEventListener("click", () => {
  document.getElementById("global-ai-panel").classList.toggle("hidden");
});
document.getElementById("global-ai-close").addEventListener("click", () => {
  document.getElementById("global-ai-panel").classList.add("hidden");
});

document.getElementById("global-ai-form").addEventListener("submit", async e => {
  e.preventDefault();
  const input = document.getElementById("global-ai-message");
  const message = input.value.trim();
  if (!message) return;
  if (!accountsCache.length) await loadAccounts();

  appendChatBubble("user", message, "global-ai-log");
  const statusEl = document.getElementById("global-ai-status");
  const sendBtn = document.getElementById("global-ai-send");
  statusEl.textContent = "";
  sendBtn.disabled = true;
  input.value = "";
  showChatTyping("global-ai-log");

  const fd = new FormData();
  fd.append("message", message);
  fd.append("history", JSON.stringify(globalAiHistory));

  try {
    const result = await api("/ai/assistant-chat", { method: "POST", body: fd });
    hideChatTyping("global-ai-log");
    if (result.error) {
      appendChatBubble("assistant", "Fehler: " + result.error, "global-ai-log");
    } else {
      (result.web_searches || []).forEach(q => {
        appendChatBubble("system", `🌐 hat im Internet gesucht: „${q}“`, "global-ai-log");
      });
      appendChatBubble("assistant", result.reply, "global-ai-log");
      globalAiHistory.push({ role: "user", content: message });
      globalAiHistory.push({ role: "assistant", content: result.reply });
      (result.proposals || []).forEach(p => {
        renderBelegProposal(p, null, null, "global-ai-log");
      });
    }
  } catch (e) {
    hideChatTyping("global-ai-log");
    // api() zeigt den Fehler bereits per alert() an
  }
  statusEl.textContent = "";
  sendBtn.disabled = false;
});


// ================= KI-ASSISTENT (OLLAMA) =================
async function loadOllamaSettings() {
  const s = await api("/settings/ollama");
  document.getElementById("ollama-url").value = s.url || "";
  const sel = document.getElementById("ollama-model");
  sel.innerHTML = s.model ? `<option value="${s.model}">${s.model}</option>` : '<option value="">Erst Modelle laden</option>';
}

document.getElementById("ollama-load-models").addEventListener("click", async () => {
  const url = document.getElementById("ollama-url").value;
  const statusEl = document.getElementById("ollama-status");
  const sel = document.getElementById("ollama-model");
  if (!url) { statusEl.textContent = "Bitte zuerst die Server-URL eintragen."; return; }
  statusEl.textContent = "Lade Modelle …";
  try {
    const result = await api(`/ollama/models?url=${encodeURIComponent(url)}`);
    sel.innerHTML = "";
    if (result.models.length === 0) {
      sel.innerHTML = '<option value="">Keine Modelle gefunden</option>';
      statusEl.textContent = "Verbindung ok, aber keine Modelle installiert.";
    } else {
      result.models.forEach(m => {
        const opt = document.createElement("option");
        opt.value = m; opt.textContent = m;
        sel.appendChild(opt);
      });
      statusEl.textContent = `${result.models.length} Modell(e) gefunden.`;
    }
  } catch (e) {
    statusEl.textContent = "Ollama nicht erreichbar. URL und Netzwerkzugriff prüfen.";
  }
});

document.getElementById("ollama-pull-btn").addEventListener("click", async () => {
  const url = document.getElementById("ollama-url").value;
  const model = document.getElementById("ollama-pull-model").value.trim();
  const statusEl = document.getElementById("ollama-pull-status");
  const btn = document.getElementById("ollama-pull-btn");
  if (!url) { statusEl.textContent = "Bitte zuerst die Server-URL eintragen und speichern."; return; }
  if (!model) { statusEl.textContent = "Bitte einen Modellnamen angeben (z.B. llama3.2:1b)."; return; }
  btn.disabled = true;
  statusEl.textContent = `„${model}“ wird heruntergeladen … das kann je nach Modellgröße mehrere Minuten dauern, bitte warten.`;
  try {
    const result = await api("/ollama/pull", { method: "POST", body: JSON.stringify({ url, model }) });
    statusEl.textContent = `„${model}“ ist bereit (${result.status}).`;
    document.getElementById("ollama-pull-model").value = "";
    document.getElementById("ollama-load-models").click();
    toast(`Modell „${model}“ heruntergeladen.`);
  } catch (e) {
    statusEl.textContent = `Fehlgeschlagen: ${e.message}`;
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("ollama-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const url = document.getElementById("ollama-url").value;
  const model = document.getElementById("ollama-model").value;
  await api("/settings/ollama", { method: "PUT", body: JSON.stringify({ url, model: model || null }) });
  toast("Ollama-Einstellungen gespeichert.");
});

document.getElementById("ai-portfolio-btn").addEventListener("click", async () => {
  const resultEl = document.getElementById("ai-portfolio-result");
  resultEl.textContent = "Analyse wird erstellt …";
  resultEl.classList.add("loading-pulse");
  try {
    const result = await api("/ai/portfolio-insight", { method: "POST" });
    if (result.error) {
      resultEl.textContent = `Fehler: ${result.error}`;
    } else {
      renderAiText(resultEl, result.text);
    }
  } catch (e) {
    resultEl.textContent = "Analyse fehlgeschlagen.";
  } finally {
    resultEl.classList.remove("loading-pulse");
  }
});

document.getElementById("ai-receipts-btn").addEventListener("click", async () => {
  const minAmount = parseFloat(document.getElementById("ai-receipts-min").value || 0);
  const summaryEl = document.getElementById("ai-receipts-summary");
  const tbody = document.getElementById("ai-receipts-list");
  summaryEl.textContent = "Prüfe …";
  tbody.innerHTML = "";
  const result = await api(`/ai/missing-receipts?min_amount=${minAmount}`);
  summaryEl.textContent = result.summary
    || `${result.transactions.length} Buchung(en) ohne Beleg, ${eur(result.total_amount)} insgesamt.`;
  if (result.transactions.length === 0) {
    tbody.innerHTML = emptyRow(4, "receipt", "Keine fehlenden Belege gefunden.");
  }
  if (!accountsCache.length) await loadAccounts();
  result.transactions.forEach(t => {
    const acc = accountsCache.find(a => a.id === t.account_id);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${t.date}</td>
      <td>${t.description || "–"}</td>
      <td>${acc ? acc.name : ""}</td>
      <td class="row-amount-neg">${eur(t.amount)}</td>`;
    tbody.appendChild(tr);
  });
});

async function loadAiTab() {
  await loadBelegChatModelSelect();
  await loadCategorySuggestions();
}


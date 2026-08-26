// ================= KI-REVIEW-QUEUE (Kategorisierungsvorschläge) =================
let categorySuggestionsCache = [];

// Von Hub UND KI-Assistent-Tab genutzt - beide zeigen dieselben Daten, nur
// der Hub nur die obersten paar als Kurzüberblick mit direktem Übernehmen-
// Button, der KI-Tab die volle Liste mit Übernehmen/Ablehnen.
async function loadCategorySuggestions() {
  categorySuggestionsCache = await api("/category-suggestions").catch(() => []);
  renderHubAiSuggestions();
  renderAiSuggestionsList();
}

function renderHubAiSuggestions() {
  const panel = document.getElementById("hub-ai-suggestions-panel");
  const body = document.getElementById("hub-ai-suggestions-body");
  if (!panel || !body) return;
  panel.classList.toggle("hidden", categorySuggestionsCache.length === 0);
  if (!categorySuggestionsCache.length) return;
  body.innerHTML = categorySuggestionsCache.slice(0, 5).map(s => `
    <button type="button" class="hub-list-row" data-suggestion-jump="${s.id}">
      <span>${esc(s.transaction_description || "–")} <span class="page-sub" style="display:inline">→ ${esc(s.suggested_category_name)} (${Math.round(s.confidence * 100)}%)</span></span>
      <span class="${s.transaction_amount >= 0 ? "row-amount-pos" : "row-amount-neg"}">${eur(s.transaction_amount)}</span>
    </button>`).join("");
}

function renderAiSuggestionsList() {
  const tbody = document.getElementById("ai-suggestions-list");
  if (!tbody) return;
  if (!categorySuggestionsCache.length) {
    tbody.innerHTML = emptyRow(6, "sparkles", "Keine wartenden Vorschläge.");
    return;
  }
  tbody.innerHTML = categorySuggestionsCache.map(s => `
    <tr>
      <td>${fmtDate(s.transaction_date)}</td>
      <td>${esc(s.transaction_description || "–")}</td>
      <td class="${s.transaction_amount >= 0 ? "row-amount-pos" : "row-amount-neg"}">${eur(s.transaction_amount)}</td>
      <td>${esc(s.suggested_category_name)}</td>
      <td>${Math.round(s.confidence * 100)}%</td>
      <td>
        <button type="button" class="btn-ghost btn-sm" data-suggestion-accept="${s.id}">✓ Übernehmen</button>
        <button type="button" class="link-btn" data-suggestion-reject="${s.id}">Ablehnen</button>
      </td>
    </tr>`).join("");
}

async function decideCategorySuggestion(id, accept) {
  await api(`/category-suggestions/${id}/${accept ? "accept" : "reject"}`, { method: "POST" });
  await loadCategorySuggestions();
}

document.addEventListener("click", e => {
  const acceptId = e.target.closest("[data-suggestion-accept]")?.dataset.suggestionAccept;
  if (acceptId) { decideCategorySuggestion(parseInt(acceptId, 10), true); return; }
  const rejectId = e.target.closest("[data-suggestion-reject]")?.dataset.suggestionReject;
  if (rejectId) { decideCategorySuggestion(parseInt(rejectId, 10), false); return; }
  const jumpId = e.target.closest("[data-suggestion-jump]")?.dataset.suggestionJump;
  if (jumpId) { goToTab("ai"); }
});


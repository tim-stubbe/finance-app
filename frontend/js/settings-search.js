// ================= SETTINGS-SUCHE (Spezifikationspunkt G, 2026-08-28) =================
// Rein clientseitig - indexiert einmalig alle .panel-Blöcke unter den
// bestehenden #settings-view-*-Containern (Titel + Label-Texte), kein neuer
// Backend-Endpunkt nötig. Treffer -> passenden Unterreiter aktivieren
// (settingsSwitchView, siehe kalender.js), zum Panel scrollen, kurz
// hervorheben.
let settingsSearchIndex = null;

function buildSettingsSearchIndex() {
  const index = [];
  SETTINGS_VIEWS.forEach(view => {
    const container = document.getElementById(`settings-view-${view}`);
    if (!container) return;
    // Bewusst JEDE Verschachtelungstiefe (nicht nur direkte Kinder) - manche
    // Panels stecken in zusätzlichen Wrapper-divs (z.B. bedingt versteckte
    // Bereiche), ein zu enges :scope-Selector-Muster hätte die dort still
    // übersehen.
    container.querySelectorAll(".panel").forEach(panel => {
      const titleEl = panel.querySelector(".panel-title");
      const title = titleEl ? titleEl.textContent.trim() : "";
      if (!title) return;
      const labels = [...panel.querySelectorAll("label")].map(l => l.textContent.trim()).join(" ");
      index.push({ view, panel, title, haystack: (title + " " + labels).toLowerCase() });
    });
  });
  return index;
}

function settingsSearchRender(query) {
  const resultsEl = document.getElementById("settings-search-results");
  const q = query.trim().toLowerCase();
  if (!q) {
    resultsEl.classList.add("hidden");
    resultsEl.innerHTML = "";
    return;
  }
  if (!settingsSearchIndex) settingsSearchIndex = buildSettingsSearchIndex();
  const hits = settingsSearchIndex.filter(e => e.haystack.includes(q)).slice(0, 8);
  if (!hits.length) {
    resultsEl.classList.remove("hidden");
    resultsEl.innerHTML = `<div class="settings-search-empty">Nichts gefunden.</div>`;
    return;
  }
  resultsEl.classList.remove("hidden");
  resultsEl.innerHTML = hits.map((h, i) => `
    <button type="button" class="settings-search-item" data-settings-hit="${i}">
      <span>${esc(h.title)}</span>
      <span class="page-sub">${esc(SETTINGS_VIEW_LABELS[h.view] || h.view)}</span>
    </button>`).join("");
  resultsEl.dataset.hits = JSON.stringify(hits.map(h => h.view));
  resultsEl._hits = hits;
}

const SETTINGS_VIEW_LABELS = {
  allgemein: "Allgemein", banken: "Banken & Börsen", ki: "KI & Automatisierung",
  benachrichtigungen: "Benachrichtigungen", verbindungen: "Weitere Verbindungen", daten: "Daten & Sicherung",
};

function settingsSearchGoTo(hit) {
  settingsSwitchView(hit.view);
  document.getElementById("settings-search-results").classList.add("hidden");
  document.getElementById("settings-search").value = "";
  setTimeout(() => {
    hit.panel.scrollIntoView({ behavior: "smooth", block: "start" });
    hit.panel.classList.add("settings-search-highlight");
    setTimeout(() => hit.panel.classList.remove("settings-search-highlight"), 1600);
  }, 80);
}

document.getElementById("settings-search").addEventListener("input", e => settingsSearchRender(e.target.value));
document.getElementById("settings-search-results").addEventListener("click", e => {
  const idx = e.target.closest("[data-settings-hit]")?.dataset.settingsHit;
  if (idx === undefined) return;
  const el = document.getElementById("settings-search-results");
  settingsSearchGoTo(el._hits[parseInt(idx, 10)]);
});
document.addEventListener("click", e => {
  const wrap = document.querySelector(".settings-search-wrap");
  if (wrap && !wrap.contains(e.target)) document.getElementById("settings-search-results").classList.add("hidden");
});

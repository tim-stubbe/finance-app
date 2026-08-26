// ================= COMMAND-PALETTE (Cmd/Ctrl+K) =================
// Bewusst eine statische Liste statt eines Live-Index ueber echte Buchungen/
// Positionen: die Palette soll blitzschnell oeffnen (kein Serveraufruf) und
// deckt genau zwei Faelle ab, die im Alltag wirklich zaehlen - "wohin will
// ich" (Seiten) und "was will ich jetzt anlegen" (Schnellaktionen). Eine
// echte Volltextsuche ueber Buchungen waere ein eigenes, viel groesseres
// Feature (Server-Query, Pagination, Relevanz-Ranking).
const CMDK_NAV = [
  { label: "Hub", tab: "hub", icon: "home" },
  { label: "Dashboard", tab: "dashboard", icon: "layout-grid" },
  { label: "Buchungen", tab: "transactions", icon: "list" },
  { label: "Konten", tab: "accounts", icon: "landmark" },
  { label: "Abos", tab: "recurring", icon: "repeat" },
  { label: "Kategorien", tab: "categories", icon: "tag" },
  { label: "Investments", tab: "investments", icon: "trending-up" },
  { label: "Geschäftlich", tab: "business", icon: "briefcase" },
  { label: "Schulden", tab: "debts", icon: "banknote-stack" },
  { label: "Ziele", tab: "goals", icon: "target" },
  { label: "Schweiz", tab: "schweiz", icon: "target" },
  { label: "KI-Assistent", tab: "ai", icon: "sparkles" },
  { label: "Fotos", tab: "photos", icon: "image" },
  { label: "Urlaube", tab: "trips", icon: "map" },
  { label: "Projekte", tab: "projects", icon: "briefcase" },
  { label: "Leben", tab: "life", icon: "target" },
  { label: "Wunschliste", tab: "wishlist", icon: "shopping-cart" },
  { label: "Einstellungen", tab: "settings", icon: "settings" },
  { label: "Profil", tab: "profile", icon: "user" },
];

function cmdkGoTo(tab) {
  return () => goToTab(tab);
}

const CMDK_ACTIONS = [
  { label: "Neue Buchung", icon: "plus", run: () => { goToTab("transactions"); setTimeout(() => document.getElementById("tx-new-btn")?.click(), 150); } },
  { label: "Neues Konto", icon: "plus", run: () => { goToTab("accounts"); setTimeout(() => document.getElementById("acc-new-btn")?.click(), 150); } },
  { label: "Neuer Kredit", icon: "plus", run: () => { goToTab("debts"); setTimeout(() => document.getElementById("debt-new-btn")?.click(), 150); } },
  { label: "Neues Ziel", icon: "plus", run: () => { goToTab("goals"); setTimeout(() => document.getElementById("goal-new-btn")?.click(), 150); } },
  { label: "Neues Schweiz-Ziel", icon: "plus", run: () => { goToTab("schweiz"); setTimeout(() => document.getElementById("schweiz-goal-new-btn")?.click(), 150); } },
  { label: "Neue Kategorie", icon: "plus", run: () => { goToTab("categories"); setTimeout(() => document.getElementById("cat-new-btn")?.click(), 150); } },
  { label: "Neues Projekt", icon: "plus", run: () => { goToTab("projects"); setTimeout(() => document.getElementById("project-new-btn")?.click(), 150); } },
  { label: "Neuer Lebensbereich", icon: "plus", run: () => { goToTab("life"); setTimeout(() => document.getElementById("life-area-new-btn")?.click(), 150); } },
  { label: "Neuer Wunsch", icon: "plus", run: () => { goToTab("wishlist"); setTimeout(() => document.getElementById("wishlist-new-btn")?.click(), 150); } },
  { label: "Neuer Kontakt", icon: "plus", run: () => { goToTab("life"); setTimeout(() => document.getElementById("contact-name")?.focus(), 150); } },
  { label: "Neuer Leseliste-Eintrag", icon: "plus", run: () => { goToTab("life"); setTimeout(() => document.getElementById("media-title")?.focus(), 150); } },
  { label: "Gesundheitswert eintragen", icon: "plus", run: () => { goToTab("life"); setTimeout(() => document.getElementById("health-value")?.focus(), 150); } },
  { label: "KI-Assistent öffnen", icon: "sparkles", run: () => document.getElementById("global-ai-fab")?.click() },
  { label: "Jahresrückblick öffnen", icon: "sparkles", run: () => { goToTab("hub"); setTimeout(openYearReview, 150); } },
  { label: "Theme: Dunkel", icon: "palette", run: () => applyTheme("dark") },
  { label: "Theme: Hell", icon: "palette", run: () => applyTheme("light") },
  { label: "Theme: Gelb", icon: "palette", run: () => applyTheme("yellow") },
  { label: "Theme: Alpen", icon: "palette", run: () => applyTheme("alpen") },
  { label: "Theme: Alpen Desktop", icon: "palette", run: () => applyTheme("alpen-desktop") },
];

let cmdkActiveIndex = 0;
let cmdkCurrentItems = [];

function cmdkFilteredItems(query) {
  const q = query.trim().toLowerCase();
  const navItems = CMDK_NAV
    .filter(n => !q || n.label.toLowerCase().includes(q))
    .map(n => ({ label: n.label, icon: n.icon, group: "Seiten", run: cmdkGoTo(n.tab) }));
  const actionItems = CMDK_ACTIONS
    .filter(a => !q || a.label.toLowerCase().includes(q))
    .map(a => ({ label: a.label, icon: a.icon, group: "Aktionen", run: a.run }));
  return [...navItems, ...actionItems];
}

function cmdkRender() {
  const el = document.getElementById("cmdk-results");
  if (!cmdkCurrentItems.length) {
    el.innerHTML = `<div class="cmdk-empty">Nichts gefunden.</div>`;
    return;
  }
  let lastGroup = null;
  const rows = [];
  cmdkCurrentItems.forEach((item, i) => {
    if (item.group !== lastGroup) {
      rows.push(`<div class="cmdk-group-label">${esc(item.group)}</div>`);
      lastGroup = item.group;
    }
    rows.push(`<button type="button" class="cmdk-item ${i === cmdkActiveIndex ? "is-active" : ""}" data-cmdk-index="${i}">
      ${svgIcon(item.icon, "")}
      <span class="cmdk-item-label">${esc(item.label)}</span>
    </button>`);
  });
  el.innerHTML = rows.join("");
}

function cmdkOpen() {
  document.getElementById("cmdk-overlay").classList.remove("hidden");
  const input = document.getElementById("cmdk-input");
  input.value = "";
  clearTimeout(cmdkSearchTimer);
  cmdkSearchGeneration++;
  cmdkCurrentItems = cmdkFilteredItems("");
  cmdkActiveIndex = 0;
  cmdkRender();
  input.focus();
}

function cmdkClose() {
  document.getElementById("cmdk-overlay").classList.add("hidden");
  clearTimeout(cmdkSearchTimer);
  cmdkSearchGeneration++;
}

function cmdkRunActive() {
  const item = cmdkCurrentItems[cmdkActiveIndex];
  if (!item) return;
  cmdkClose();
  item.run();
}

document.getElementById("cmdk-trigger").addEventListener("click", cmdkOpen);
document.getElementById("cmdk-overlay").addEventListener("click", e => {
  if (e.target.id === "cmdk-overlay") cmdkClose();
});
// Globale Suche (Buchungen/Ziele/Projekte/Kontakte/Leseliste/Notizen/Belege,
// siehe crud.global_search) - läuft asynchron NEBEN der sofortigen lokalen
// Seiten-/Aktions-Filterung, statt sie zu ersetzen: Navigation soll nicht auf
// eine Serverantwort warten. Ergebnisse werden als weitere Gruppe angehängt,
// sobald sie da sind. cmdkSearchGeneration verhindert, dass eine spät
// eintreffende Antwort zu einer inzwischen geänderten Eingabe gerendert wird.
const CMDK_SEARCH_ICONS = {
  transaction: "receipt", goal: "target", business_project: "briefcase",
  contact: "user", media: "file-text", note: "file-text", receipt: "file-text",
};
let cmdkSearchGeneration = 0;
let cmdkSearchTimer = null;

function cmdkRunSearchResult(result) {
  return () => goToTab(result.tab);
}

async function cmdkRunSearch(query) {
  const generation = ++cmdkSearchGeneration;
  if (query.trim().length < 2) return;
  let hits;
  try {
    hits = await api(`/search?q=${encodeURIComponent(query.trim())}`);
  } catch (e) {
    return;
  }
  // Eingabefeld hat sich seitdem geändert, oder die Palette wurde geschlossen -
  // diese Antwort ist überholt.
  if (generation !== cmdkSearchGeneration) return;
  if (document.getElementById("cmdk-input").value !== query) return;
  if (!hits.length) return;
  cmdkCurrentItems = [
    ...cmdkCurrentItems,
    ...hits.map(h => ({
      label: h.sublabel ? `${h.label} — ${h.sublabel}` : h.label,
      icon: CMDK_SEARCH_ICONS[h.entity_type] || "file-text",
      group: "Suchergebnisse",
      run: cmdkRunSearchResult(h),
    })),
  ];
  cmdkRender();
}

document.getElementById("cmdk-input").addEventListener("input", e => {
  const query = e.target.value;
  cmdkCurrentItems = cmdkFilteredItems(query);
  cmdkActiveIndex = 0;
  cmdkRender();
  clearTimeout(cmdkSearchTimer);
  cmdkSearchTimer = setTimeout(() => cmdkRunSearch(query), 250);
});
document.getElementById("cmdk-results").addEventListener("click", e => {
  const idx = e.target.closest("[data-cmdk-index]")?.dataset.cmdkIndex;
  if (idx === undefined) return;
  cmdkActiveIndex = parseInt(idx, 10);
  cmdkRunActive();
});
document.getElementById("cmdk-input").addEventListener("keydown", e => {
  if (e.key === "ArrowDown") {
    e.preventDefault();
    cmdkActiveIndex = Math.min(cmdkActiveIndex + 1, cmdkCurrentItems.length - 1);
    cmdkRender();
    document.querySelector(".cmdk-item.is-active")?.scrollIntoView({ block: "nearest" });
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    cmdkActiveIndex = Math.max(cmdkActiveIndex - 1, 0);
    cmdkRender();
    document.querySelector(".cmdk-item.is-active")?.scrollIntoView({ block: "nearest" });
  } else if (e.key === "Enter") {
    e.preventDefault();
    cmdkRunActive();
  } else if (e.key === "Escape") {
    cmdkClose();
  }
});

document.addEventListener("keydown", e => {
  const isK = e.key === "k" || e.key === "K";
  if ((e.metaKey || e.ctrlKey) && isK) {
    e.preventDefault();
    const overlay = document.getElementById("cmdk-overlay");
    overlay.classList.contains("hidden") ? cmdkOpen() : cmdkClose();
  } else if (e.key === "Escape" && !document.getElementById("cmdk-overlay").classList.contains("hidden")) {
    cmdkClose();
  }
});


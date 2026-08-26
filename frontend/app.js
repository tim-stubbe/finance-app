const API = "/api";
let accountsCache = [];
let categoriesCache = [];
let txListCache = [];
let editingTxId = null;
let editingAccId = null;
let editingCatId = null;
let chartInstance = null;
let catIncomeChartInstance = null;
let catExpenseChartInstance = null;
let balanceHistoryChart = null;
let catTrendChartInstance = null;
let holdingsCache = [];
let portfolioHistoryChart = null;
let holdingHistoryChart = null;
let divAssetChart = null;
let divSectorChart = null;
let divPositionChart = null;
let divRegionChart = null;
let divCurrencyChart = null;
let portfolioRange = "1y";
let hmRange = "1y";
let currentHoldingId = null;
let lotsCache = [];
let editingLotId = null;

// ---------- Helpers ----------
// Gespeichert wird überall in EUR - displayCurrency/displayRate steuern nur die
// Anzeige (Umschalter im Topbar). toDisplay() für rohe Zahlen (z.B. Chart-Daten),
// eur() für die formatierte Anzeige - beide immer zusammen verwenden, sonst
// zeigt ein Chart EUR-Werte während die Achsen-Beschriftung schon CHF sagt.
let displayCurrency = "EUR";
let displayRate = 1; // EUR -> displayCurrency

function toDisplay(n) {
  return (n ?? 0) * displayRate;
}
function eur(n) {
  const locale = displayCurrency === "CHF" ? "de-CH" : "de-DE";
  return toDisplay(n).toLocaleString(locale, { style: "currency", currency: displayCurrency });
}
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
const LOT_TYPE_LABELS = { kauf: "Kauf", verkauf: "Verkauf", staking: "Staking-Ertrag", dividende: "Dividende" };
function lotTypeLabel(type) {
  return LOT_TYPE_LABELS[type] || type;
}
function lotTypeColor(type) {
  if (type === "kauf") return cssVar("--pos");
  if (type === "verkauf") return cssVar("--neg");
  if (type === "staking") return cssVar("--accent-strong");
  if (type === "dividende") return cssVar("--warn");
  return cssVar("--accent-strong");
}
// Kurze Bestätigung für Aktionen, bei denen sich sichtbar nichts ändert -
// vor allem die Einstellungs-Formulare, die sonst stumm speichern.
function toast(message, kind = "ok") {
  const host = document.getElementById("toast-host");
  if (!host) return;
  const el = document.createElement("div");
  el.className = `toast toast-${kind}`;
  el.textContent = message;
  host.appendChild(el);
  // Nach dem Ausblenden entfernen, damit sich keine Leichen ansammeln.
  setTimeout(() => {
    el.classList.add("toast-out");
    el.addEventListener("transitionend", () => el.remove(), { once: true });
  }, 2600);
}

// Zentrale Icon-Bibliothek (Lucide-artige Strichzeichnungen) statt bunter Emoji -
// einheitlicher Look, unabhaengig von Betriebssystem/Emoji-Font.
const ICON_PATHS = {
  landmark: '<path d="M3 21h18M4 21V10M20 21V10M12 3L21 8H3z"/><path d="M8 10v7M12 10v7M16 10v7"/>',
  banknote: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="3"/><path d="M6 9v.01M18 15v.01"/>',
  wallet: '<path d="M3 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v2h1a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1h-1v2a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/><circle cx="16" cy="12" r="1.3" fill="currentColor" stroke="none"/>',
  "trending-up": '<path d="M3 17L9 11L13 15L21 6"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/>',
  coins: '<circle cx="9" cy="9" r="6"/><circle cx="15" cy="15" r="6"/>',
  receipt: '<path d="M6 3h12v18l-2.5-1.5L13 21l-2.5-1.5L8 21l-2-1.5V3z"/><path d="M9 8h6M9 12h6M9 16h4"/>',
  tag: '<path d="M12 2H4a2 2 0 0 0-2 2v8l11 11 10-10L12 2z"/><circle cx="7" cy="7" r="1.5" fill="currentColor" stroke="none"/>',
  "file-text": '<path d="M6 2h9l5 5v15H6V2z"/><path d="M14 2v5h5"/><path d="M9 13h6M9 17h6"/>',
  repeat: '<path d="M4 7h13l-3-3M20 17H7l3 3"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none"/>',
  database: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12a8 3 0 0 0 16 0V6"/><path d="M4 12a8 3 0 0 0 16 0"/>',
  "alert-triangle": '<path d="M12 3l9 16H3z"/><path d="M12 9v4M12 16h.01"/>',
  "credit-card": '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M3 10H21"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  "shopping-cart": '<circle cx="9" cy="21" r="1.3"/><circle cx="18" cy="21" r="1.3"/><path d="M2 3h2l2.4 12.4a2 2 0 0 0 2 1.6h8.6a2 2 0 0 0 2-1.6L21 7H6"/>',
  flame: '<path d="M12 22a6 6 0 0 0 6-6c0-2.5-1.5-4-2.5-5.5C14.5 9 14 7 14 5c-2 1.5-3.5 4-3.5 6.5C9 10 8.5 8.5 8.5 7 7 8.5 6 11 6 13.5A6 6 0 0 0 12 22z"/>',
  send: '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/>',
  "check-circle": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.5 2.5L16 9"/>',
  map: '<path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2V6z"/><path d="M9 4v14M15 6v14"/>',
  home: '<path d="M4 11L12 4L20 11"/><path d="M6 10V19a1 1 0 0 0 1 1h4v-5h2v5h4a1 1 0 0 0 1-1V10"/>',
  "layout-grid": '<rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="8" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/><rect x="13" y="13" width="8" height="8" rx="1.5"/>',
  list: '<path d="M4 7H20M4 12H20M4 17H14"/>',
  briefcase: '<rect x="4" y="8" width="16" height="12" rx="1.5"/><path d="M9 8V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/>',
  "banknote-stack": '<path d="M4 6.5h16M4 12h16M4 17.5h9"/><path d="M15 17.5h5"/>',
  image: '<rect x="3" y="6" width="18" height="14" rx="2"/><circle cx="12" cy="13" r="3.5"/><path d="M8 6l1.5-2h5L16 6"/>',
  sparkles: '<path d="M12 3L13.8 8.2L19 10L13.8 11.8L12 17L10.2 11.8L5 10L10.2 8.2L12 3Z"/><path d="M19 14L19.8 16.2L22 17L19.8 17.8L19 20L18.2 17.8L16 17L18.2 16.2L19 14Z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  palette: '<path d="M12 2a10 10 0 1 0 0 20c1.5 0 2-1 2-2s-.5-1.5-.5-2.5A2.5 2.5 0 0 1 16 15h2a4 4 0 0 0 4-4c0-5-4.5-9-10-9z"/><circle cx="7.5" cy="10.5" r="1" fill="currentColor" stroke="none"/><circle cx="12" cy="7.5" r="1" fill="currentColor" stroke="none"/><circle cx="16.5" cy="10.5" r="1" fill="currentColor" stroke="none"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1.08-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 20c0-3.5 3.5-6 8-6s8 2.5 8 6"/>',
};

// Kleine Trendlinie ohne Chart.js-Overhead - reicht fuer 6 Datenpunkte in
// einer 56x22px-Karte locker, spart eine schwere Abhaengigkeit fuer etwas
// rein Dekoratives.
function sparklineSvg(values) {
  if (!values || values.length < 2) return "";
  const w = 56, h = 22, pad = 2;
  const min = Math.min(...values), max = Math.max(...values);
  const range = max - min || 1;
  const step = (w - pad * 2) / (values.length - 1);
  const points = values.map((v, i) => {
    const x = pad + i * step;
    const y = h - pad - ((v - min) / range) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return `<svg class="sparkline" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <polyline points="${points}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
}

function svgIcon(name, cls = "empty-icon-svg") {
  const inner = ICON_PATHS[name];
  if (!inner) return "";
  return `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;
}

function emptyRow(colspan, iconName, text) {
  return `<tr class="empty-row"><td colspan="${colspan}"><div class="empty-state"><span class="empty-icon">${svgIcon(iconName)}</span><span>${text}</span></div></td></tr>`;
}

const ACCOUNT_TYPE_ICONS = { girokonto: "landmark", bargeld: "banknote", sparkonto: "wallet", tagesgeldkonto: "coins", depot: "trending-up", sonstiges: "folder" };
const CATEGORY_TYPE_ICONS = { einnahme: "coins", ausgabe: "receipt" };
// FastAPI liefert bei Validierungsfehlern (422) `detail` als Liste von
// {loc, msg, type}-Objekten statt als Text - naive String-Verkettung ergibt
// dann "[object Object]" statt der eigentlichen Meldung.
function formatApiErrorDetail(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map(d => {
      if (typeof d === "string") return d;
      const field = Array.isArray(d?.loc) ? d.loc.slice(1).join(".") : "";
      return field ? `${field}: ${d?.msg || d}` : (d?.msg || JSON.stringify(d));
    }).join("; ");
  }
  if (detail && typeof detail === "object") return detail.msg || JSON.stringify(detail);
  return String(detail);
}

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const message = formatApiErrorDetail(err.detail ?? res.statusText);
    alert("Fehler: " + message);
    throw new Error(message);
  }
  if (res.status === 204) return null;
  return res.json();
}

// ---------- App-Start ----------
// Es gibt nur noch einen Bereich, das Backend wählt ihn automatisch
// (auth.get_active_space_id) - keine Bereichsauswahl-UI mehr nötig.
const appEl = document.getElementById("app");

function startApp() {
  appEl.classList.remove("hidden");
  init();
}

// ---------- Theme ----------
function getCatColors() {
  return [1, 2, 3, 4, 5, 6, 7, 8].map(i => cssVar(`--cat-${i}`));
}

// Gemeinsames Pie-Chart für Kategorie-Aufschlüsselungen (Dashboard-Ausgaben,
// Kategorien-Tab Einnahmen/Ausgaben) - zerstört eine evtl. vorhandene
// Chart.js-Instanz und gibt die neue zurück, damit der Aufrufer sie in seiner
// eigenen Variable weiterverfolgen kann.
function renderCategoryPieChart(canvasId, existingInstance, labels, values) {
  if (existingInstance) existingInstance.destroy();
  const ctx = document.getElementById(canvasId);
  const total = values.reduce((a, b) => a + b, 0);
  const catColors = getCatColors();
  const colors = labels.map((_, i) => catColors[i % catColors.length]);
  return new Chart(ctx, {
    type: "pie",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: colors,
        borderColor: cssVar("--surface"),
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "right",
          labels: { color: cssVar("--text-secondary"), font: { size: 12 }, boxWidth: 12, padding: 10 },
        },
        tooltip: {
          backgroundColor: cssVar("--surface-2"),
          borderColor: cssVar("--border-strong"),
          borderWidth: 1,
          titleColor: cssVar("--text"),
          bodyColor: cssVar("--text-secondary"),
          padding: 10,
          cornerRadius: 8,
          displayColors: false,
          callbacks: {
            label: ctx => `${eur(ctx.parsed)} (${total ? (ctx.parsed / total * 100).toFixed(0) : 0}%)`,
          },
        },
      },
    },
  });
}

const THEME_BG = { dark: "#0d0d0d", light: "#f4f5f8", yellow: "#fdf6e0", alpen: "#16223a", "alpen-desktop": "#191817" };

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem("financeAppTheme", theme); } catch (e) {}
  const themeColorMeta = document.querySelector('meta[name="theme-color"]');
  if (themeColorMeta) themeColorMeta.setAttribute("content", THEME_BG[theme] || THEME_BG.dark);
  document.querySelectorAll(".theme-option").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.themeOption === theme);
  });
  if (document.getElementById("tab-dashboard").classList.contains("active")) loadDashboard();
  if (document.getElementById("tab-investments").classList.contains("active")) loadInvestmentsTab();
}

document.querySelectorAll(".theme-option").forEach(btn => {
  btn.addEventListener("click", () => applyTheme(btn.dataset.themeOption));
});

function initThemeSwitchUI() {
  let current = "dark";
  try { current = localStorage.getItem("financeAppTheme") || "dark"; } catch (e) {}
  document.querySelectorAll(".theme-option").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.themeOption === current);
  });
}

// ---------- Tabs ----------

const navIndicator = document.querySelector(".nav-indicator");
function moveNavIndicator(btn) {
  if (!navIndicator || !btn) return;
  navIndicator.style.width = btn.offsetWidth + "px";
  navIndicator.style.height = btn.offsetHeight + "px";
  navIndicator.style.transform = `translate(${btn.offsetLeft}px, ${btn.offsetTop}px)`;
}

document.querySelectorAll(".nav-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
    moveNavIndicator(btn);
    if (btn.dataset.tab === "hub") loadHubTab();
    if (btn.dataset.tab === "dashboard") loadDashboard();
    if (btn.dataset.tab === "business") loadBusinessTab();
    if (btn.dataset.tab === "transactions") { loadTransactions(); loadMailInbox(); loadDuplicateTransactions(); }
    if (btn.dataset.tab === "accounts") loadAccounts();
    if (btn.dataset.tab === "recurring") loadRecurringTab();
    if (btn.dataset.tab === "categories") loadCategories();
    if (btn.dataset.tab === "investments") loadInvestmentsTab();
    if (btn.dataset.tab === "debts") loadDebtsTab();
    if (btn.dataset.tab === "goals") loadGoalsTab();
    if (btn.dataset.tab === "schweiz") loadSchweizGoalsTab();
    if (btn.dataset.tab === "ai") loadAiTab();
    if (btn.dataset.tab === "trips") loadTrips();
    if (btn.dataset.tab === "projects") loadProjectsTab();
    if (btn.dataset.tab === "life") loadLifeTab();
    if (btn.dataset.tab === "wishlist") loadWishlistTab();
    if (btn.dataset.tab === "photos") loadPhotosTab();
    if (btn.dataset.tab === "settings") loadSettingsTab();
    if (btn.dataset.tab === "profile") loadProfile();
    loadGlobalTopbar();
  });
});

window.addEventListener("resize", () => moveNavIndicator(document.querySelector(".nav-btn.active")));

// ---------- Count-up animation for stat values ----------
function animateValue(el, from, to, formatFn, duration = 600) {
  const start = performance.now();
  const step = now => {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    el.textContent = formatFn(from + (to - from) * eased);
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// Färbt Beträge, die je nach Lage positiv oder negativ sein können, nach ihrem
// Vorzeichen ein - Zahl und Symbol immer gemeinsam. Ohne das erben solche
// Stellen die Akzentfarbe des Themes; im Alpen-Theme ist die Schweizer Rot,
// wodurch ein positives Vermögen aussieht wie ein Minus.
// Feste Größen (Einnahmen immer grün, Ausgaben/Schulden immer rot) bleiben
// bewusst außen vor - die haben ihre Farbe direkt im HTML.
function applySign(valueEl, value, cardEl) {
  const positive = (value ?? 0) >= 0;
  if (valueEl) {
    valueEl.classList.toggle("pos", positive);
    valueEl.classList.toggle("neg", !positive);
  }
  if (cardEl) {
    cardEl.classList.remove("card-bal");
    cardEl.classList.toggle("card-pos", positive);
    cardEl.classList.toggle("card-neg", !positive);
  }
}

// ================= ACCOUNTS =================
async function loadAccounts() {
  accountsCache = await api("/accounts");
  const tbody = document.getElementById("acc-list");
  tbody.innerHTML = "";
  if (accountsCache.length === 0) {
    tbody.innerHTML = emptyRow(4, "landmark", "Noch keine Konten angelegt. Leg dein erstes Konto an!");
  }
  accountsCache.forEach(a => {
    const tr = document.createElement("tr");
    const icon = ACCOUNT_TYPE_ICONS[a.type] || "folder";
    tr.innerHTML = `<td><span class="row-name"><span class="row-icon">${svgIcon(icon)}</span>${a.name}${a.is_business ? ' <span class="goal-chip">💼 Geschäftlich</span>' : ""}</span></td><td>${a.type}</td>
      <td class="${a.current_balance >= 0 ? "row-amount-pos" : "row-amount-neg"}">${eur(a.current_balance)}</td>
      <td>
        <button class="link-btn" onclick="editAccount(${a.id})">Bearbeiten</button>
        <button class="link-btn" onclick="deleteAccount(${a.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });
  populateAccountSelects();
  loadBalanceLog();
}

async function loadBalanceLog() {
  const panel = document.getElementById("balance-log-panel");
  let log = [];
  try {
    log = await api("/accounts/balance-log");
  } catch (e) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.toggle("hidden", log.length === 0);
  if (!log.length) return;
  const sourceLabel = { app: "App", telegram: "Telegram" };
  document.getElementById("balance-log-list").innerHTML = log.map(l => `
    <tr>
      <td>${esc(l.account_name)}</td>
      <td>${eur(l.old_balance)}</td>
      <td>${eur(l.new_balance)}</td>
      <td>${sourceLabel[l.source] || l.source}</td>
      <td>${new Date(l.created_at).toLocaleString("de-DE")}</td>
    </tr>`).join("");
}

function populateAccountSelects() {
  const selects = [
    document.getElementById("tx-account"),
    document.getElementById("tx-filter-account"),
  ];
  selects.forEach(sel => {
    const keepFirst = sel.id === "tx-filter-account";
    sel.innerHTML = keepFirst ? '<option value="">Alle Konten</option>' : "";
    accountsCache.forEach(a => {
      const opt = document.createElement("option");
      opt.value = a.id; opt.textContent = a.name;
      sel.appendChild(opt);
    });
  });
}

document.getElementById("acc-form").addEventListener("submit", async e => {
  e.preventDefault();
  const payload = {
    name: document.getElementById("acc-name").value,
    type: document.getElementById("acc-type").value,
    is_business: document.getElementById("acc-business").checked,
  };
  if (editingAccId) {
    // Beim Bearbeiten wird statt des Startsaldos der aktuelle Kontostand gezeigt/korrigiert -
    // rechnerisch bleibt initial_balance die Stellschraube (siehe crud.set_balance_by_name).
    const a = accountsCache.find(x => x.id === editingAccId);
    const newCurrentBalance = parseFloat(document.getElementById("acc-current-balance").value || 0);
    payload.initial_balance = round2(a.initial_balance - a.current_balance + newCurrentBalance);
    await api(`/accounts/${editingAccId}`, { method: "PUT", body: JSON.stringify(payload) });
  } else {
    payload.initial_balance = parseFloat(document.getElementById("acc-balance").value || 0);
    await api("/accounts", { method: "POST", body: JSON.stringify(payload) });
  }
  resetAccForm();
  closeAccModal();
  loadAccounts();
  loadGlobalTopbar();
});

function round2(n) {
  return Math.round(n * 100) / 100;
}

function openAccModal() {
  document.getElementById("acc-modal").classList.remove("hidden");
}
function closeAccModal() {
  document.getElementById("acc-modal").classList.add("hidden");
}

window.editAccount = async id => {
  const a = accountsCache.find(x => x.id === id);
  editingAccId = id;
  document.getElementById("acc-name").value = a.name;
  document.getElementById("acc-type").value = a.type;
  document.getElementById("acc-current-balance").value = a.current_balance;
  document.getElementById("acc-business").checked = a.is_business;
  document.getElementById("acc-balance-label").classList.add("hidden");
  document.getElementById("acc-current-balance-label").classList.remove("hidden");
  document.getElementById("acc-current-balance-hint").classList.remove("hidden");
  document.getElementById("acc-cancel").classList.remove("hidden");
  document.getElementById("acc-submit").textContent = "Änderungen speichern";
  document.getElementById("acc-modal-title").textContent = "Konto bearbeiten";
  openAccModal();
};
document.getElementById("acc-new-btn").addEventListener("click", () => {
  resetAccForm();
  document.getElementById("acc-modal-title").textContent = "Neues Konto";
  openAccModal();
});
document.getElementById("acc-modal-close").addEventListener("click", closeAccModal);
document.getElementById("acc-cancel").addEventListener("click", () => {
  resetAccForm();
  closeAccModal();
});
function resetAccForm() {
  editingAccId = null;
  document.getElementById("acc-form").reset();
  document.getElementById("acc-balance-label").classList.remove("hidden");
  document.getElementById("acc-current-balance-label").classList.add("hidden");
  document.getElementById("acc-current-balance-hint").classList.add("hidden");
  document.getElementById("acc-cancel").classList.add("hidden");
  document.getElementById("acc-submit").textContent = "Speichern";
}
window.deleteAccount = async id => {
  if (!confirm("Konto wirklich löschen? Zugehörige Buchungen werden mitgelöscht.")) return;
  await api(`/accounts/${id}`, { method: "DELETE" });
  loadAccounts();
};

// ================= CATEGORIES =================
async function loadCategories() {
  const yearInput = document.getElementById("cat-filter-year");
  const monthSelect = document.getElementById("cat-filter-month");
  if (!yearInput.value) yearInput.value = new Date().getFullYear();
  const year = parseInt(yearInput.value);
  const month = monthSelect.value ? parseInt(monthSelect.value) : null;
  const periodParam = month ? `year=${year}&month=${month}` : `year=${year}`;
  const periodLabel = month ? `${MONTH_NAMES_DE[month - 1]} ${year}` : `${year}`;

  const [categories, yearTotals, periodTotals, mismatches] = await Promise.all([
    api("/categories"), api(`/categories/totals?year=${year}`), api(`/categories/totals?${periodParam}`),
    api("/categories/sign-mismatches"),
  ]);
  categoriesCache = categories;

  const mismatchWarning = document.getElementById("cat-mismatch-warning");
  mismatchWarning.classList.toggle("hidden", mismatches.length === 0);
  if (mismatches.length > 0) {
    const parts = mismatches.map(m => `${esc(m.category_name)} (${m.count})`).join(", ");
    mismatchWarning.innerHTML = `⚠️ ${mismatches.reduce((s, m) => s + m.count, 0)} Buchungen mit unpassendem Vorzeichen für ihre Kategorie
      (z.B. eine Ausgabe-Kategorie mit positivem Betrag) - oft ein Zeichen für falsch zugeordnete Kategorien:
      ${parts}. Im Buchungen-Tab nach Kategorie filtern und prüfen.`;
  }
  document.getElementById("cat-list-year-header").textContent = year === new Date().getFullYear() ? "Dieses Jahr" : String(year);
  const tbody = document.getElementById("cat-list");
  tbody.innerHTML = "";
  if (categoriesCache.length === 0) {
    tbody.innerHTML = emptyRow(5, "tag", "Noch keine Kategorien angelegt.");
  }
  categoriesCache.forEach(c => {
    const parent = categoriesCache.find(p => p.id === c.parent_id);
    const tr = document.createElement("tr");
    const icon = CATEGORY_TYPE_ICONS[c.type] || "tag";
    const total = yearTotals[c.id];
    const totalCls = total == null ? "" : total >= 0 ? "row-amount-pos" : "row-amount-neg";
    tr.innerHTML = `<td><span class="row-name"><span class="row-icon">${svgIcon(icon)}</span>${c.name}</span></td><td>${c.type}</td><td>${parent ? parent.name : "–"}</td>
      <td class="${totalCls}">${total == null ? "–" : eur(total)}</td>
      <td>
        <button class="link-btn" onclick="editCategory(${c.id})">Bearbeiten</button>
        <button class="link-btn" onclick="deleteCategory(${c.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });
  populateCategorySelects();

  document.getElementById("cat-income-chart-title").textContent = `Einnahmen nach Kategorie (${periodLabel})`;
  document.getElementById("cat-expense-chart-title").textContent = `Ausgaben nach Kategorie (${periodLabel})`;

  const totals = periodTotals;
  const incomeCats = categoriesCache.filter(c => c.type === "einnahme" && totals[c.id] > 0);
  const expenseCats = categoriesCache.filter(c => c.type === "ausgabe" && totals[c.id] < 0);
  document.getElementById("cat-charts-grid").classList.toggle("hidden", incomeCats.length === 0 && expenseCats.length === 0);
  catIncomeChartInstance = renderCategoryPieChart(
    "chart-cat-income", catIncomeChartInstance,
    incomeCats.map(c => c.name), incomeCats.map(c => totals[c.id]),
  );
  catExpenseChartInstance = renderCategoryPieChart(
    "chart-cat-expense", catExpenseChartInstance,
    expenseCats.map(c => c.name), expenseCats.map(c => Math.abs(totals[c.id])),
  );

  const trend = await api("/categories/trend?months=12");
  const trendPanel = document.getElementById("cat-trend-panel");
  trendPanel.classList.toggle("hidden", trend.series.length === 0);
  if (trend.series.length > 0) {
    if (catTrendChartInstance) catTrendChartInstance.destroy();
    const catColors = getCatColors();
    // Zu viele Linien machen das Chart unlesbar - die 8 ausgabenstärksten
    // Kategorien reichen für einen Trend-Überblick (Backend sortiert bereits
    // absteigend nach Gesamtsumme).
    const topSeries = trend.series.slice(0, 8);
    catTrendChartInstance = new Chart(document.getElementById("chart-cat-trend"), {
      type: "line",
      data: {
        labels: trend.months.map(m => {
          const [y, mo] = m.split("-");
          return new Date(`${y}-${mo}-01T00:00:00`).toLocaleDateString("de-DE", { month: "short", year: "2-digit" });
        }),
        datasets: topSeries.map((s, i) => ({
          label: s.category_name,
          data: s.points,
          borderColor: catColors[i % catColors.length],
          backgroundColor: catColors[i % catColors.length],
          tension: 0.3,
          pointRadius: 3,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        onClick: (evt, elements) => {
          const points = catTrendChartInstance.getElementsAtEventForMode(evt, "index", { intersect: false }, true);
          const idx = points[0]?.index;
          if (idx == null) return;
          const [y, mo] = trend.months[idx].split("-");
          document.getElementById("cat-filter-year").value = y;
          document.getElementById("cat-filter-month").value = String(parseInt(mo));
          loadCategories();
        },
        onHover: (evt, elements, chart) => {
          chart.canvas.style.cursor = elements.length ? "pointer" : "default";
        },
        plugins: {
          legend: {
            position: "right",
            labels: { color: cssVar("--text-secondary"), font: { size: 12 }, boxWidth: 12, padding: 10 },
          },
          tooltip: {
            backgroundColor: cssVar("--surface-2"),
            borderColor: cssVar("--border-strong"),
            borderWidth: 1,
            titleColor: cssVar("--text"),
            bodyColor: cssVar("--text-secondary"),
            padding: 10,
            cornerRadius: 8,
            callbacks: { label: ctx => `${ctx.dataset.label}: ${eur(ctx.parsed.y)}` },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            border: { display: false },
            ticks: { color: cssVar("--muted"), font: { size: 11 } },
          },
          y: {
            grid: { color: cssVar("--border"), drawTicks: false },
            border: { display: false },
            ticks: { color: cssVar("--muted"), font: { size: 11 }, callback: v => eur(v) },
          },
        },
      },
    });
  }
}

function populateCategorySelects() {
  const txSel = document.getElementById("tx-category");
  const filterSel = document.getElementById("tx-filter-category");
  const parentSel = document.getElementById("cat-parent");
  const bulkSel = document.getElementById("tx-bulk-category");
  txSel.innerHTML = '<option value="">–</option>';
  filterSel.innerHTML = '<option value="">Alle Kategorien</option>';
  parentSel.innerHTML = '<option value="">–</option>';
  bulkSel.innerHTML = '<option value="">– Kategorie wählen –</option>';
  categoriesCache.forEach(c => {
    [txSel, filterSel, parentSel, bulkSel].forEach(sel => {
      const opt = document.createElement("option");
      opt.value = c.id; opt.textContent = `${c.name} (${c.type})`;
      sel.appendChild(opt);
    });
  });
}

document.getElementById("cat-form").addEventListener("submit", async e => {
  e.preventDefault();
  const parentVal = document.getElementById("cat-parent").value;
  const payload = {
    name: document.getElementById("cat-name").value,
    type: document.getElementById("cat-type").value,
    parent_id: parentVal ? parseInt(parentVal) : null,
  };
  if (editingCatId) {
    await api(`/categories/${editingCatId}`, { method: "PUT", body: JSON.stringify(payload) });
  } else {
    await api("/categories", { method: "POST", body: JSON.stringify(payload) });
  }
  resetCatForm();
  closeCatModal();
  loadCategories();
});

function openCatModal() {
  document.getElementById("cat-modal").classList.remove("hidden");
}
function closeCatModal() {
  document.getElementById("cat-modal").classList.add("hidden");
}

window.editCategory = id => {
  const c = categoriesCache.find(x => x.id === id);
  editingCatId = id;
  document.getElementById("cat-name").value = c.name;
  document.getElementById("cat-type").value = c.type;
  document.getElementById("cat-parent").value = c.parent_id || "";
  document.getElementById("cat-cancel").classList.remove("hidden");
  document.getElementById("cat-submit").textContent = "Änderungen speichern";
  document.getElementById("cat-modal-title").textContent = "Kategorie bearbeiten";
  openCatModal();
};
document.getElementById("cat-new-btn").addEventListener("click", () => {
  resetCatForm();
  document.getElementById("cat-modal-title").textContent = "Neue Kategorie";
  openCatModal();
});
document.getElementById("cat-modal-close").addEventListener("click", closeCatModal);
document.getElementById("cat-cancel").addEventListener("click", () => {
  resetCatForm();
  closeCatModal();
});
function resetCatForm() {
  editingCatId = null;
  document.getElementById("cat-form").reset();
  document.getElementById("cat-cancel").classList.add("hidden");
  document.getElementById("cat-submit").textContent = "Speichern";
}
window.deleteCategory = async id => {
  if (!confirm("Kategorie wirklich löschen?")) return;
  await api(`/categories/${id}`, { method: "DELETE" });
  loadCategories();
};

// ================= INVESTMENTS =================
const ASSET_TYPE_LABELS = { aktie: "Aktie", etf: "ETF", anleihe: "Anleihe", krypto: "Krypto", sonstiges: "Sonstiges" };
const HOLDING_SOURCE_LABELS = { scalable: "Scalable Capital", bitvavo: "Bitvavo" };

// Persistente Kopfzeile über allen Tabs. Läuft bewusst separat von loadNetWorth
// (das Karten auf der Investments-Seite füllt) - die Kopfzeile muss existieren
// und aktuell sein, egal welcher Tab gerade offen ist.
async function loadGlobalTopbar() {
  let nw;
  try {
    nw = await api("/net-worth");
  } catch (e) {
    return; // z.B. kein Bereich ausgewählt - Kopfzeile bleibt bei "–"
  }
  const accEl = document.getElementById("gtb-accounts");
  accEl.textContent = eur(nw.accounts_total);
  applySign(accEl, nw.accounts_total);
  const invEl = document.getElementById("gtb-investments");
  invEl.textContent = eur(nw.investments_total);
  applySign(invEl, nw.investments_total);
  const hasDebts = nw.debts_total > 0;
  document.getElementById("gtb-debts-item").classList.toggle("hidden", !hasDebts);
  document.getElementById("gtb-debts").textContent = "−" + eur(nw.debts_total);
  document.getElementById("gtb-total-label").textContent = hasDebts ? "Nettovermögen" : "Gesamtvermögen";
  const totalEl = document.getElementById("gtb-total");
  totalEl.textContent = eur(nw.total);
  applySign(totalEl, nw.total);
}

async function loadNetWorth() {
  const nw = await api("/net-worth");
  const totalEl = document.getElementById("networth-total");
  totalEl.textContent = eur(nw.total);
  applySign(totalEl, nw.total, totalEl.closest(".card"));
  const accEl = document.getElementById("networth-accounts");
  accEl.textContent = eur(nw.accounts_total);
  applySign(accEl, nw.accounts_total, accEl.closest(".card"));
  const invEl = document.getElementById("networth-investments");
  invEl.textContent = eur(nw.investments_total);
  applySign(invEl, nw.investments_total, invEl.closest(".card"));

  // Schulden mindern das Gesamtvermögen. Ohne Schulden bleibt die Ansicht exakt
  // wie vorher - Karte und Bruttohinweis erscheinen erst, wenn es welche gibt.
  const hasDebts = nw.debts_total > 0;
  document.getElementById("networth-debts-card").classList.toggle("hidden", !hasDebts);
  document.getElementById("networth-debts").textContent = "−" + eur(nw.debts_total);
  document.getElementById("networth-total-label").textContent = hasDebts ? "Nettovermögen" : "Gesamtvermögen";
  const note = document.getElementById("networth-gross-note");
  note.classList.toggle("hidden", !hasDebts);
  note.textContent = hasDebts ? `brutto ${eur(nw.gross_total)}` : "";
}

function relativeTimeDe(d) {
  const diffMs = Date.now() - d.getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "gerade eben";
  if (mins < 60) return `vor ${mins} Min.`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `vor ${hours} Std.`;
  const days = Math.round(hours / 24);
  if (days < 7) return `vor ${days} Tag${days === 1 ? "" : "en"}`;
  return d.toLocaleString("de-DE");
}

function renderPricesLastUpdated() {
  const el = document.getElementById("prices-last-updated");
  if (!el) return;
  const timestamps = holdingsCache.map(h => h.price_updated_at).filter(Boolean).map(t => new Date(t));
  if (timestamps.length === 0) {
    el.textContent = holdingsCache.length ? "Kurse noch nie aktualisiert" : "";
    return;
  }
  const oldest = new Date(Math.min(...timestamps));
  const staleCount = holdingsCache.filter(h => !h.price_updated_at).length;
  el.textContent = `Kurse zuletzt aktualisiert: ${relativeTimeDe(oldest)}`
    + (staleCount ? ` (${staleCount} ohne Kurs)` : "");
}

let holdingsSortKey = null;
let holdingsSortDir = 1;

function renderHoldingsTable() {
  const tbody = document.getElementById("holding-list");
  tbody.innerHTML = "";
  if (holdingsCache.length === 0) {
    tbody.innerHTML = emptyRow(9, "trending-up", "Noch keine Positionen angelegt.");
    return;
  }
  let rows = [...holdingsCache];
  if (holdingsSortKey) {
    rows.sort((a, b) => {
      let va = a[holdingsSortKey];
      let vb = b[holdingsSortKey];
      if (typeof va === "string" || typeof vb === "string") {
        va = (va ?? "").toString().toLowerCase();
        vb = (vb ?? "").toString().toLowerCase();
        return va < vb ? -holdingsSortDir : va > vb ? holdingsSortDir : 0;
      }
      va = va ?? -Infinity;
      vb = vb ?? -Infinity;
      return (va - vb) * holdingsSortDir;
    });
  }
  rows.forEach(h => {
    const tr = document.createElement("tr");
    const gainClass = h.gain_abs >= 0 ? "row-amount-pos" : "row-amount-neg";
    tr.innerHTML = `
      <td>${h.name}${h.import_source ? ` <span class="page-sub" title="Automatisch synchronisiert über ${HOLDING_SOURCE_LABELS[h.import_source] || h.import_source}">🔄</span>` : ""}<br><span class="page-sub">${h.symbol}${h.sector ? " · " + h.sector : ""}</span></td>
      <td>${ASSET_TYPE_LABELS[h.asset_type] || h.asset_type}</td>
      <td>${h.quantity}</td>
      <td>${eur(h.purchase_price)}</td>
      <td>${h.current_price != null ? eur(h.current_price) : "–"}</td>
      <td>${eur(h.current_value)}</td>
      <td class="${gainClass}">${eur(h.gain_abs)} (${h.gain_pct.toFixed(1)}%)</td>
      <td><span class="risk-badge risk-badge-${h.risk_level}">${h.risk_level}</span></td>
      <td>
        <button class="link-btn" onclick="openHoldingDetail(${h.id})">Details</button>
        <button class="link-btn" onclick="deleteHolding(${h.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });
}

document.querySelectorAll("#holding-list-head [data-sort-key]").forEach(th => {
  th.addEventListener("click", () => {
    const key = th.dataset.sortKey;
    if (holdingsSortKey === key) {
      holdingsSortDir *= -1;
    } else {
      holdingsSortKey = key;
      holdingsSortDir = 1;
    }
    document.querySelectorAll("#holding-list-head [data-sort-key]").forEach(el => el.classList.remove("sort-asc", "sort-desc"));
    th.classList.add(holdingsSortDir === 1 ? "sort-asc" : "sort-desc");
    renderHoldingsTable();
  });
});

async function loadHoldings() {
  holdingsCache = await api("/holdings");
  loadNetWorth();
  renderPricesLastUpdated();
  renderHoldingsTable();
}

document.getElementById("holding-form").addEventListener("submit", async e => {
  e.preventDefault();
  const payload = {
    asset_type: document.getElementById("holding-type").value,
    name: document.getElementById("holding-name").value,
    symbol: document.getElementById("holding-symbol").value,
    sector: document.getElementById("holding-sector").value || null,
    quantity: parseFloat(document.getElementById("holding-quantity").value),
    purchase_price: parseFloat(document.getElementById("holding-purchase-price").value),
    purchase_date: document.getElementById("holding-purchase-date").value || null,
  };
  const result = await api("/holdings", { method: "POST", body: JSON.stringify(payload) });
  document.getElementById("holding-form").reset();
  closeHoldingModal();
  loadInvestmentsTab();
  if (result.price_warning) toast(result.price_warning);
});

function openHoldingModal() {
  document.getElementById("holding-new-modal").classList.remove("hidden");
}
function closeHoldingModal() {
  document.getElementById("holding-new-modal").classList.add("hidden");
}
document.getElementById("holding-new-btn").addEventListener("click", openHoldingModal);
document.getElementById("holding-new-modal-close").addEventListener("click", closeHoldingModal);

window.deleteHolding = async id => {
  if (!confirm("Position wirklich löschen?")) return;
  await api(`/holdings/${id}`, { method: "DELETE" });
  loadInvestmentsTab();
};

document.getElementById("refresh-prices-btn").addEventListener("click", async () => {
  const resultEl = document.getElementById("price-refresh-result");
  resultEl.textContent = "Aktualisiere Kurse …";
  const result = await api("/holdings/refresh-prices", { method: "POST" });
  resultEl.textContent = `${result.updated} Kurs(e) aktualisiert.`
    + (result.failed.length ? "\nFehlgeschlagen:\n" + result.failed.join("\n") : "");
  loadInvestmentsTab();
});

// ---------- Portfolio-Verlauf ----------
async function loadPortfolioHistoryChart(range) {
  portfolioRange = range || portfolioRange;
  document.querySelectorAll("#portfolio-range-tabs .range-tab").forEach(b => b.classList.toggle("active", b.dataset.range === portfolioRange));
  const noteEl = document.getElementById("portfolio-history-note");
  noteEl.textContent = "Lädt …";
  noteEl.classList.add("loading-pulse");
  let data;
  try {
    data = await api(`/portfolio/history?range=${portfolioRange}`);
  } catch (e) {
    noteEl.textContent = "Portfolio-Verlauf konnte nicht geladen werden.";
    noteEl.classList.remove("loading-pulse");
    return;
  }
  noteEl.classList.remove("loading-pulse");
  noteEl.textContent = data.partial
    ? "Hinweis: mindestens eine Position konnte nicht einbezogen werden (Kurshistorie nicht verfügbar)."
    : "";

  const ctx = document.getElementById("chart-portfolio-history");
  const labels = data.points.map(p => p.date);
  const values = data.points.map(p => p.value);
  const invested = data.points.map(p => p.invested);
  const returnPct = data.points.map(p => p.return_pct);
  if (portfolioHistoryChart) portfolioHistoryChart.destroy();

  const cardsEl = document.getElementById("portfolio-history-summary-cards");
  if (labels.length === 0) {
    cardsEl.innerHTML = "";
    return;
  }
  const last = data.points[data.points.length - 1];
  const gainAbs = last.value - last.invested;
  const gainClass = gainAbs >= 0 ? "pos" : "neg";
  cardsEl.innerHTML = `
    <div class="card"><div><h3>Aktueller Wert</h3><p>${eur(last.value)}</p></div></div>
    <div class="card"><div><h3>Investiert</h3><p>${eur(last.invested)}</p></div></div>
    <div class="card"><div><h3>Gewinn/Verlust</h3><p class="${gainClass}">${eur(gainAbs)}${last.return_pct != null ? ` (${last.return_pct.toFixed(1)}%)` : ""}</p></div></div>`;
  portfolioHistoryChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Portfolio-Wert",
          data: values,
          borderColor: cssVar("--accent-strong"),
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.25,
          fill: true,
          yAxisID: "y",
          backgroundColor: context => {
            const { ctx: c, chartArea } = context.chart;
            if (!chartArea) return cssVar("--accent-wash");
            const gradient = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
            gradient.addColorStop(0, cssVar("--accent-wash"));
            gradient.addColorStop(1, "rgba(0,0,0,0)");
            return gradient;
          },
        },
        {
          label: "Investiertes Kapital",
          data: invested,
          borderColor: cssVar("--muted"),
          borderWidth: 1.5,
          borderDash: [6, 4],
          pointRadius: 0,
          tension: 0.15,
          fill: false,
          yAxisID: "y",
        },
        {
          label: "Rendite (%)",
          data: returnPct,
          borderColor: cssVar("--pos"),
          borderWidth: 1.5,
          borderDash: [4, 3],
          pointRadius: 0,
          tension: 0.25,
          fill: false,
          yAxisID: "y1",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: true, position: "top", align: "end", labels: { color: cssVar("--text-secondary"), boxWidth: 16, font: { size: 12 } } },
        tooltip: {
          backgroundColor: cssVar("--surface-2"), borderColor: cssVar("--border-strong"), borderWidth: 1,
          titleColor: cssVar("--text"), bodyColor: cssVar("--text-secondary"), padding: 10, cornerRadius: 8,
          callbacks: {
            label: c => c.dataset.yAxisID === "y1"
              ? `Rendite: ${c.parsed.y == null ? "–" : c.parsed.y.toFixed(1) + "%"}`
              : `${c.dataset.label}: ${eur(c.parsed.y)}`,
          },
        },
      },
      scales: {
        x: { grid: { display: false }, border: { display: false }, ticks: { color: cssVar("--muted"), maxTicksLimit: 8, font: { size: 11 } } },
        y: {
          position: "left",
          grid: { color: cssVar("--border"), drawTicks: false }, border: { display: false },
          ticks: { color: cssVar("--muted"), font: { size: 11 }, callback: v => eur(v) },
        },
        y1: {
          position: "right",
          grid: { display: false }, border: { display: false },
          ticks: { color: cssVar("--muted"), font: { size: 11 }, callback: v => v + "%" },
        },
      },
    },
  });
}

document.querySelectorAll("#portfolio-range-tabs .range-tab").forEach(btn => {
  btn.addEventListener("click", () => loadPortfolioHistoryChart(btn.dataset.range));
});

// ---------- Diversifikation & Risiko ----------
function renderDonut(canvasId, slices) {
  const ctx = document.getElementById(canvasId);
  const catColors = getCatColors();
  return new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: slices.map(s => s.label),
      datasets: [{
        data: slices.map(s => s.value),
        backgroundColor: slices.map((_, i) => catColors[i % catColors.length]),
        borderColor: cssVar("--surface"),
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom", labels: { color: cssVar("--text-secondary"), boxWidth: 11, font: { size: 11.5 }, padding: 10 } },
        tooltip: {
          backgroundColor: cssVar("--surface-2"), borderColor: cssVar("--border-strong"), borderWidth: 1,
          titleColor: cssVar("--text"), bodyColor: cssVar("--text-secondary"), padding: 10, cornerRadius: 8,
          callbacks: { label: c => `${c.label}: ${eur(c.parsed)} (${slices[c.dataIndex].percent.toFixed(1)}%)` },
        },
      },
    },
  });
}

async function loadDiversification() {
  const data = await api("/portfolio/diversification");
  [divPositionChart, divAssetChart, divSectorChart, divRegionChart, divCurrencyChart].forEach(c => c && c.destroy());
  const assetSlices = data.by_asset_type.map(s => ({ ...s, label: ASSET_TYPE_LABELS[s.label] || s.label }));
  divPositionChart = data.by_position.length ? renderDonut("chart-div-position", data.by_position) : null;
  divAssetChart = assetSlices.length ? renderDonut("chart-div-assettype", assetSlices) : null;
  divSectorChart = data.by_sector.length ? renderDonut("chart-div-sector", data.by_sector) : null;
  divRegionChart = data.by_region.length ? renderDonut("chart-div-region", data.by_region) : null;
  divCurrencyChart = data.by_currency.length ? renderDonut("chart-div-currency", data.by_currency) : null;

  const flagsEl = document.getElementById("risk-flags");
  flagsEl.innerHTML = "";
  if (data.risk_flags.length === 0) {
    flagsEl.innerHTML = '<p class="page-sub">Keine Risikohinweise – Portfolio wirkt gut gestreut.</p>';
  }
  data.risk_flags.forEach(f => {
    const div = document.createElement("div");
    div.className = `risk-flag risk-flag-${f.level}`;
    div.textContent = f.message;
    flagsEl.appendChild(div);
  });
}

// ---------- Rendite-Heatmap ----------
function hexToRgb(hex) {
  const h = hex.trim().replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map(c => c + c).join("") : h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function gainHeatColor(pct) {
  const t = Math.max(-1, Math.min(1, pct / 20));
  const mid = [95, 99, 104];
  const target = hexToRgb(t < 0 ? cssVar("--neg") : cssVar("--pos"));
  const k = Math.abs(t);
  const c = [0, 1, 2].map(i => Math.round(mid[i] + (target[i] - mid[i]) * k));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

async function loadHeatmap() {
  if (!holdingsCache.length) await loadHoldings();
  const grid = document.getElementById("heatmap-grid");
  grid.innerHTML = "";
  if (holdingsCache.length === 0) {
    grid.innerHTML = `<div class="empty-state"><span class="empty-icon">${svgIcon("flame")}</span><span>Noch keine Positionen für die Heatmap.</span></div>`;
    return;
  }
  holdingsCache.forEach(h => {
    const tile = document.createElement("div");
    tile.className = "heatmap-tile";
    tile.style.background = gainHeatColor(h.gain_pct);
    tile.innerHTML = `
      <span class="hm-name">${h.name}</span>
      <span class="hm-pct">${h.gain_pct >= 0 ? "+" : ""}${h.gain_pct.toFixed(1)}%</span>
      <span class="hm-value">${eur(h.current_value)}</span>`;
    grid.appendChild(tile);
  });
}

// ---------- Investments: Unterreiter (Analyse / Dividenden / Steuer) ----------
let dividendsLoaded = false;
let taxLoaded = false;

document.querySelectorAll("#inv-subtabs .range-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#inv-subtabs .range-tab").forEach(b => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".inv-subtab").forEach(s => s.classList.remove("active"));
    document.getElementById(`inv-sub-${btn.dataset.invSubtab}`).classList.add("active");
    if (btn.dataset.invSubtab === "dividenden" && !dividendsLoaded) {
      dividendsLoaded = true;
      loadDividendsTab();
    }
    if (btn.dataset.invSubtab === "steuer" && !taxLoaded) {
      taxLoaded = true;
      loadTaxTab();
    }
  });
});

async function loadInvestmentsTab() {
  loadGlobalTopbar();
  await loadHoldings();
  await loadPortfolioHistoryChart(portfolioRange);
  await loadDiversification();
  await loadHeatmap();
  if (dividendsLoaded) await loadDividendsTab();
  if (taxLoaded) await loadTaxTab();
}

let dividendHistoryChart = null;

async function loadDividendsTab() {
  const [data, upcoming] = await Promise.all([
    api("/portfolio/dividends"),
    api("/portfolio/dividends/upcoming"),
  ]);

  const upcomingPanel = document.getElementById("div-upcoming-panel");
  upcomingPanel.classList.toggle("hidden", upcoming.length === 0);
  document.getElementById("div-upcoming-list").innerHTML = upcoming.map(u => `
    <tr>
      <td>${esc(u.name)}</td>
      <td>${fmtDate(u.estimated_date)}</td>
      <td class="row-amount-pos">${eur(u.estimated_amount)}</td>
    </tr>`).join("");

  document.getElementById("div-summary-cards").innerHTML = `
    <div class="card card-pos">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><path d="M12 19V5M12 5L6 11M12 5L18 11" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
      <div><h3>Jährlich (aktuell, geschätzt)</h3><p class="pos">${eur(data.total_annual_income_estimate)}</p></div>
    </div>
    <div class="card">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><rect x="3" y="3" width="8" height="10" rx="2" stroke="currentColor" stroke-width="1.8"/><rect x="13" y="3" width="8" height="6" rx="2" stroke="currentColor" stroke-width="1.8"/></svg></div>
      <div><h3>Positionen mit Dividende</h3><p>${data.holdings.filter(h => h.annual_rate_per_share > 0).length}</p></div>
    </div>`;

  document.getElementById("div-forecast-cards").innerHTML = `
    <div class="card"><div><h3>Nächste 12 Monate</h3><p>${eur(data.forecast_1y)}</p></div></div>
    <div class="card"><div><h3>Nächste 5 Jahre</h3><p>${eur(data.forecast_5y)}</p></div></div>
    <div class="card"><div><h3>Nächste 10 Jahre</h3><p>${eur(data.forecast_10y)}</p></div></div>`;

  const labels = data.by_year.map(p => String(p.year));
  const values = data.by_year.map(p => p.total);
  if (dividendHistoryChart) dividendHistoryChart.destroy();
  const ctx = document.getElementById("chart-dividend-history");
  if (labels.length === 0) {
    ctx.getContext("2d").clearRect(0, 0, ctx.width, ctx.height);
  } else {
    dividendHistoryChart = new Chart(ctx, {
      type: "bar",
      data: { labels, datasets: [{ data: values, backgroundColor: cssVar("--pos"), borderRadius: 4, maxBarThickness: 44 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: cssVar("--surface-2"), borderColor: cssVar("--border-strong"), borderWidth: 1,
            titleColor: cssVar("--text"), bodyColor: cssVar("--text-secondary"), padding: 10, cornerRadius: 8,
            callbacks: { label: c => eur(c.parsed.y) },
          },
        },
        scales: {
          x: { grid: { display: false }, border: { display: false }, ticks: { color: cssVar("--muted"), font: { size: 11 } } },
          y: { grid: { color: cssVar("--border"), drawTicks: false }, border: { display: false }, ticks: { color: cssVar("--muted"), font: { size: 11 }, callback: v => eur(v) } },
        },
      },
    });
  }

  const tbody = document.getElementById("div-holdings-list");
  tbody.innerHTML = "";
  const withDividends = data.holdings.filter(h => h.history.length > 0 || h.annual_rate_per_share > 0);
  if (withDividends.length === 0) {
    tbody.innerHTML = emptyRow(5, "coins", "Keine Dividenden-Positionen gefunden (Aktien/ETFs mit Ausschüttung).");
  }
  withDividends.forEach(h => {
    const last = h.history[h.history.length - 1];
    const qty = last ? last.quantity : 0;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${h.name}</td>
      <td>${eur(h.annual_rate_per_share)}</td>
      <td>${qty}</td>
      <td class="row-amount-pos">${eur(h.annual_income_estimate)}</td>
      <td>${last ? `${fmtDate(last.date)} · ${eur(last.total)}` : "–"}</td>`;
    tbody.appendChild(tr);
  });
}

// ---------- Investments: Steuer (Vorabpauschale / realisierte Gewinne) ----------
let taxYear = new Date().getFullYear();

function populateTaxYearSelect() {
  const sel = document.getElementById("tax-year");
  if (sel.options.length) return;
  const current = new Date().getFullYear();
  for (let y = current; y >= current - 2; y--) {
    const opt = document.createElement("option");
    opt.value = y; opt.textContent = y;
    sel.appendChild(opt);
  }
  sel.value = taxYear;
}

document.getElementById("tax-year").addEventListener("change", e => {
  taxYear = parseInt(e.target.value);
  loadTaxTab();
});

function renderBasiszinsList(rows) {
  const tbody = document.getElementById("basiszins-list");
  tbody.innerHTML = "";
  rows.forEach(r => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${r.year}</td><td>${r.rate_percent}%</td>`;
    tbody.appendChild(tr);
  });
}

async function loadTaxTab() {
  populateTaxYearSelect();
  const [summary, vorab, realized, sparer, basiszinsRows] = await Promise.all([
    api(`/tax/summary?year=${taxYear}`),
    api(`/tax/vorabpauschale?year=${taxYear}`),
    api(`/tax/realized-gains?year=${taxYear}`),
    api("/tax/sparerpauschbetrag"),
    api("/tax/basiszins"),
  ]);

  document.getElementById("tax-missing-basiszins").style.display = vorab.missing_basiszins ? "block" : "none";

  document.getElementById("tax-summary-cards").innerHTML = `
    <div class="card"><div><h3>Vorabpauschale (steuerpflichtig)</h3><p>${eur(summary.vorabpauschale_total)}</p></div></div>
    <div class="card"><div><h3>Realisierte Gewinne/Verluste</h3><p class="${summary.realized_gain_total >= 0 ? "pos" : "neg"}">${eur(summary.realized_gain_total)}</p></div></div>
    <div class="card"><div><h3>Sparerpauschbetrag</h3><p>${eur(summary.sparerpauschbetrag)}</p></div></div>
    <div class="card card-pos"><div><h3>Voraussichtlich steuerpflichtig</h3><p class="pos">${eur(summary.taxable_after_allowance)}</p></div></div>`;

  const vorabTbody = document.getElementById("tax-vorab-list");
  vorabTbody.innerHTML = "";
  if (vorab.rows.length === 0) {
    vorabTbody.innerHTML = emptyRow(7, "file-text", "Keine ETF-Positionen mit Basiszins für dieses Jahr.");
  }
  vorab.rows.forEach(r => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.name}${r.is_estimate ? ' <span class="page-sub">(Schätzung)</span>' : ""}</td>
      <td>${eur(r.basisertrag)}</td>
      <td>${eur(r.wertsteigerung)}</td>
      <td>${eur(r.ausschuettung)}</td>
      <td>${eur(r.vorabpauschale)}</td>
      <td>${r.teilfreistellung_percent}%</td>
      <td>${eur(r.steuerpflichtiger_betrag)}</td>`;
    vorabTbody.appendChild(tr);
  });

  const realizedTbody = document.getElementById("tax-realized-list");
  realizedTbody.innerHTML = "";
  if (realized.rows.length === 0) {
    realizedTbody.innerHTML = emptyRow(6, "trending-up", "Keine Verkäufe in diesem Jahr.");
  }
  realized.rows.forEach(r => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${fmtDate(r.date)}</td>
      <td>${r.name}</td>
      <td>${r.quantity}</td>
      <td>${eur(r.proceeds)}</td>
      <td>${eur(r.cost_basis)}</td>
      <td class="${r.gain >= 0 ? "row-amount-pos" : "row-amount-neg"}">${eur(r.gain)}</td>`;
    realizedTbody.appendChild(tr);
  });

  document.getElementById("tax-sparerpauschbetrag").value = sparer.amount;
  renderBasiszinsList(basiszinsRows);
}

document.getElementById("tax-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const amount = parseFloat(document.getElementById("tax-sparerpauschbetrag").value);
  await api("/tax/sparerpauschbetrag", { method: "PUT", body: JSON.stringify({ amount }) });
  await loadTaxTab();
  toast(`Sparerpauschbetrag auf ${eur(amount)} gesetzt.`);
});

document.getElementById("basiszins-form").addEventListener("submit", async e => {
  e.preventDefault();
  const year = parseInt(document.getElementById("basiszins-year").value);
  const rate_percent = parseFloat(document.getElementById("basiszins-rate").value);
  await api("/tax/basiszins", { method: "PUT", body: JSON.stringify({ year, rate_percent }) });
  document.getElementById("basiszins-form").reset();
  await loadTaxTab();
  toast(`Basiszins ${year}: ${rate_percent} % gespeichert.`);
});

// ---------- Holding-Detail (Kaufhistorie & Kursverlauf) ----------
function nearestLabelIndex(labels, targetDate) {
  if (!labels.length) return -1;
  const target = new Date(targetDate + "T00:00:00").getTime();
  let bestIdx = 0, bestDiff = Infinity;
  labels.forEach((d, i) => {
    const diff = Math.abs(new Date(d + "T00:00:00").getTime() - target);
    if (diff < bestDiff) { bestDiff = diff; bestIdx = i; }
  });
  return bestIdx;
}

window.openHoldingDetail = async id => {
  currentHoldingId = id;
  hmRange = "1y";
  document.querySelectorAll("#hm-range-tabs .range-tab").forEach(b => b.classList.toggle("active", b.dataset.range === hmRange));
  document.getElementById("holding-modal").classList.remove("hidden");
  document.getElementById("hm-edit-form").classList.add("hidden");
  document.getElementById("lot-holding-id").value = id;
  resetLotForm();
  await loadHoldingDetail(id, hmRange);
};

function closeHoldingDetail() {
  document.getElementById("holding-modal").classList.add("hidden");
  currentHoldingId = null;
}
document.getElementById("holding-modal-close").addEventListener("click", closeHoldingDetail);
document.getElementById("holding-modal").addEventListener("click", e => {
  if (e.target.id === "holding-modal") closeHoldingDetail();
});

document.querySelectorAll("#hm-range-tabs .range-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    hmRange = btn.dataset.range;
    document.querySelectorAll("#hm-range-tabs .range-tab").forEach(b => b.classList.toggle("active", b === btn));
    loadHoldingDetail(currentHoldingId, hmRange);
  });
});

async function loadHoldingDetail(id, range) {
  if (!holdingsCache.length) await loadHoldings();
  const h = holdingsCache.find(x => x.id === id);
  if (!h) return;

  document.getElementById("hm-title").textContent = `${h.name} (${h.symbol})`;
  document.getElementById("hm-sub").innerHTML =
    `${ASSET_TYPE_LABELS[h.asset_type] || h.asset_type}${h.sector ? " · " + h.sector : ""} · `
    + `<span class="risk-badge risk-badge-${h.risk_level}">${h.risk_level}</span>`;

  const gainClass = h.gain_abs >= 0 ? "pos" : "neg";
  document.getElementById("hm-stats").innerHTML = `
    <div class="card"><div><h3>Bestand</h3><p>${h.quantity}</p></div></div>
    <div class="card"><div><h3>Ø Kaufkurs</h3><p>${eur(h.purchase_price)}</p></div></div>
    <div class="card"><div><h3>Aktueller Wert</h3><p>${eur(h.current_value)}</p></div></div>
    <div class="card"><div><h3>Gewinn/Verlust</h3><p class="${gainClass}">${eur(h.gain_abs)} (${h.gain_pct.toFixed(1)}%)</p></div></div>`;

  document.getElementById("hm-edit-id").value = h.id;
  document.getElementById("hm-edit-name").value = h.name;
  document.getElementById("hm-edit-symbol").value = h.symbol;
  document.getElementById("hm-edit-type").value = h.asset_type;
  document.getElementById("hm-edit-sector").value = h.sector || "";

  lotsCache = await api(`/holdings/${id}/lots`);
  renderLotList();

  const noteEl = document.getElementById("hm-history-note");
  noteEl.textContent = "Lädt …";
  noteEl.classList.add("loading-pulse");
  try {
    const history = await api(`/holdings/${id}/history?range=${range}`);
    noteEl.textContent = "";
    renderHoldingHistoryChart(history.points, history.lots);
  } catch (e) {
    noteEl.textContent = "Kurshistorie konnte nicht geladen werden (Symbol prüfen, ggf. über 'Position bearbeiten' korrigieren).";
    if (holdingHistoryChart) { holdingHistoryChart.destroy(); holdingHistoryChart = null; }
  } finally {
    noteEl.classList.remove("loading-pulse");
  }
}

document.getElementById("hm-edit-toggle").addEventListener("click", () => {
  document.getElementById("hm-edit-form").classList.toggle("hidden");
});
document.getElementById("hm-edit-cancel").addEventListener("click", () => {
  document.getElementById("hm-edit-form").classList.add("hidden");
});

document.getElementById("hm-edit-form").addEventListener("submit", async e => {
  e.preventDefault();
  const id = document.getElementById("hm-edit-id").value;
  const payload = {
    name: document.getElementById("hm-edit-name").value,
    symbol: document.getElementById("hm-edit-symbol").value,
    asset_type: document.getElementById("hm-edit-type").value,
    sector: document.getElementById("hm-edit-sector").value || null,
  };
  await api(`/holdings/${id}`, { method: "PUT", body: JSON.stringify(payload) });
  document.getElementById("hm-edit-form").classList.add("hidden");
  await loadHoldings();
  await loadHoldingDetail(parseInt(id), hmRange);
  await loadDiversification();
});

function renderHoldingHistoryChart(points, lots) {
  const ctx = document.getElementById("chart-holding-history");
  const labels = points.map(p => p.date);
  const values = points.map(p => p.price);

  const pointRadius = new Array(labels.length).fill(0);
  const pointColors = new Array(labels.length).fill(cssVar("--accent-strong"));
  const lotAtIndex = {};
  lots.forEach(lot => {
    const idx = nearestLabelIndex(labels, lot.date);
    if (idx === -1) return;
    pointRadius[idx] = 6;
    pointColors[idx] = lotTypeColor(lot.type);
    lotAtIndex[idx] = lot;
  });

  if (holdingHistoryChart) holdingHistoryChart.destroy();
  if (labels.length === 0) return;
  holdingHistoryChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        data: values,
        borderColor: cssVar("--accent-strong"),
        borderWidth: 2,
        pointRadius,
        pointHoverRadius: 7,
        pointBackgroundColor: pointColors,
        pointBorderColor: cssVar("--surface"),
        pointBorderWidth: 1.5,
        tension: 0.2,
        fill: true,
        backgroundColor: context => {
          const { ctx: c, chartArea } = context.chart;
          if (!chartArea) return cssVar("--accent-wash");
          const gradient = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
          gradient.addColorStop(0, cssVar("--accent-wash"));
          gradient.addColorStop(1, "rgba(0,0,0,0)");
          return gradient;
        },
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: cssVar("--surface-2"), borderColor: cssVar("--border-strong"), borderWidth: 1,
          titleColor: cssVar("--text"), bodyColor: cssVar("--text-secondary"), padding: 10, cornerRadius: 8,
          callbacks: {
            label: c => {
              const lot = lotAtIndex[c.dataIndex];
              const base = eur(c.parsed.y);
              return lot ? `${base} — ${lotTypeLabel(lot.type)}: ${lot.quantity} Stk. @ ${eur(lot.price_per_unit)}` : base;
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, border: { display: false }, ticks: { color: cssVar("--muted"), maxTicksLimit: 8, font: { size: 11 } } },
        y: { grid: { color: cssVar("--border"), drawTicks: false }, border: { display: false }, ticks: { color: cssVar("--muted"), font: { size: 11 }, callback: v => eur(v) } },
      },
    },
  });
}

function renderLotList() {
  const tbody = document.getElementById("lot-list");
  tbody.innerHTML = "";
  if (lotsCache.length === 0) {
    tbody.innerHTML = emptyRow(7, "receipt", "Noch keine Transaktionen erfasst.");
  }
  lotsCache.forEach(l => {
    const tr = document.createElement("tr");
    const value = l.quantity * l.price_per_unit;
    tr.innerHTML = `
      <td>${fmtDate(l.date)}</td>
      <td>${lotTypeLabel(l.type)}</td>
      <td>${l.quantity}</td>
      <td>${eur(l.price_per_unit)}</td>
      <td>${eur(value)}</td>
      <td>${l.notes || "–"}</td>
      <td>
        <button class="link-btn" onclick="editLot(${l.id})">Bearbeiten</button>
        <button class="link-btn" onclick="deleteLot(${l.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });
}

document.getElementById("lot-form").addEventListener("submit", async e => {
  e.preventDefault();
  const holdingId = document.getElementById("lot-holding-id").value;
  const payload = {
    date: document.getElementById("lot-date").value,
    type: document.getElementById("lot-type").value,
    quantity: parseFloat(document.getElementById("lot-quantity").value),
    price_per_unit: parseFloat(document.getElementById("lot-price").value),
    notes: document.getElementById("lot-notes").value || null,
  };
  if (editingLotId) {
    await api(`/holdings/${holdingId}/lots/${editingLotId}`, { method: "PUT", body: JSON.stringify(payload) });
  } else {
    await api(`/holdings/${holdingId}/lots`, { method: "POST", body: JSON.stringify(payload) });
  }
  resetLotForm();
  await loadHoldingDetail(holdingId, hmRange);
  await loadHoldings();
});

window.editLot = id => {
  const lot = lotsCache.find(l => l.id === id);
  if (!lot) return;
  editingLotId = id;
  document.getElementById("lot-date").value = lot.date;
  document.getElementById("lot-type").value = lot.type;
  document.getElementById("lot-quantity").value = lot.quantity;
  document.getElementById("lot-price").value = lot.price_per_unit;
  document.getElementById("lot-notes").value = lot.notes || "";
  document.getElementById("lot-cancel").style.display = "inline-block";
  document.getElementById("lot-submit").textContent = "Änderungen speichern";
};

document.getElementById("lot-cancel").addEventListener("click", resetLotForm);
function resetLotForm() {
  editingLotId = null;
  document.getElementById("lot-form").reset();
  document.getElementById("lot-date").value = new Date().toISOString().slice(0, 10);
  document.getElementById("lot-cancel").style.display = "none";
  document.getElementById("lot-submit").textContent = "Hinzufügen";
}

window.deleteLot = async id => {
  if (!confirm("Diese Transaktion wirklich löschen?")) return;
  const holdingId = document.getElementById("lot-holding-id").value;
  await api(`/holdings/${holdingId}/lots/${id}`, { method: "DELETE" });
  await loadHoldingDetail(holdingId, hmRange);
  await loadHoldings();
};

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
    resultEl.textContent = result.error ? `Fehler: ${result.error}` : result.text;
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

// ================= BELEG-CHAT =================
let belegChatHistory = [];

function appendChatBubble(role, text, logId = "beleg-chat-log") {
  const log = document.getElementById(logId);
  const div = document.createElement("div");
  div.className = `chat-msg ${role}`;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function showChatTyping(logId = "beleg-chat-log") {
  const log = document.getElementById(logId);
  const div = document.createElement("div");
  div.className = "chat-typing";
  div.id = `${logId}-typing`;
  div.innerHTML = "<span></span><span></span><span></span>";
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function hideChatTyping(logId = "beleg-chat-log") {
  document.getElementById(`${logId}-typing`)?.remove();
}

function renderBelegProposal(proposal, attachmentFilename, attachmentBase64, logId = "beleg-chat-log") {
  const wrap = document.createElement("div");
  wrap.className = "beleg-proposal";

  if (proposal.type === "update_category" || proposal.type === "mark_transfer") {
    const match = proposal.resolved_transaction;
    if (!match) {
      wrap.innerHTML = `
        <h4>${proposal.type === "mark_transfer" ? "Vorschlag: Als Umbuchung markieren" : "Vorschlag: Kategorie setzen"}</h4>
        <p class="beleg-warning">⚠️ ${esc(proposal.resolution_error || "Buchung konnte nicht eindeutig zugeordnet werden.")}</p>`;
      const log = document.getElementById(logId);
      log.appendChild(wrap);
      log.scrollTop = log.scrollHeight;
      return;
    }
    const label = proposal.type === "mark_transfer"
      ? "als Umbuchung markieren (zählt dann nicht mehr als Einnahme/Ausgabe)"
      : `Kategorie auf „${esc(proposal.category ?? "")}“ setzen`;
    wrap.innerHTML = `
      <h4>${proposal.type === "mark_transfer" ? "Vorschlag: Als Umbuchung markieren" : "Vorschlag: Kategorie setzen"}</h4>
      <p class="goal-meta">${fmtDate(match.date)} · ${eur(match.amount)} · ${esc(match.description || "ohne Beschreibung")}</p>
      <p>${label}</p>
      <div class="form-actions">
        <button type="button" class="btn-primary" data-action="apply">Übernehmen</button>
        <button type="button" class="btn-ghost" data-action="discard">Verwerfen</button>
      </div>`;
    const log = document.getElementById(logId);
    log.appendChild(wrap);
    log.scrollTop = log.scrollHeight;
    wrap.querySelector('[data-action="discard"]').addEventListener("click", () => wrap.remove());
    wrap.querySelector('[data-action="apply"]').addEventListener("click", async () => {
      const body = {
        type: proposal.type,
        data: proposal.type === "mark_transfer"
          ? { transaction_id: match.id }
          : { transaction_id: match.id, category: proposal.category },
      };
      try {
        const result = await api("/ai/beleg-chat/apply", { method: "POST", body: JSON.stringify(body) });
        wrap.classList.add("applied");
        wrap.querySelectorAll("button").forEach(el => { el.disabled = true; });
        appendChatBubble("assistant", "✅ " + result.message, logId);
        await loadTransactions();
        await loadGlobalTopbar();
      } catch (e) {
        // api() zeigt den Fehler bereits per alert() an
      }
    });
    return;
  }

  if (proposal.type === "create_debt") {
    const accOptionsDebt = [`<option value="">– kein Konto –</option>`]
      .concat(accountsCache.map(a => `<option value="${a.id}" ${a.id === proposal.resolved_account_id ? "selected" : ""}>${a.name}</option>`))
      .join("");
    const payments = proposal.payments || [];
    const paymentRows = payments.map((p, i) => `
      <div class="beleg-proposal-payment" data-payment-row="${i}">
        <label>Datum <input type="date" data-pay-field="date" value="${p.date || ""}"></label>
        <label>Betrag (€) <input type="number" step="0.01" data-pay-field="total_amount" value="${p.total_amount ?? ""}"></label>
        <label>davon Zinsen (€) <input type="number" step="0.01" data-pay-field="interest_amount" value="${p.interest_amount ?? ""}" placeholder="automatisch"></label>
        <p class="goal-meta">${p.resolved_transaction_label
          ? "✅ verknüpft mit Buchung: " + esc(p.resolved_transaction_label)
          : "⚠️ keine passende Buchung gefunden – wird ohne Verknüpfung angelegt"}</p>
      </div>`).join("") || "<p class=\"goal-meta\">Keine bereits geleisteten Zahlungen.</p>";
    wrap.innerHTML = `
      <h4>Vorschlag: Schuld/Ratenkauf</h4>
      ${proposal.account_description && !proposal.resolved_account_id
        ? `<p class="beleg-warning">⚠️ Konto „${esc(proposal.account_description)}“ nicht eindeutig gefunden – bitte manuell wählen.</p>` : ""}
      <div class="form-grid">
        <label class="wide">Name <input type="text" data-field="name" value="${esc(proposal.name ?? "")}"></label>
        <label>Gläubiger <input type="text" data-field="lender" value="${esc(proposal.lender ?? "")}"></label>
        <label>Konto <select data-field="account_id">${accOptionsDebt}</select></label>
        <label>Finanzierter Betrag (€) <input type="number" step="0.01" data-field="original_amount" value="${proposal.original_amount ?? ""}"></label>
        <label>Zinssatz (% p.a.) <input type="number" step="0.01" data-field="interest_rate_percent" value="${proposal.interest_rate_percent ?? ""}"></label>
        <label>Monatliche Rate (€) <input type="number" step="0.01" data-field="monthly_payment" value="${proposal.monthly_payment ?? ""}"></label>
        <label>Start <input type="date" data-field="start_date" value="${proposal.start_date || ""}"></label>
        <label>Geplantes Ende <input type="date" data-field="planned_end_date" value="${proposal.planned_end_date || ""}"></label>
        <label class="wide">Notizen <input type="text" data-field="notes" value="${esc(proposal.notes ?? "")}"></label>
      </div>
      <h5>Bereits geleistete Zahlungen</h5>
      ${paymentRows}
      <div class="form-actions">
        <button type="button" class="btn-primary" data-action="apply">Schuld anlegen</button>
        <button type="button" class="btn-ghost" data-action="discard">Verwerfen</button>
      </div>`;
    const log = document.getElementById(logId);
    log.appendChild(wrap);
    log.scrollTop = log.scrollHeight;
    wrap.querySelector('[data-action="discard"]').addEventListener("click", () => wrap.remove());
    wrap.querySelector('[data-action="apply"]').addEventListener("click", async () => {
      const fields = {};
      wrap.querySelectorAll("[data-field]").forEach(el => { fields[el.dataset.field] = el.value; });
      const editedPayments = Array.from(wrap.querySelectorAll("[data-payment-row]")).map((row, i) => {
        const pf = {};
        row.querySelectorAll("[data-pay-field]").forEach(el => { pf[el.dataset.payField] = el.value; });
        return {
          date: pf.date, total_amount: pf.total_amount,
          interest_amount: pf.interest_amount || null,
          resolved_transaction_id: payments[i]?.resolved_transaction_id ?? null,
          notes: payments[i]?.notes ?? null,
        };
      });
      const body = {
        type: "create_debt",
        data: {
          ...fields,
          resolved_account_id: fields.account_id ? parseInt(fields.account_id) : null,
          payments: editedPayments,
        },
      };
      try {
        const result = await api("/ai/beleg-chat/apply", { method: "POST", body: JSON.stringify(body) });
        wrap.classList.add("applied");
        wrap.querySelectorAll("button, input, select").forEach(el => { el.disabled = true; });
        appendChatBubble("assistant", "✅ " + result.message, logId);
      } catch (e) {
        // api() zeigt den Fehler bereits per alert() an
      }
    });
    return;
  }

  if (proposal.type === "transaction") {
    const accOptions = accountsCache.map(a => `<option value="${a.id}">${a.name}</option>`).join("");
    const dupWarning = (proposal.duplicate_matches || []).length
      ? `<p class="beleg-warning">⚠️ Ähnliche Buchung bereits vorhanden: ${proposal.duplicate_matches.map(m =>
          `${fmtDate(m.date)}, ${eur(m.amount)}${m.description ? " – " + m.description : ""}`).join("; ")}</p>`
      : "";
    const receiptMatchBlock = (proposal.receipt_matches || []).length
      ? `<div class="beleg-receipt-match">
           <p>📎 Passt evtl. zu einer bestehenden Buchung ohne Beleg – statt einer neuen Buchung stattdessen nur den Beleg anhängen?</p>
           ${proposal.receipt_matches.map(m => `
             <button type="button" class="btn-ghost" data-action="attach-receipt" data-tx-id="${m.id}">
               An Buchung vom ${fmtDate(m.date)} über ${eur(m.amount)}${m.description ? " (" + m.description + ")" : ""} anhängen
             </button>`).join("")}
         </div>`
      : "";
    wrap.innerHTML = `
      <h4>Vorschlag: Buchung</h4>
      ${dupWarning}
      <div class="form-grid">
        <label>Datum <input type="date" data-field="date" value="${proposal.date || ""}"></label>
        <label>Betrag (€) <input type="number" step="0.01" data-field="amount" value="${proposal.amount ?? ""}"></label>
        <label class="wide">Beschreibung <input type="text" data-field="description" value="${proposal.description ?? ""}"></label>
        <label>Konto <select data-field="account_id">${accOptions}</select></label>
      </div>
      <div class="form-actions">
        <button type="button" class="btn-primary" data-action="apply">Als neue Buchung übernehmen</button>
        <button type="button" class="btn-ghost" data-action="discard">Verwerfen</button>
      </div>
      ${receiptMatchBlock}`;
  } else if (proposal.type === "holding_lot") {
    const assetTypes = ["aktie", "etf", "anleihe", "krypto", "sonstiges"];
    const assetOptions = assetTypes.map(a => `<option value="${a}" ${a === proposal.asset_type ? "selected" : ""}>${a}</option>`).join("");
    const lotOptions = Object.keys(LOT_TYPE_LABELS).map(t => `<option value="${t}" ${t === proposal.lot_type ? "selected" : ""}>${LOT_TYPE_LABELS[t]}</option>`).join("");
    wrap.innerHTML = `
      <h4>Vorschlag: Investment-Position</h4>
      <div class="form-grid">
        <label>Anlageklasse <select data-field="asset_type">${assetOptions}</select></label>
        <label>Typ <select data-field="lot_type">${lotOptions}</select></label>
        <label>Name <input type="text" data-field="name" value="${proposal.name ?? ""}"></label>
        <label>Symbol <input type="text" data-field="symbol" value="${proposal.symbol ?? ""}"></label>
        <label>Datum <input type="date" data-field="date" value="${proposal.date || ""}"></label>
        <label>Stückzahl <input type="number" step="0.00000001" data-field="quantity" value="${proposal.quantity ?? ""}"></label>
        <label>Preis/Stück (€) <input type="number" step="0.0001" data-field="price_per_unit" value="${proposal.price_per_unit ?? ""}"></label>
      </div>
      <div class="form-actions">
        <button type="button" class="btn-primary" data-action="apply">Übernehmen</button>
        <button type="button" class="btn-ghost" data-action="discard">Verwerfen</button>
      </div>`;
  } else {
    return;
  }

  const log = document.getElementById(logId);
  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;

  wrap.querySelector('[data-action="discard"]').addEventListener("click", () => wrap.remove());
  wrap.querySelector('[data-action="apply"]').addEventListener("click", async () => {
    const fields = {};
    wrap.querySelectorAll("[data-field]").forEach(el => { fields[el.dataset.field] = el.value; });
    const body = { type: proposal.type, data: fields };
    if (proposal.type === "transaction") {
      body.account_id = parseInt(fields.account_id);
      delete fields.account_id;
      body.attachment_filename = attachmentFilename || null;
      body.attachment_base64 = attachmentBase64 || null;
    }
    try {
      const result = await api("/ai/beleg-chat/apply", { method: "POST", body: JSON.stringify(body) });
      wrap.classList.add("applied");
      wrap.querySelectorAll("button, input, select").forEach(el => { el.disabled = true; });
      appendChatBubble("assistant", "✅ " + result.message, logId);
      if (proposal.type === "transaction") { await loadTransactions(); await loadGlobalTopbar(); }
      if (proposal.type === "holding_lot") await loadInvestmentsTab();
    } catch (e) {
      // api() zeigt den Fehler bereits per alert() an
    }
  });

  wrap.querySelectorAll('[data-action="attach-receipt"]').forEach(btn => {
    btn.addEventListener("click", async () => {
      const body = {
        type: "attach_receipt",
        data: { transaction_id: parseInt(btn.dataset.txId) },
        attachment_filename: attachmentFilename || null,
        attachment_base64: attachmentBase64 || null,
      };
      try {
        const result = await api("/ai/beleg-chat/apply", { method: "POST", body: JSON.stringify(body) });
        wrap.classList.add("applied");
        wrap.querySelectorAll("button, input, select").forEach(el => { el.disabled = true; });
        appendChatBubble("assistant", "✅ " + result.message, logId);
        await loadTransactions();
      } catch (e) {
        // api() zeigt den Fehler bereits per alert() an
      }
    });
  });
}

document.getElementById("beleg-chat-form").addEventListener("submit", async e => {
  e.preventDefault();
  const msgInput = document.getElementById("beleg-chat-message");
  const fileInput = document.getElementById("beleg-chat-file");
  const message = msgInput.value.trim();
  const file = fileInput.files[0];
  if (!message && !file) return;
  if (!accountsCache.length) await loadAccounts();

  appendChatBubble("user", message || `📎 ${file.name}`);
  const statusEl = document.getElementById("beleg-chat-status");
  const sendBtn = document.getElementById("beleg-chat-send");
  statusEl.textContent = "";
  sendBtn.disabled = true;
  showChatTyping("beleg-chat-log");

  const fd = new FormData();
  fd.append("message", message);
  fd.append("history", JSON.stringify(belegChatHistory));
  if (file) fd.append("file", file);

  try {
    const result = await api("/ai/beleg-chat", { method: "POST", body: fd });
    hideChatTyping("beleg-chat-log");
    if (result.error) {
      appendChatBubble("assistant", "Fehler: " + result.error);
    } else {
      appendChatBubble("assistant", result.reply);
      belegChatHistory.push({ role: "user", content: message || "(Anhang gesendet)" });
      belegChatHistory.push({ role: "assistant", content: result.reply });
      (result.proposals || []).forEach(p => {
        renderBelegProposal(p, result.attachment_filename, result.attachment_base64);
      });
    }
  } catch (e) {
    hideChatTyping("beleg-chat-log");
    // api() zeigt den Fehler bereits per alert() an
  }
  statusEl.textContent = "";
  sendBtn.disabled = false;
  msgInput.value = "";
  fileInput.value = "";
});

async function loadBelegChatModelSelect() {
  const sel = document.getElementById("beleg-chat-model");
  const s = await api("/settings/ollama");
  if (!s.url) return;
  try {
    const result = await api(`/ollama/models?url=${encodeURIComponent(s.url)}`);
    sel.innerHTML = '<option value="">Wie Standard-Modell</option>';
    result.models.forEach(m => {
      const opt = document.createElement("option");
      opt.value = m; opt.textContent = m;
      sel.appendChild(opt);
    });
    sel.value = s.beleg_chat_model || "";
  } catch (e) {
    // Ollama evtl. nicht erreichbar - Dropdown bleibt beim Default-Eintrag
  }
}

document.getElementById("beleg-chat-model").addEventListener("change", async e => {
  const s = await api("/settings/ollama");
  await api("/settings/ollama", { method: "PUT", body: JSON.stringify({ url: s.url, model: s.model, beleg_chat_model: e.target.value || null }) });
  toast(e.target.value ? `Bild-Modell: ${e.target.value}` : "Bild-Modell: wie Standard-Modell");
});

// ================= TRIPS (URLAUBE) =================
let tripsCache = [];

function fmtDate(d) {
  if (!d) return "";
  return new Date(d + "T00:00:00").toLocaleDateString("de-DE");
}

async function loadTrips() {
  tripsCache = await api("/trips");
  populateTripSelects();
  const grid = document.getElementById("trip-grid");
  grid.innerHTML = "";
  if (tripsCache.length === 0) {
    grid.innerHTML = `<div class="empty-state"><span class="empty-icon">${svgIcon("map")}</span><span>Noch keine Urlaube angelegt.</span></div>`;
  }
  tripsCache.forEach(t => {
    const card = document.createElement("div");
    card.className = "trip-card";
    const hasDates = t.start_date || t.end_date;
    let budgetHtml = "";
    if (t.budget) {
      const pct = Math.min(100, (t.total_spent / t.budget) * 100);
      const cls = t.total_spent > t.budget ? "over" : pct >= 80 ? "warn" : "ok";
      budgetHtml = `
        <div class="budget-track"><div class="budget-fill ${cls}" style="width:${pct}%"></div></div>
        <p class="trip-meta">${eur(t.total_spent)} von ${eur(t.budget)} Budget
          ${t.total_spent > t.budget ? ` – ${eur(t.total_spent - t.budget)} über Budget` : ""}</p>`;
    }
    card.innerHTML = `
      <h4><span class="row-icon"><svg class="panel-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2V6z"/><path d="M9 4v14M15 6v14"/></svg></span>${t.name}</h4>
      ${hasDates ? `<p class="trip-dates">${fmtDate(t.start_date)} – ${fmtDate(t.end_date)}</p>` : ""}
      <div class="trip-total">${eur(t.total_spent)}</div>
      ${budgetHtml}
      <p class="trip-meta">${t.transaction_count} Buchung(en)</p>
      <button class="link-btn" onclick="deleteTrip(${t.id})">Löschen</button>`;
    grid.appendChild(card);
  });
}

function populateTripSelects() {
  const txSel = document.getElementById("tx-trip");
  const filterSel = document.getElementById("tx-filter-trip");
  txSel.innerHTML = '<option value="">–</option>';
  filterSel.innerHTML = '<option value="">Alle Urlaube</option>';
  tripsCache.forEach(t => {
    [txSel, filterSel].forEach(sel => {
      const opt = document.createElement("option");
      opt.value = t.id; opt.textContent = t.name;
      sel.appendChild(opt);
    });
  });
}

document.getElementById("trip-form").addEventListener("submit", async e => {
  e.preventDefault();
  const name = document.getElementById("trip-name").value;
  const start_date = document.getElementById("trip-start").value || null;
  const end_date = document.getElementById("trip-end").value || null;
  const budgetVal = document.getElementById("trip-budget").value;
  const budget = budgetVal ? parseFloat(budgetVal) : null;
  await api("/trips", { method: "POST", body: JSON.stringify({ name, start_date, end_date, budget }) });
  document.getElementById("trip-form").reset();
  closeTripModal();
  loadTrips();
});

function openTripModal() {
  document.getElementById("trip-modal").classList.remove("hidden");
}
function closeTripModal() {
  document.getElementById("trip-modal").classList.add("hidden");
}
document.getElementById("trip-new-btn").addEventListener("click", openTripModal);
document.getElementById("trip-modal-close").addEventListener("click", closeTripModal);

window.deleteTrip = async id => {
  if (!confirm("Urlaub wirklich löschen? Zugehörige Buchungen bleiben erhalten, verlieren aber die Zuordnung.")) return;
  await api(`/trips/${id}`, { method: "DELETE" });
  loadTrips();
};

// ================= PROJEKTE (Nebengeschäfte) =================
let projectsCache = [];

async function loadProjectsTab() {
  if (!accountsCache.length) await loadAccounts();
  document.getElementById("project-account").innerHTML = '<option value="">– keins –</option>' +
    accountsCache.map(a => `<option value="${a.id}">${esc(a.name)}</option>`).join("");
  const [projects, issues] = await Promise.all([
    api("/business-projects"),
    api("/business-issues"),
  ]);
  projectsCache = projects;
  const issuesByProject = new Map();
  issues.forEach(i => {
    if (!issuesByProject.has(i.project_id)) issuesByProject.set(i.project_id, []);
    issuesByProject.get(i.project_id).push(i);
  });

  const list = document.getElementById("projects-list");
  if (!projects.length) {
    list.innerHTML = `<div class="empty-state"><span class="empty-icon">${svgIcon("briefcase")}</span><span>Noch keine Projekte angelegt. Leg oben rechts eins an.</span></div>`;
  } else {
    list.innerHTML = "";
    projects.forEach(p => list.appendChild(renderProjectCard(p, issuesByProject.get(p.id) || [])));
  }

  const totalOpen = issues.length;
  const badge = document.getElementById("projects-nav-badge");
  badge.textContent = totalOpen;
  badge.classList.toggle("hidden", !totalOpen);

  loadProjectTimeSummaries();
}

function fmtMinutes(min) {
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return h > 0 ? `${h} Std. ${m} Min.` : `${m} Min.`;
}

// Zeiterfassung pro Projekt - eine Summary fuer alle Projekte auf einmal statt
// eines Aufrufs je Karte, damit das Laden der Projekte-Liste nicht mit der
// Anzahl Projekte langsamer wird.
async function loadProjectTimeSummaries() {
  const summaries = await api("/time-entries/summary");
  const byProject = new Map(summaries.map(s => [s.project_id, s]));
  projectsCache.forEach(p => {
    const s = byProject.get(p.id);
    const el = document.getElementById(`project-time-${p.id}`);
    const btn = document.querySelector(`[data-project-time-toggle="${p.id}"]`);
    if (!el || !btn) return;
    const running = s && s.running_entry_id;
    el.textContent = s && s.total_minutes > 0 ? `⏱ ${fmtMinutes(s.total_minutes)} erfasst` : "";
    btn.textContent = running ? "⏹ Stoppen" : "⏱ Start";
    btn.dataset.projectTimeRunning = running ? s.running_entry_id : "";
    btn.classList.toggle("btn-warn", !!running);
  });
}

document.getElementById("projects-list").addEventListener("click", async e => {
  const toggleId = e.target.closest("[data-project-time-toggle]")?.dataset.projectTimeToggle;
  if (toggleId) {
    const btn = e.target.closest("[data-project-time-toggle]");
    if (btn.dataset.projectTimeRunning) {
      await api(`/time-entries/${btn.dataset.projectTimeRunning}/stop`, { method: "POST" });
    } else {
      await api(`/projects/${toggleId}/time-entries/start`, { method: "POST" });
    }
    loadProjectTimeSummaries();
  }
});

function projectIsOverdue(p) {
  if (!p.check_interval_days) return false;
  // Fallback auf created_at spiegelt main._scheduled_business_check_reminder -
  // ohne das galt ein gerade erst angelegtes Projekt sofort als überfällig.
  const reference = new Date(p.last_checked_at || p.created_at);
  const days = (Date.now() - reference.getTime()) / (1000 * 60 * 60 * 24);
  return days >= p.check_interval_days;
}

function renderProjectCard(p, openIssues) {
  const card = document.createElement("div");
  card.className = "goal-card";
  const overdue = projectIsOverdue(p);
  const lastChecked = p.last_checked_at
    ? new Date(p.last_checked_at).toLocaleDateString("de-DE")
    : "noch nie geprüft";
  card.innerHTML = `
    <div class="goal-card-head">
      <h4>${esc(p.name)}</h4>
      <span class="goal-chip ${openIssues.length ? "is-warn" : ""}">${openIssues.length} offen</span>
    </div>
    ${p.description ? `<p class="goal-desc">${esc(p.description)}</p>` : ""}
    ${p.account_name ? `<p class="goal-values">${esc(p.account_name)} · diesen Monat ${eur(p.income_this_month)} · gesamt ${eur(p.income_total)}</p>` : ""}
    <p class="goal-meta ${overdue ? "goal-error" : ""}">
      ${overdue ? "⚠️ " : ""}Zuletzt geprüft: ${lastChecked}${p.check_interval_days ? ` · Intervall ${p.check_interval_days} Tage` : ""}
    </p>
    <div id="project-issues-${p.id}" class="todo-row-list"></div>
    <p class="goal-meta" id="project-time-${p.id}"></p>
    <div class="filter-row" style="margin-top:4px">
      <button type="button" class="btn-ghost btn-sm" data-project-checked="${p.id}">✓ Geprüft</button>
      <button type="button" class="btn-ghost btn-sm" data-project-add-issue="${p.id}">+ Punkt</button>
      <button type="button" class="btn-ghost btn-sm" data-project-time-toggle="${p.id}">⏱ …</button>
      <button type="button" class="link-btn" data-project-edit="${p.id}">Bearbeiten</button>
      <button type="button" class="link-btn" data-notes-entity="business_project" data-notes-id="${p.id}" data-notes-label="${esc(p.name)}">📝 Notizen</button>
    </div>
  `;
  const issuesWrap = card.querySelector(`#project-issues-${p.id}`);
  issuesWrap.innerHTML = openIssues.map(i => `
    <div class="todo-row">
      <span class="todo-title">${esc(i.title)}${i.notes ? `<br><span class="page-sub">${esc(i.notes)}</span>` : ""}</span>
      <button type="button" class="link-btn" data-issue-resolve="${i.id}">✓ Erledigt</button>
    </div>
  `).join("");
  return card;
}

document.getElementById("projects-list").addEventListener("click", async e => {
  const checkedId = e.target.closest("[data-project-checked]")?.dataset.projectChecked;
  if (checkedId) {
    await api(`/business-projects/${checkedId}/checked`, { method: "POST" });
    toast("Als geprüft bestätigt.");
    loadProjectsTab();
    return;
  }
  const addIssueId = e.target.closest("[data-project-add-issue]")?.dataset.projectAddIssue;
  if (addIssueId) {
    document.getElementById("project-issue-project-id").value = addIssueId;
    document.getElementById("project-issue-form").reset();
    document.getElementById("project-issue-modal").classList.remove("hidden");
    return;
  }
  const editId = e.target.closest("[data-project-edit]")?.dataset.projectEdit;
  if (editId) {
    openProjectModal(projectsCache.find(p => p.id === parseInt(editId)));
    return;
  }
  const resolveId = e.target.closest("[data-issue-resolve]")?.dataset.issueResolve;
  if (resolveId) {
    await api(`/business-issues/${resolveId}/resolve`, { method: "POST" });
    loadProjectsTab();
  }
});

function openProjectModal(project) {
  document.getElementById("project-modal-title").textContent = project ? "Projekt bearbeiten" : "Neues Projekt";
  document.getElementById("project-id").value = project ? project.id : "";
  document.getElementById("project-name").value = project ? project.name : "";
  document.getElementById("project-description").value = project?.description || "";
  document.getElementById("project-interval").value = project?.check_interval_days || "";
  document.getElementById("project-account").value = project?.account_id || "";
  document.getElementById("project-archive").classList.toggle("hidden", !project);
  document.getElementById("project-modal").classList.remove("hidden");
}
document.getElementById("project-new-btn").addEventListener("click", () => openProjectModal(null));
document.getElementById("project-modal-close").addEventListener("click", () => {
  document.getElementById("project-modal").classList.add("hidden");
});
document.getElementById("project-issue-modal-close").addEventListener("click", () => {
  document.getElementById("project-issue-modal").classList.add("hidden");
});

document.getElementById("project-form").addEventListener("submit", async e => {
  e.preventDefault();
  const id = document.getElementById("project-id").value;
  const payload = {
    name: document.getElementById("project-name").value,
    description: document.getElementById("project-description").value || null,
    check_interval_days: document.getElementById("project-interval").value
      ? parseInt(document.getElementById("project-interval").value) : null,
    account_id: document.getElementById("project-account").value
      ? parseInt(document.getElementById("project-account").value) : null,
  };
  if (id) {
    await api(`/business-projects/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
  } else {
    await api("/business-projects", { method: "POST", body: JSON.stringify(payload) });
  }
  document.getElementById("project-modal").classList.add("hidden");
  loadProjectsTab();
});

document.getElementById("project-archive").addEventListener("click", async () => {
  const id = document.getElementById("project-id").value;
  if (!id || !confirm("Projekt archivieren? Offene Punkte bleiben erhalten, das Projekt verschwindet aber aus der Liste.")) return;
  await api(`/business-projects/${id}`, { method: "PATCH", body: JSON.stringify({ active: false }) });
  document.getElementById("project-modal").classList.add("hidden");
  loadProjectsTab();
});

document.getElementById("project-issue-form").addEventListener("submit", async e => {
  e.preventDefault();
  const payload = {
    project_id: parseInt(document.getElementById("project-issue-project-id").value),
    title: document.getElementById("project-issue-title").value,
    notes: document.getElementById("project-issue-notes").value || null,
  };
  await api("/business-issues", { method: "POST", body: JSON.stringify(payload) });
  document.getElementById("project-issue-modal").classList.add("hidden");
  loadProjectsTab();
});

async function refreshProjectsBadge() {
  try {
    const issues = await api("/business-issues");
    const badge = document.getElementById("projects-nav-badge");
    badge.textContent = issues.length;
    badge.classList.toggle("hidden", !issues.length);
  } catch (e) {
    // Beim App-Start unkritisch
  }
}

// ================= LEBEN (persönliche Lebensbereiche) =================
let lifeAreasCache = [];

async function loadLifeTab() {
  const [areas, checkins] = await Promise.all([
    api("/life-areas"),
    api("/life-checkins"),
  ]);
  lifeAreasCache = areas;
  const checkinsByArea = new Map();
  checkins.forEach(c => {
    if (!checkinsByArea.has(c.area_id)) checkinsByArea.set(c.area_id, []);
    checkinsByArea.get(c.area_id).push(c);
  });

  const list = document.getElementById("life-areas-list");
  if (!areas.length) {
    list.innerHTML = `<div class="empty-state"><span class="empty-icon">${svgIcon("target")}</span><span>Noch keine Lebensbereiche angelegt. Leg oben rechts einen an.</span></div>`;
  } else {
    list.innerHTML = "";
    areas.forEach(a => list.appendChild(renderLifeAreaCard(a, (checkinsByArea.get(a.id) || []).slice(0, 5))));
  }

  loadContacts();
  loadMediaItems();
  loadHealthMetrics();
}

// ---------- Kontakte (People/CRM-Light) ----------
async function loadContacts() {
  const contacts = await api("/contacts");
  const tbody = document.getElementById("contacts-list");
  if (!contacts.length) {
    tbody.innerHTML = emptyRow(4, "user", "Noch keine Kontakte.");
    return;
  }
  tbody.innerHTML = contacts.map(c => `
    <tr>
      <td>${esc(c.name)}</td>
      <td>${esc(c.notes || "–")}</td>
      <td>${c.last_interaction_at ? fmtDate(c.last_interaction_at) : "–"}</td>
      <td>
        <button type="button" class="link-btn" data-contact-touch="${c.id}">Jetzt kontaktiert</button>
        <button type="button" class="link-btn" data-contact-delete="${c.id}">Löschen</button>
      </td>
    </tr>`).join("");
}

document.getElementById("contact-form").addEventListener("submit", async e => {
  e.preventDefault();
  const name = document.getElementById("contact-name").value.trim();
  if (!name) return;
  await api("/contacts", {
    method: "POST",
    body: JSON.stringify({ name, notes: document.getElementById("contact-notes").value.trim() || null }),
  });
  document.getElementById("contact-form").reset();
  loadContacts();
});

document.getElementById("contacts-list").addEventListener("click", async e => {
  const touchId = e.target.closest("[data-contact-touch]")?.dataset.contactTouch;
  if (touchId) {
    await api(`/contacts/${touchId}/touch`, { method: "POST" });
    loadContacts();
    return;
  }
  const delId = e.target.closest("[data-contact-delete]")?.dataset.contactDelete;
  if (delId) {
    await api(`/contacts/${delId}`, { method: "DELETE" });
    loadContacts();
  }
});

// ---------- Leseliste / Medien-Tracking ----------
let mediaCache = [];
let mediaFilter = "alle";
const MEDIA_STATUS_LABELS = { offen: "Offen", "läuft": "Läuft", fertig: "Fertig", abgebrochen: "Abgebrochen" };

async function loadMediaItems() {
  mediaCache = await api("/media");
  renderMediaList();
}

function renderMediaList() {
  const tbody = document.getElementById("media-list");
  const items = mediaFilter === "alle" ? mediaCache : mediaCache.filter(m => m.status === mediaFilter);
  if (!items.length) {
    tbody.innerHTML = emptyRow(4, "file-text", "Nichts in der Leseliste.");
    return;
  }
  tbody.innerHTML = items.map(m => `
    <tr>
      <td>${m.url ? `<a href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.title)}</a>` : esc(m.title)}</td>
      <td>${esc(m.media_type)}</td>
      <td>
        <select data-media-status="${m.id}">
          ${Object.entries(MEDIA_STATUS_LABELS).map(([v, l]) => `<option value="${v}" ${v === m.status ? "selected" : ""}>${l}</option>`).join("")}
        </select>
      </td>
      <td><button type="button" class="link-btn" data-media-delete="${m.id}">Löschen</button></td>
    </tr>`).join("");
}

document.querySelectorAll("#media-filter-tabs .range-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#media-filter-tabs .range-tab").forEach(b => b.classList.toggle("active", b === btn));
    mediaFilter = btn.dataset.mediaFilter;
    renderMediaList();
  });
});

document.getElementById("media-form").addEventListener("submit", async e => {
  e.preventDefault();
  const title = document.getElementById("media-title").value.trim();
  if (!title) return;
  await api("/media", {
    method: "POST",
    body: JSON.stringify({
      title,
      media_type: document.getElementById("media-type").value.trim() || "Buch",
      url: document.getElementById("media-url").value.trim() || null,
    }),
  });
  document.getElementById("media-form").reset();
  document.getElementById("media-type").value = "Buch";
  loadMediaItems();
});

document.getElementById("media-list").addEventListener("change", async e => {
  const id = e.target.closest("[data-media-status]")?.dataset.mediaStatus;
  if (id) await api(`/media/${id}`, { method: "PATCH", body: JSON.stringify({ status: e.target.value }) });
});

document.getElementById("media-list").addEventListener("click", async e => {
  const delId = e.target.closest("[data-media-delete]")?.dataset.mediaDelete;
  if (delId) {
    await api(`/media/${delId}`, { method: "DELETE" });
    loadMediaItems();
  }
});

// ---------- Gesundheits-Grunddaten ----------
let healthChart = null;

async function loadHealthMetrics() {
  const type = document.getElementById("health-metric-type").value;
  const points = await api(`/health-metrics?metric_type=${type}&days=90`);
  const ctx = document.getElementById("chart-health");
  const label = type === "gewicht" ? "Gewicht (kg)" : "Schlaf (Std.)";
  const data = {
    labels: points.map(p => fmtDate(p.date)),
    datasets: [{
      label, data: points.map(p => p.value),
      borderColor: cssVar("--accent"), backgroundColor: "transparent", tension: 0.25, pointRadius: 2,
    }],
  };
  if (healthChart) { healthChart.destroy(); healthChart = null; }
  if (!points.length) return;
  healthChart = new Chart(ctx, {
    type: "line", data,
    options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: false } } },
  });
}

document.getElementById("health-metric-type").addEventListener("change", loadHealthMetrics);

document.getElementById("health-form").addEventListener("submit", async e => {
  e.preventDefault();
  const dateVal = document.getElementById("health-date").value;
  const value = parseFloat(document.getElementById("health-value").value);
  if (!dateVal || isNaN(value)) return;
  await api("/health-metrics", {
    method: "POST",
    body: JSON.stringify({ metric_type: document.getElementById("health-metric-type").value, date: dateVal, value }),
  });
  document.getElementById("health-form").reset();
  loadHealthMetrics();
});

function lifeAreaIsOverdue(a) {
  if (!a.check_interval_days) return false;
  // Fallback auf created_at spiegelt main._scheduled_life_check_reminder.
  const reference = new Date(a.last_checked_at || a.created_at);
  const days = (Date.now() - reference.getTime()) / (1000 * 60 * 60 * 24);
  return days >= a.check_interval_days;
}

function renderLifeAreaHeatmap(a) {
  const days = a.checkin_days_30 || [];
  const daySet = new Set(days);
  const cells = [];
  for (let i = 29; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    const iso = d.toISOString().slice(0, 10);
    cells.push(`<span class="life-heatmap-day${daySet.has(iso) ? " filled" : ""}" title="${iso}"></span>`);
  }
  return `<div class="life-heatmap">${cells.join("")}</div>`;
}

const WEEKDAY_LABELS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

function renderLifeAreaWeekGrid(a) {
  if (!a.target_days_per_week) return "";
  const weekDays = a.week_days || [];
  const done = weekDays.filter(Boolean).length;
  const met = done >= a.target_days_per_week;
  const cells = WEEKDAY_LABELS.map((label, i) => `
    <div class="life-week-cell${weekDays[i] ? " filled" : ""}">
      <span class="life-week-daylabel">${label}</span>
      <span class="life-week-check">${weekDays[i] ? "✓" : ""}</span>
    </div>
  `).join("");
  return `
    <div class="life-week-grid-wrap">
      <p class="page-sub life-week-count${met ? " met" : ""}">${done}/${a.target_days_per_week}x diese Woche${met ? " ✓" : ""}</p>
      <div class="life-week-grid">${cells}</div>
    </div>
  `;
}

function renderLifeAreaCard(a, recentCheckins) {
  const card = document.createElement("div");
  card.className = "goal-card";
  const overdue = lifeAreaIsOverdue(a);
  const lastChecked = a.last_checked_at
    ? new Date(a.last_checked_at).toLocaleDateString("de-DE")
    : "noch kein Check-in";
  const progress = a.progress_percent != null ? a.progress_percent : null;
  const streak = a.streak_days || 0;
  card.innerHTML = `
    <div class="goal-card-head">
      <h4>${esc(a.name)}</h4>
      ${a.target_date ? `<span class="goal-chip">bis ${fmtDate(a.target_date)}</span>` : ""}
    </div>
    ${a.description ? `<p class="goal-desc">${esc(a.description)}</p>` : ""}
    ${progress != null ? `
      <div class="budget-track"><div class="goal-fill${progress >= 100 ? " done" : ""}" style="width:${Math.min(progress, 100)}%"></div></div>
      <p class="goal-values">${progress}%</p>
    ` : ""}
    <p class="goal-meta ${overdue ? "goal-error" : ""}">
      ${overdue ? "⚠️ " : ""}Letzter Check-in: ${lastChecked}${a.check_interval_days ? ` · Intervall ${a.check_interval_days} Tage` : ""}
    </p>
    <div class="life-streak${streak > 0 ? " active" : ""}">${streak > 0 ? `🔥 ${streak} Tag${streak === 1 ? "" : "e"} Streak` : "Noch keine Streak"}</div>
    ${renderLifeAreaWeekGrid(a)}
    ${renderLifeAreaHeatmap(a)}
    <div class="todo-row-list">
      ${recentCheckins.map(c => `
        <div class="todo-row">
          <span class="todo-title">${esc(c.note)}</span>
          <span class="page-sub">${new Date(c.created_at).toLocaleDateString("de-DE")}</span>
        </div>
      `).join("")}
    </div>
    <div class="filter-row" style="margin-top:4px">
      ${checkedInToday(a)
        ? `<span class="btn-ghost btn-sm" style="cursor:default;opacity:0.7">✓ Heute erledigt</span>`
        : `<button type="button" class="btn-primary btn-sm" data-life-tick="${a.id}">✓ Heute</button>`}
      <button type="button" class="btn-ghost btn-sm" data-life-checkin="${a.id}">+ Check-in mit Notiz</button>
      <button type="button" class="link-btn" data-life-edit="${a.id}">Bearbeiten</button>
      <button type="button" class="link-btn" data-notes-entity="life_area" data-notes-id="${a.id}" data-notes-label="${esc(a.name)}">📝 Notizen</button>
    </div>
  `;
  return card;
}

// Für den Ein-Klick-Häkchen-Button: heute schon abgehakt, wenn ein Streak-Tag
// den heutigen ISO-Tag enthält - dieselbe Datenquelle wie die Heatmap, kein
// zusätzlicher Serverstatus nötig.
function checkedInToday(a) {
  const today = new Date().toISOString().slice(0, 10);
  return (a.checkin_days_30 || []).includes(today);
}

document.getElementById("life-areas-list").addEventListener("click", async e => {
  const tickId = e.target.closest("[data-life-tick]")?.dataset.lifeTick;
  if (tickId) {
    await api("/life-checkins", { method: "POST", body: JSON.stringify({ area_id: parseInt(tickId), note: "Erledigt" }) });
    toast("Häkchen gesetzt.");
    loadLifeTab();
    return;
  }
  const checkinId = e.target.closest("[data-life-checkin]")?.dataset.lifeCheckin;
  if (checkinId) {
    document.getElementById("life-checkin-area-id").value = checkinId;
    document.getElementById("life-checkin-form").reset();
    document.getElementById("life-checkin-modal").classList.remove("hidden");
    return;
  }
  const editId = e.target.closest("[data-life-edit]")?.dataset.lifeEdit;
  if (editId) {
    openLifeAreaModal(lifeAreasCache.find(a => a.id === parseInt(editId)));
  }
});

function openLifeAreaModal(area) {
  document.getElementById("life-area-modal-title").textContent = area ? "Lebensbereich bearbeiten" : "Neuer Lebensbereich";
  document.getElementById("life-area-id").value = area ? area.id : "";
  document.getElementById("life-area-name").value = area ? area.name : "";
  document.getElementById("life-area-description").value = area?.description || "";
  document.getElementById("life-area-target-date").value = area?.target_date || "";
  document.getElementById("life-area-progress").value = area?.progress_percent ?? "";
  document.getElementById("life-area-interval").value = area?.check_interval_days || "";
  document.getElementById("life-area-week-target").value = area?.target_days_per_week || "";
  document.getElementById("life-area-archive").classList.toggle("hidden", !area);
  document.getElementById("life-area-modal").classList.remove("hidden");
}
document.getElementById("life-area-new-btn").addEventListener("click", () => openLifeAreaModal(null));
document.getElementById("life-area-modal-close").addEventListener("click", () => {
  document.getElementById("life-area-modal").classList.add("hidden");
});
document.getElementById("life-checkin-modal-close").addEventListener("click", () => {
  document.getElementById("life-checkin-modal").classList.add("hidden");
});

document.getElementById("life-area-form").addEventListener("submit", async e => {
  e.preventDefault();
  const id = document.getElementById("life-area-id").value;
  const progressVal = document.getElementById("life-area-progress").value;
  const payload = {
    name: document.getElementById("life-area-name").value,
    description: document.getElementById("life-area-description").value || null,
    target_date: document.getElementById("life-area-target-date").value || null,
    progress_percent: progressVal !== "" ? parseInt(progressVal) : null,
    check_interval_days: document.getElementById("life-area-interval").value
      ? parseInt(document.getElementById("life-area-interval").value) : null,
    target_days_per_week: document.getElementById("life-area-week-target").value
      ? parseInt(document.getElementById("life-area-week-target").value) : null,
  };
  if (id) {
    await api(`/life-areas/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
  } else {
    await api("/life-areas", { method: "POST", body: JSON.stringify(payload) });
  }
  document.getElementById("life-area-modal").classList.add("hidden");
  loadLifeTab();
});

document.getElementById("life-area-archive").addEventListener("click", async () => {
  const id = document.getElementById("life-area-id").value;
  if (!id || !confirm("Lebensbereich archivieren? Der Verlauf bleibt erhalten, der Bereich verschwindet aber aus der Liste.")) return;
  await api(`/life-areas/${id}`, { method: "PATCH", body: JSON.stringify({ active: false }) });
  document.getElementById("life-area-modal").classList.add("hidden");
  loadLifeTab();
});

document.getElementById("life-checkin-form").addEventListener("submit", async e => {
  e.preventDefault();
  const progressVal = document.getElementById("life-checkin-progress").value;
  const payload = {
    area_id: parseInt(document.getElementById("life-checkin-area-id").value),
    note: document.getElementById("life-checkin-note").value,
    progress_percent: progressVal !== "" ? parseInt(progressVal) : null,
  };
  await api("/life-checkins", { method: "POST", body: JSON.stringify(payload) });
  document.getElementById("life-checkin-modal").classList.add("hidden");
  loadLifeTab();
});

// ================= WUNSCHLISTE (Deal-Wecker) =================
let wishlistCache = [];

function wishlistItemIsOverdue(w) {
  if (!w.check_interval_days) return false;
  // Fallback auf created_at spiegelt main._scheduled_wishlist_reminder.
  const reference = new Date(w.last_checked_at || w.created_at);
  const days = (Date.now() - reference.getTime()) / (1000 * 60 * 60 * 24);
  return days >= w.check_interval_days;
}

async function loadWishlistTab() {
  wishlistCache = await api("/wishlist");
  const tbody = document.getElementById("wishlist-list");
  if (!wishlistCache.length) {
    tbody.innerHTML = emptyRow(6, "shopping-cart", "Noch nichts auf der Wunschliste – oben rechts einen Wunsch anlegen.");
    return;
  }
  tbody.innerHTML = wishlistCache.map(w => {
    const overdue = wishlistItemIsOverdue(w);
    const lastChecked = w.last_checked_at ? new Date(w.last_checked_at).toLocaleDateString("de-DE") : "noch nie";
    return `
      <tr>
        <td>${w.url ? `<a href="${esc(w.url)}" target="_blank" rel="noopener">${esc(w.name)}</a>` : esc(w.name)}</td>
        <td>${w.category ? esc(w.category) : "–"}</td>
        <td>${w.target_price != null ? eur(w.target_price) : "–"}</td>
        <td class="${overdue ? "row-amount-neg" : ""}">${overdue ? "⚠️ " : ""}${lastChecked}</td>
        <td>${w.auto_check_enabled ? "🤖 an" : "aus"}</td>
        <td>
          <button type="button" class="btn-ghost btn-sm" data-wishlist-checked="${w.id}">✓ Geprüft</button>
          <button type="button" class="link-btn" data-wishlist-edit="${w.id}">Bearbeiten</button>
        </td>
      </tr>`;
  }).join("");
}

document.getElementById("wishlist-list").addEventListener("click", async e => {
  const checkedId = e.target.closest("[data-wishlist-checked]")?.dataset.wishlistChecked;
  if (checkedId) {
    await api(`/wishlist/${checkedId}/checked`, { method: "POST" });
    toast("Als geprüft bestätigt.");
    loadWishlistTab();
    return;
  }
  const editId = e.target.closest("[data-wishlist-edit]")?.dataset.wishlistEdit;
  if (editId) {
    openWishlistModal(wishlistCache.find(w => w.id === parseInt(editId)));
  }
});

function openWishlistModal(item) {
  document.getElementById("wishlist-modal-title").textContent = item ? "Wunsch bearbeiten" : "Neuer Wunsch";
  document.getElementById("wishlist-id").value = item ? item.id : "";
  document.getElementById("wishlist-name").value = item ? item.name : "";
  document.getElementById("wishlist-category").value = item?.category || "";
  document.getElementById("wishlist-target-price").value = item?.target_price ?? "";
  document.getElementById("wishlist-url").value = item?.url || "";
  document.getElementById("wishlist-notes").value = item?.notes || "";
  document.getElementById("wishlist-interval").value = item?.check_interval_days || "";
  document.getElementById("wishlist-auto-check").checked = item?.auto_check_enabled || false;
  document.getElementById("wishlist-purchased").classList.toggle("hidden", !item);
  document.getElementById("wishlist-archive").classList.toggle("hidden", !item);
  document.getElementById("wishlist-modal").classList.remove("hidden");
}
document.getElementById("wishlist-new-btn").addEventListener("click", () => openWishlistModal(null));
document.getElementById("wishlist-modal-close").addEventListener("click", () => {
  document.getElementById("wishlist-modal").classList.add("hidden");
});

document.getElementById("wishlist-form").addEventListener("submit", async e => {
  e.preventDefault();
  const id = document.getElementById("wishlist-id").value;
  const priceVal = document.getElementById("wishlist-target-price").value;
  const payload = {
    name: document.getElementById("wishlist-name").value,
    category: document.getElementById("wishlist-category").value || null,
    target_price: priceVal !== "" ? parseFloat(priceVal) : null,
    url: document.getElementById("wishlist-url").value || null,
    notes: document.getElementById("wishlist-notes").value || null,
    check_interval_days: document.getElementById("wishlist-interval").value
      ? parseInt(document.getElementById("wishlist-interval").value) : null,
    auto_check_enabled: document.getElementById("wishlist-auto-check").checked,
  };
  if (id) {
    await api(`/wishlist/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
  } else {
    await api("/wishlist", { method: "POST", body: JSON.stringify(payload) });
  }
  document.getElementById("wishlist-modal").classList.add("hidden");
  loadWishlistTab();
});

document.getElementById("wishlist-purchased").addEventListener("click", async () => {
  const id = document.getElementById("wishlist-id").value;
  if (!id) return;
  await api(`/wishlist/${id}`, { method: "PATCH", body: JSON.stringify({ purchased: true, active: false }) });
  document.getElementById("wishlist-modal").classList.add("hidden");
  toast("Als gekauft markiert.");
  loadWishlistTab();
});

document.getElementById("wishlist-archive").addEventListener("click", async () => {
  const id = document.getElementById("wishlist-id").value;
  if (!id || !confirm("Wunsch entfernen?")) return;
  await api(`/wishlist/${id}`, { method: "PATCH", body: JSON.stringify({ active: false }) });
  document.getElementById("wishlist-modal").classList.add("hidden");
  loadWishlistTab();
});

// ================= TRANSACTIONS =================
let returnDeadlinesCache = [];

async function runReceiptSearch() {
  const q = document.getElementById("receipt-search-input").value.trim();
  const results = document.getElementById("receipt-search-results");
  if (q.length < 2) {
    results.innerHTML = `<p class="page-sub">Mindestens 2 Zeichen eingeben.</p>`;
    return;
  }
  if (!accountsCache.length) await loadAccounts();
  if (!categoriesCache.length) await loadCategories();
  results.innerHTML = `<p class="page-sub">Suche …</p>`;
  const hits = await api(`/receipts/search/query?q=${encodeURIComponent(q)}`);
  if (!hits.length) {
    results.innerHTML = `<div class="empty-state"><span class="empty-icon">${svgIcon("receipt")}</span><span>Keine Belege gefunden.</span></div>`;
    return;
  }
  results.innerHTML = hits.map(t => {
    const acc = accountsCache.find(a => a.id === t.account_id);
    const cat = categoriesCache.find(c => c.id === t.category_id);
    return `
      <div class="todo-row">
        <span class="todo-title">
          ${esc(t.description || "Ohne Beschreibung")}
          <span class="page-sub" style="display:inline">– ${fmtDate(t.date)} · ${acc ? esc(acc.name) : "?"}${cat ? " · " + esc(cat.name) : ""}</span>
        </span>
        <span class="${t.amount >= 0 ? "row-amount-pos" : "row-amount-neg"}">${eur(t.amount)}</span>
        <a href="/api/receipts/${esc(t.receipt_filename)}" target="_blank" rel="noopener" class="link-btn">Beleg öffnen</a>
      </div>`;
  }).join("");
}
document.getElementById("receipt-search-btn").addEventListener("click", runReceiptSearch);
document.getElementById("receipt-search-input").addEventListener("keydown", e => {
  if (e.key === "Enter") { e.preventDefault(); runReceiptSearch(); }
});

async function loadTransactions() {
  loadGlobalTopbar();
  document.getElementById("tx-list").innerHTML = skelTableRows(7, 8);
  if (!accountsCache.length) await loadAccounts();
  if (!categoriesCache.length) await loadCategories();
  if (!tripsCache.length) await loadTrips();

  const params = new URLSearchParams();
  const search = document.getElementById("tx-search").value;
  const accId = document.getElementById("tx-filter-account").value;
  const catId = document.getElementById("tx-filter-category").value;
  const tripId = document.getElementById("tx-filter-trip").value;
  const hideTransfers = document.getElementById("tx-hide-transfers").checked;
  if (search) params.set("search", search);
  if (accId) params.set("account_id", accId);
  if (catId) params.set("category_id", catId);
  if (tripId) params.set("trip_id", tripId);
  if (hideTransfers) params.set("hide_transfers", "true");
  localStorage.setItem("txHideTransfers", hideTransfers ? "1" : "0");

  const [txs] = await Promise.all([
    api("/transactions?" + params.toString()),
    api("/return-deadlines").then(d => { returnDeadlinesCache = d; }),
  ]);
  txs.forEach(t => {
    const acc = accountsCache.find(a => a.id === t.account_id);
    const cat = categoriesCache.find(c => c.id === t.category_id);
    t._account_name = acc ? acc.name : "";
    t._category_name = t.is_transfer ? "Umbuchung" : (cat ? cat.name : "");
    t._has_receipt = t.receipt_filename ? 1 : 0;
  });
  txListCache = txs;
  renderTransactionsTable();
}

let txSortKey = "date";
let txSortDir = -1;
let txSelection = new Set();

function updateTxBulkBar() {
  const bar = document.getElementById("tx-bulk-bar");
  bar.classList.toggle("hidden", txSelection.size === 0);
  document.getElementById("tx-bulk-count").textContent = txSelection.size;
  document.getElementById("tx-select-all").checked =
    txListCache.length > 0 && txListCache.every(t => txSelection.has(t.id));
}

function renderTransactionsTable() {
  const tbody = document.getElementById("tx-list");
  tbody.innerHTML = "";
  // Aus der Auswahl entfernen, was durch einen neuen Filter/Reload nicht mehr
  // in der Liste steckt - sonst bliebe der Zähler auf unsichtbaren Buchungen sitzen.
  const visibleIds = new Set(txListCache.map(t => t.id));
  txSelection.forEach(id => { if (!visibleIds.has(id)) txSelection.delete(id); });
  if (txListCache.length === 0) {
    tbody.innerHTML = emptyRow(8, "receipt", "Keine Buchungen gefunden.");
    updateTxBulkBar();
    return;
  }
  const rows = [...txListCache];
  if (txSortKey) {
    rows.sort((a, b) => {
      let va = a[txSortKey];
      let vb = b[txSortKey];
      if (typeof va === "string" || typeof vb === "string") {
        va = (va ?? "").toString().toLowerCase();
        vb = (vb ?? "").toString().toLowerCase();
        return va < vb ? -txSortDir : va > vb ? txSortDir : 0;
      }
      va = va ?? -Infinity;
      vb = vb ?? -Infinity;
      return (va - vb) * txSortDir;
    });
  }
  rows.forEach(t => {
    const rd = returnDeadlinesCache.find(r => r.transaction_id === t.id && !r.returned);
    const rdBadge = rd
      ? ` <span class="goal-chip ${rd.due ? "is-warn" : ""}" title="Rückgabefrist ${fmtDate(rd.deadline_date)}">🔄 ${rd.days_left >= 0 ? `noch ${rd.days_left} Tag(e)` : "abgelaufen"}</span>`
      : "";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="checkbox" class="tx-row-select" data-tx-select="${t.id}" ${txSelection.has(t.id) ? "checked" : ""}></td>
      <td>${t.date}</td>
      <td>${t.description || ""}${rdBadge}</td>
      <td>${t._account_name}</td>
      <td>${t.is_transfer ? '<span class="goal-chip">🔁 Umbuchung</span>' : (t._category_name || "–")}</td>
      <td class="${t.is_transfer ? "" : (t.amount >= 0 ? "row-amount-pos" : "row-amount-neg")}">${eur(t.amount)}</td>
      <td>${t.receipt_filename ? `<a href="/api/receipts/${t.receipt_filename}" target="_blank">Beleg</a>` : "–"}</td>
      <td>
        <button class="link-btn" onclick="editTransaction(${t.id})">Bearbeiten</button>
        <button class="link-btn" onclick="deleteTransaction(${t.id})">Löschen</button>
        <button class="link-btn" onclick="openReturnDeadlineModal(${t.id})">${rd ? "Rückgabe" : "🔄 Rückgabe"}</button>
        ${!t.is_transfer && t.amount < 0 ? `<button class="link-btn" data-cr-account="${t.account_id}" data-cr-desc="${esc(t.description || "")}">📄 Frist</button>` : ""}
      </td>`;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll("[data-cr-account]").forEach(btn => {
    btn.addEventListener("click", () => {
      const desc = btn.dataset.crDesc;
      openContractReminderModal(parseInt(btn.dataset.crAccount), normalizeDescriptionKey(desc), desc, null);
    });
  });
  tbody.querySelectorAll("[data-tx-select]").forEach(cb => {
    cb.addEventListener("change", () => {
      const id = parseInt(cb.dataset.txSelect, 10);
      cb.checked ? txSelection.add(id) : txSelection.delete(id);
      updateTxBulkBar();
    });
  });
  updateTxBulkBar();
}

document.getElementById("tx-select-all").addEventListener("change", e => {
  if (e.target.checked) txListCache.forEach(t => txSelection.add(t.id));
  else txListCache.forEach(t => txSelection.delete(t.id));
  renderTransactionsTable();
});

document.getElementById("tx-bulk-clear").addEventListener("click", () => {
  txSelection.clear();
  renderTransactionsTable();
});

document.getElementById("tx-bulk-apply").addEventListener("click", async () => {
  const catId = document.getElementById("tx-bulk-category").value;
  if (!catId) { toast("Bitte zuerst eine Kategorie auswählen."); return; }
  const ids = [...txSelection];
  await api("/transactions/bulk-categorize", {
    method: "POST",
    body: JSON.stringify({ transaction_ids: ids, category_id: parseInt(catId, 10) }),
  });
  toast(`${ids.length} Buchung(en) kategorisiert.`);
  txSelection.clear();
  await loadTransactions();
});

document.querySelectorAll("#tx-list-head [data-sort-key]").forEach(th => {
  th.addEventListener("click", () => {
    const key = th.dataset.sortKey;
    if (txSortKey === key) {
      txSortDir *= -1;
    } else {
      txSortKey = key;
      txSortDir = 1;
    }
    document.querySelectorAll("#tx-list-head [data-sort-key]").forEach(el => el.classList.remove("sort-asc", "sort-desc"));
    th.classList.add(txSortDir === 1 ? "sort-asc" : "sort-desc");
    renderTransactionsTable();
  });
});

function normalizeDescriptionKey(desc) {
  // Muss exakt zu crud._normalize_description() im Backend passen, da
  // ContractReminder ueber (account_id, description_key) eindeutig ist -
  // sonst wuerde aus dieser Buchungsliste heraus eine zweite, nicht
  // zusammengehoerende Erinnerung fuer dieselbe Zahlung entstehen.
  if (!desc) return "";
  let text = desc.trim().toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
  text = text.replace(/[.,()/-]/g, " ");
  text = text.replace(/\s+/g, " ");
  text = text.replace(/\b\d{6,}\b/g, "");
  return text.trim();
}

function openReturnDeadlineModal(transactionId) {
  const existing = returnDeadlinesCache.find(r => r.transaction_id === transactionId);
  document.getElementById("return-deadline-modal-title").textContent = existing ? "Rückgabefrist bearbeiten" : "Rückgabefrist anlegen";
  document.getElementById("return-deadline-modal-sub").textContent = existing?.returned
    ? "Bereits als zurückgeschickt markiert." : "";
  document.getElementById("rd-id").value = existing ? existing.id : "";
  document.getElementById("rd-transaction-id").value = transactionId;
  document.getElementById("rd-start").value = existing ? existing.start_date : new Date().toISOString().slice(0, 10);
  document.getElementById("rd-days").value = existing ? existing.deadline_days : 14;
  document.getElementById("rd-remind").value = existing ? existing.remind_days_before : 3;
  document.getElementById("rd-delete").classList.toggle("hidden", !existing);
  document.getElementById("rd-mark-returned").classList.toggle("hidden", !existing || existing.returned);
  document.getElementById("return-deadline-modal").classList.remove("hidden");
}
window.openReturnDeadlineModal = openReturnDeadlineModal;

function closeReturnDeadlineModal() {
  document.getElementById("return-deadline-modal").classList.add("hidden");
}
document.getElementById("return-deadline-modal-close").addEventListener("click", closeReturnDeadlineModal);

document.getElementById("return-deadline-form").addEventListener("submit", async e => {
  e.preventDefault();
  const id = document.getElementById("rd-id").value;
  const payload = {
    transaction_id: parseInt(document.getElementById("rd-transaction-id").value),
    start_date: document.getElementById("rd-start").value,
    deadline_days: parseInt(document.getElementById("rd-days").value),
    remind_days_before: parseInt(document.getElementById("rd-remind").value),
  };
  await api(id ? `/return-deadlines/${id}` : "/return-deadlines", {
    method: id ? "PUT" : "POST", body: JSON.stringify(payload),
  });
  closeReturnDeadlineModal();
  loadTransactions();
});

document.getElementById("rd-mark-returned").addEventListener("click", async () => {
  const id = document.getElementById("rd-id").value;
  if (!id) return;
  await api(`/return-deadlines/${id}`, { method: "PUT", body: JSON.stringify({ returned: true }) });
  closeReturnDeadlineModal();
  loadTransactions();
});

document.getElementById("rd-delete").addEventListener("click", async () => {
  const id = document.getElementById("rd-id").value;
  if (!id || !confirm("Rückgabefrist wirklich löschen?")) return;
  await api(`/return-deadlines/${id}`, { method: "DELETE" });
  closeReturnDeadlineModal();
  loadTransactions();
});

// ================= ABOS / WIEDERKEHRENDE ZAHLUNGEN =================
const RECURRING_FREQ_LABELS = {
  woechentlich: "Wöchentlich", zweiwoechentlich: "Alle 2 Wochen", monatlich: "Monatlich",
  quartalsweise: "Vierteljährlich", jaehrlich: "Jährlich",
};
const RECURRING_MONTHLY_FACTOR = {
  woechentlich: 4.33, zweiwoechentlich: 2.17, monatlich: 1, quartalsweise: 1 / 3, jaehrlich: 1 / 12,
};

let cashflowChart = null;
let cashflowDays = 90;

async function loadCashflowForecast() {
  const data = await api(`/forecast/cashflow?days=${cashflowDays}`);

  const warnEl = document.getElementById("cashflow-warning");
  if (data.goes_negative) {
    warnEl.textContent = `⚠️ Prognose: Kontostand könnte am ${fmtDate(data.first_negative_date)} ins Minus rutschen (Tiefstand ${eur(data.lowest_balance)} am ${fmtDate(data.lowest_date)}).`;
    warnEl.classList.remove("hidden");
  } else {
    warnEl.classList.add("hidden");
  }

  const labels = data.points.map(p => p.date);
  const values = data.points.map(p => p.balance);
  const ctx = document.getElementById("chart-cashflow");
  if (cashflowChart) cashflowChart.destroy();
  cashflowChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        data: values,
        borderColor: data.goes_negative ? cssVar("--neg") : cssVar("--accent-strong"),
        backgroundColor: data.goes_negative ? "transparent" : cssVar("--accent-wash"),
        fill: !data.goes_negative,
        tension: 0.25,
        pointRadius: 0,
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: cssVar("--surface-2"), borderColor: cssVar("--border-strong"), borderWidth: 1,
          titleColor: cssVar("--text"), bodyColor: cssVar("--text-secondary"), padding: 10, cornerRadius: 8,
          callbacks: { title: items => fmtDate(items[0].label), label: c => eur(c.parsed.y) },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          border: { display: false },
          ticks: { color: cssVar("--muted"), font: { size: 11 }, maxTicksLimit: 8 },
        },
        y: {
          grid: { color: cssVar("--border"), drawTicks: false },
          border: { display: false },
          ticks: { color: cssVar("--muted"), font: { size: 11 }, callback: v => eur(v) },
        },
      },
    },
  });
}

document.querySelectorAll("#cashflow-range-tabs .range-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#cashflow-range-tabs .range-tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    cashflowDays = parseInt(btn.dataset.days);
    loadCashflowForecast();
  });
});

document.getElementById("cashflow-scenario-form").addEventListener("submit", async e => {
  e.preventDefault();
  const payload = {
    horizon_days: cashflowDays,
    cancel_description_key: document.getElementById("scenario-cancel").value || null,
    extra_monthly_saving: parseFloat(document.getElementById("scenario-saving").value) || 0,
    extra_monthly_expense: parseFloat(document.getElementById("scenario-expense").value) || 0,
  };
  const result = document.getElementById("scenario-result");
  result.textContent = "Berechne …";
  const data = await api("/forecast/cashflow/scenario", { method: "POST", body: JSON.stringify(payload) });

  if (cashflowChart) {
    cashflowChart.data.datasets = cashflowChart.data.datasets.slice(0, 1);
    cashflowChart.data.datasets.push({
      data: data.scenario.points.map(p => p.balance),
      borderColor: cssVar("--pos"),
      backgroundColor: "transparent",
      borderDash: [6, 4],
      fill: false,
      tension: 0.25,
      pointRadius: 0,
      borderWidth: 2,
    });
    cashflowChart.update();
  }

  const delta = data.scenario.points.at(-1).balance - data.baseline.points.at(-1).balance;
  const sign = delta >= 0 ? "+" : "";
  // Bei einer Kündigung zusätzlich die Jahresersparnis nennen: der Endstand
  // über den Prognose-Horizont (Standard 90 Tage) beantwortet "was spare ich?"
  // nur für diesen Ausschnitt - die Frage meint aber fast immer aufs Jahr.
  let cancelNote = "";
  if (payload.cancel_description_key) {
    const item = recurringItemsCache.find(it => it.description_key === payload.cancel_description_key);
    if (item) {
      const yearly = Math.abs(item.avg_amount) * (RECURRING_MONTHLY_FACTOR[item.frequency] || 0) * 12;
      cancelNote = `<br><strong>Kündigung „${esc(item.description || "?")}“ spart ${eur(yearly)} pro Jahr</strong> ` +
        `(${eur(yearly / 12)}/Monat).`;
    }
  }
  result.innerHTML = `Endstand normal: <strong>${eur(data.baseline.points.at(-1).balance)}</strong> · ` +
    `Szenario (gestrichelt): <strong>${eur(data.scenario.points.at(-1).balance)}</strong> ` +
    `(${sign}${eur(delta)}) · Tiefststand Szenario: ${eur(data.scenario.lowest_balance)}` +
    (data.scenario.goes_negative ? " ⚠️ rutscht ins Minus" : "") + cancelNote;
});

// Gemeinsamer Ignorieren-Button für erkannte wiederkehrende Zahlungen und
// Preiserhöhungen (beide bauen auf derselben account_id+description_key-
// Gruppierung auf, siehe crud.detect_recurring_transactions/detect_price_increases).
function bindIgnoreButtons(container) {
  container.querySelectorAll("[data-ignore-account]").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm(`„${btn.dataset.ignoreLabel || "?"}“ als Fehlerkennung ignorieren? Taucht dann nirgends mehr auf, bis du sie in der Liste wieder aktivierst.`)) return;
      await api("/recurring-ignores", {
        method: "POST",
        body: JSON.stringify({
          account_id: parseInt(btn.dataset.ignoreAccount),
          description_key: btn.dataset.ignoreKey,
          label: btn.dataset.ignoreLabel || btn.dataset.ignoreKey,
        }),
      });
      loadRecurringTab();
    });
  });
}

async function loadPriceIncreases() {
  const increases = await api("/transactions/price-increases");
  const panel = document.getElementById("price-increase-panel");
  panel.classList.toggle("hidden", increases.length === 0);
  const tbody = document.getElementById("price-increase-list");
  tbody.innerHTML = increases.map(p => `
    <tr>
      <td>${esc(p.description || "–")}</td>
      <td>${esc(p.account_name || "–")}</td>
      <td>${eur(p.old_amount)}</td>
      <td class="row-amount-neg">${eur(p.new_amount)}</td>
      <td class="row-amount-neg">+${p.increase_pct.toFixed(1).replace(".", ",")}%</td>
      <td>${fmtDate(p.changed_date)}</td>
      <td><button type="button" class="btn-ghost btn-sm" data-ignore-account="${p.account_id}" data-ignore-key="${esc(p.description_key)}" data-ignore-label="${esc(p.description || "")}">🚫 Ignorieren</button></td>
    </tr>`).join("");
  bindIgnoreButtons(tbody);
}

async function loadOverlappingContracts() {
  const groups = await api("/transactions/overlapping-contracts");
  const panel = document.getElementById("overlapping-contracts-panel");
  panel.classList.toggle("hidden", groups.length === 0);
  document.getElementById("overlapping-contracts-list").innerHTML = groups.map(g => `
    <div class="overlap-group">
      <div class="overlap-group-head">
        <strong>${esc(g.category_name)}</strong>
        <span class="overlap-group-total">${eur(g.monthly_total)} / Monat zusammen</span>
      </div>
      ${g.items.map(it => `
        <div class="overlap-item">
          <span>${esc(it.description || "–")}</span>
          <span class="overlap-item-meta">${esc(it.frequency)} · ${eur(Math.abs(it.avg_amount))} · ${esc(it.account_name || "–")}</span>
        </div>`).join("")}
    </div>`).join("");
}

let recurringItemsCache = [];

async function loadRecurringTab() {
  await loadCashflowForecast();
  const [items] = await Promise.all([api("/transactions/recurring"), loadContractReminders(), loadPriceIncreases(), loadOverlappingContracts(), loadIgnoredRecurring()]);
  recurringItemsCache = items;
  document.getElementById("scenario-cancel").innerHTML = '<option value="">– keins –</option>' +
    items.filter(it => it.avg_amount < 0).map(it =>
      `<option value="${esc(it.description_key)}">${esc(it.description || "?")} (${eur(it.avg_amount)}/${RECURRING_FREQ_LABELS[it.frequency] || it.frequency})</option>`
    ).join("");
  const tbody = document.getElementById("recurring-list");
  tbody.innerHTML = "";
  if (items.length === 0) {
    tbody.innerHTML = emptyRow(11, "repeat", "Noch keine wiederkehrenden Zahlungen erkannt (mindestens 3 ähnliche Buchungen mit regelmäßigem Abstand nötig).");
  }
  let monthlyTotal = 0;
  items.forEach(it => {
    const monthlyCost = Math.abs(it.avg_amount) * (RECURRING_MONTHLY_FACTOR[it.frequency] || 0);
    monthlyTotal += monthlyCost;
    // Hinterlegte Kündigungsfrist direkt in der Abo-Zeile zeigen, statt sie nur
    // in der separaten Tabelle darüber zu haben - hier entscheidet man, ob ein
    // Abo bleibt, und dafür ist "wie lange kann ich noch kündigen" die Kernzahl.
    const reminder = contractRemindersCache.find(
      r => r.account_id === it.account_id && r.description_key === it.description_key,
    );
    let noticeCell;
    if (reminder) {
      const days = reminder.days_until_reminder;
      const when = reminder.due
        ? "jetzt kündbar ⚠️"
        : `noch ${days} Tag${days !== 1 ? "e" : ""}`;
      noticeCell = `<button type="button" class="link-btn" data-cr-edit="${reminder.id}">
          ${reminder.should_cancel ? "🔴 " : ""}${when}
          <span class="page-sub" style="display:block">bis ${fmtDate(reminder.renewal_date)}</span>
        </button>`;
    } else {
      noticeCell = `<button type="button" class="btn-ghost btn-sm" data-cr-account="${it.account_id}" data-cr-key="${esc(it.description_key)}" data-cr-label="${esc(it.description || "")}" data-cr-freq="${it.frequency}">📄 Frist</button>`;
    }
    const tr = document.createElement("tr");
    if (reminder && reminder.due) tr.classList.add("row-warning");
    tr.innerHTML = `
      <td>${it.description || "–"}</td>
      <td>${it.account_name || "–"}</td>
      <td>${it.category_name || "–"}</td>
      <td>${RECURRING_FREQ_LABELS[it.frequency] || it.frequency}</td>
      <td class="${it.avg_amount >= 0 ? "row-amount-pos" : "row-amount-neg"}">${eur(it.avg_amount)}</td>
      <td>${eur(monthlyCost * 12)}</td>
      <td>${fmtDate(it.next_expected_date)}</td>
      <td>${eur(it.total_amount)}</td>
      <td>${noticeCell}</td>
      <td>${it.avg_amount < 0 ? `<button type="button" class="btn-ghost btn-sm" data-savings-key="${esc(it.description_key)}">💡 Was spare ich?</button>` : ""}</td>
      <td><button type="button" class="btn-ghost btn-sm" data-ignore-account="${it.account_id}" data-ignore-key="${esc(it.description_key)}" data-ignore-label="${esc(it.description || "")}">🚫 Ignorieren</button></td>`;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll("[data-cr-account]").forEach(btn => {
    btn.addEventListener("click", () => openContractReminderModal(
      parseInt(btn.dataset.crAccount), btn.dataset.crKey, btn.dataset.crLabel, btn.dataset.crFreq,
    ));
  });
  tbody.querySelectorAll("[data-cr-edit]").forEach(btn => {
    btn.addEventListener("click", () => {
      const r = contractRemindersCache.find(x => x.id === parseInt(btn.dataset.crEdit));
      if (r) openContractReminderModal(r.account_id, r.description_key, r.label, r.auto_advance_frequency, r);
    });
  });
  // "Was spare ich?" nutzt das bestehende Kündigungs-Szenario (baseline vs.
  // Prognose ohne dieses Abo) statt einer zweiten, eigenen Rechnung - so kann
  // die Antwort nicht von dem abweichen, was das Szenario darunter zeigt.
  tbody.querySelectorAll("[data-savings-key]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.getElementById("scenario-cancel").value = btn.dataset.savingsKey;
      document.getElementById("cashflow-scenario-form").requestSubmit();
      document.getElementById("cashflow-scenario-form").scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });
  bindIgnoreButtons(tbody);

  document.getElementById("recurring-summary-cards").innerHTML = `
    <div class="card">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><path d="M4 12a8 8 0 0114-5.3M20 12a8 8 0 01-14 5.3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></div>
      <div><h3>Erkannte Abos/Fixkosten</h3><p>${items.length}</p></div>
    </div>
    <div class="card">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><rect x="3" y="3" width="8" height="10" rx="2" stroke="currentColor" stroke-width="1.8"/><rect x="13" y="3" width="8" height="6" rx="2" stroke="currentColor" stroke-width="1.8"/><rect x="13" y="11" width="8" height="10" rx="2" stroke="currentColor" stroke-width="1.8"/></svg></div>
      <div><h3>Hochgerechnet pro Monat</h3><p>${eur(monthlyTotal)}</p></div>
    </div>`;
}

async function loadIgnoredRecurring() {
  const items = await api("/recurring-ignores");
  const panel = document.getElementById("recurring-ignored-panel");
  panel.classList.toggle("hidden", items.length === 0);
  const tbody = document.getElementById("recurring-ignored-list");
  tbody.innerHTML = items.map(it => `
    <tr>
      <td>${esc(it.label)}</td>
      <td>${esc(it.account_name || "–")}</td>
      <td><button type="button" class="btn-ghost btn-sm" data-unignore="${it.id}">Wieder anzeigen</button></td>
    </tr>`).join("");
  tbody.querySelectorAll("[data-unignore]").forEach(btn => {
    btn.addEventListener("click", async () => {
      await api(`/recurring-ignores/${btn.dataset.unignore}`, { method: "DELETE" });
      loadRecurringTab();
    });
  });
}

let contractRemindersCache = [];

async function loadContractReminders() {
  contractRemindersCache = await api("/contract-reminders");
  const tbody = document.getElementById("contract-reminder-list");
  tbody.innerHTML = "";
  if (contractRemindersCache.length === 0) {
    tbody.innerHTML = emptyRow(5, "file-text", "Noch keine Kündigungsfrist hinterlegt – bei einem Abo unten auf „📄 Frist“ klicken.");
    return;
  }
  contractRemindersCache.forEach(r => {
    const tr = document.createElement("tr");
    if (r.due) tr.classList.add("row-warning");
    tr.innerHTML = `
      <td>${r.should_cancel ? "🔴 " : ""}${esc(r.label)}${r.notes ? `<br><span class="page-sub">${esc(r.notes)}</span>` : ""}</td>
      <td>${r.account_name || "–"}</td>
      <td>${fmtDate(r.renewal_date)}</td>
      <td>${r.notice_period_days} Tage</td>
      <td>${fmtDate(r.reminder_date)}${r.due ? " ⚠️" : ""}</td>
      <td><button type="button" class="btn-ghost btn-sm" data-edit-cr="${r.id}">Bearbeiten</button></td>`;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll("[data-edit-cr]").forEach(btn => {
    btn.addEventListener("click", () => {
      const r = contractRemindersCache.find(x => x.id === parseInt(btn.dataset.editCr));
      if (r) openContractReminderModal(r.account_id, r.description_key, r.label, r.auto_advance_frequency, r);
    });
  });
}

function openContractReminderModal(accountId, descriptionKey, label, frequency, existingOverride = null) {
  const existing = existingOverride && existingOverride.id
    ? existingOverride
    : contractRemindersCache.find(r => r.account_id === accountId && r.description_key === descriptionKey);
  document.getElementById("contract-reminder-modal-title").textContent = existing ? "Kündigungsfrist bearbeiten" : "Kündigungsfrist anlegen";
  document.getElementById("contract-reminder-modal-sub").textContent = frequency
    ? `Häufigkeit erkannt: ${RECURRING_FREQ_LABELS[frequency] || frequency} – Verlängerungstermin rückt danach automatisch weiter.`
    : "";
  document.getElementById("cr-id").value = existing ? existing.id : "";
  document.getElementById("cr-account-id").value = accountId;
  document.getElementById("cr-description-key").value = descriptionKey;
  document.getElementById("cr-frequency").value = frequency || "";
  document.getElementById("cr-label").value = existing ? existing.label : label;
  document.getElementById("cr-renewal").value = existing ? existing.renewal_date : "";
  document.getElementById("cr-notice").value = existing ? existing.notice_period_days : 30;
  document.getElementById("cr-should-cancel").checked = existing ? existing.should_cancel : false;
  document.getElementById("cr-notes").value = existing?.notes || "";
  document.getElementById("cr-delete").classList.toggle("hidden", !existing);
  document.getElementById("contract-reminder-modal").classList.remove("hidden");
}

function closeContractReminderModal() {
  document.getElementById("contract-reminder-modal").classList.add("hidden");
}
document.getElementById("contract-reminder-modal-close").addEventListener("click", closeContractReminderModal);

document.getElementById("contract-reminder-form").addEventListener("submit", async e => {
  e.preventDefault();
  const id = document.getElementById("cr-id").value;
  const payload = {
    account_id: parseInt(document.getElementById("cr-account-id").value),
    description_key: document.getElementById("cr-description-key").value,
    label: document.getElementById("cr-label").value,
    renewal_date: document.getElementById("cr-renewal").value,
    notice_period_days: parseInt(document.getElementById("cr-notice").value),
    auto_advance_frequency: document.getElementById("cr-frequency").value || null,
    should_cancel: document.getElementById("cr-should-cancel").checked,
    notes: document.getElementById("cr-notes").value.trim() || null,
  };
  await api(id ? `/contract-reminders/${id}` : "/contract-reminders", {
    method: id ? "PUT" : "POST",
    body: JSON.stringify(payload),
  });
  closeContractReminderModal();
  loadContractReminders();
});

document.getElementById("cr-delete").addEventListener("click", async () => {
  const id = document.getElementById("cr-id").value;
  if (!id || !confirm("Kündigungsfrist-Erinnerung wirklich löschen?")) return;
  await api(`/contract-reminders/${id}`, { method: "DELETE" });
  closeContractReminderModal();
  loadContractReminders();
});

document.getElementById("tx-filter-btn").addEventListener("click", loadTransactions);
document.getElementById("tx-search").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); loadTransactions(); } });
document.getElementById("tx-hide-transfers").addEventListener("change", loadTransactions);
{
  const saved = localStorage.getItem("txHideTransfers");
  if (saved !== null) document.getElementById("tx-hide-transfers").checked = saved === "1";
}

document.getElementById("tx-form").addEventListener("submit", async e => {
  e.preventDefault();
  const payload = {
    date: document.getElementById("tx-date").value,
    amount: parseFloat(document.getElementById("tx-amount").value),
    account_id: parseInt(document.getElementById("tx-account").value),
    category_id: document.getElementById("tx-category").value ? parseInt(document.getElementById("tx-category").value) : null,
    trip_id: document.getElementById("tx-trip").value ? parseInt(document.getElementById("tx-trip").value) : null,
    description: document.getElementById("tx-description").value,
    notes: document.getElementById("tx-notes").value,
  };

  let tx;
  if (editingTxId) {
    tx = await api(`/transactions/${editingTxId}`, { method: "PUT", body: JSON.stringify(payload) });
  } else {
    tx = await api("/transactions", { method: "POST", body: JSON.stringify(payload) });
  }

  const fileInput = document.getElementById("tx-receipt");
  if (fileInput.files.length > 0) {
    const fd = new FormData();
    fd.append("file", fileInput.files[0]);
    await api(`/transactions/${tx.id}/receipt`, { method: "POST", body: fd });
  }

  resetTxForm();
  closeTxModal();
  loadTransactions();
  loadAccounts();
});

function openTxModal() {
  document.getElementById("tx-modal").classList.remove("hidden");
}
function closeTxModal() {
  document.getElementById("tx-modal").classList.add("hidden");
}

window.editTransaction = async id => {
  const txs = await api("/transactions");
  const t = txs.find(x => x.id === id);
  editingTxId = id;
  document.getElementById("tx-date").value = t.date;
  document.getElementById("tx-amount").value = t.amount;
  document.getElementById("tx-account").value = t.account_id;
  document.getElementById("tx-category").value = t.category_id || "";
  document.getElementById("tx-trip").value = t.trip_id || "";
  document.getElementById("tx-description").value = t.description || "";
  document.getElementById("tx-notes").value = t.notes || "";
  document.getElementById("tx-cancel").classList.remove("hidden");
  document.getElementById("tx-submit").textContent = "Änderungen speichern";
  document.getElementById("tx-modal-title").textContent = "Buchung bearbeiten";
  openTxModal();
};
document.getElementById("tx-new-btn").addEventListener("click", () => {
  resetTxForm();
  document.getElementById("tx-modal-title").textContent = "Neue Buchung";
  openTxModal();
});
document.getElementById("tx-modal-close").addEventListener("click", closeTxModal);
document.getElementById("tx-cancel").addEventListener("click", () => {
  resetTxForm();
  closeTxModal();
});
function resetTxForm() {
  editingTxId = null;
  document.getElementById("tx-form").reset();
  document.getElementById("tx-date").value = new Date().toISOString().slice(0, 10);
  document.getElementById("tx-cancel").classList.add("hidden");
  document.getElementById("tx-submit").textContent = "Buchen";
}
window.deleteTransaction = async id => {
  if (!confirm("Buchung wirklich löschen?")) return;
  await api(`/transactions/${id}`, { method: "DELETE" });
  loadTransactions();
  loadAccounts();
};

// ================= PROFILE =================
async function loadProfile() {
  const profile = await api("/auth/profile");
  document.getElementById("profile-name").value = profile.display_name;
  await loadBenchmark();
}

document.getElementById("profile-form").addEventListener("submit", async e => {
  e.preventDefault();
  const display_name = document.getElementById("profile-name").value;
  await api("/auth/profile", { method: "PUT", body: JSON.stringify({ display_name }) });
  toast("Profil gespeichert.");
});

// ================= FOTOS (IMMICH) =================
// Je Duplikatgruppe die Menge der aktuell zum Papierkorb ausgewaehlten
// Bild-IDs - eine echte, von den anderen Bildern unabhaengige Mehrfachauswahl.
// Kein "genau ein Bild bleibt" mehr: leer = alles bleibt, komplett gefuellt =
// alles geht raus, beides ist ein gueltiger Zustand.
const photoTrash = new Map();
// Immichs Vorschlag bleibt als fester Bezugspunkt fuer die
// Uebereinstimmungs-Prozente erhalten, unabhaengig davon, was der Nutzer
// gerade aus-/abgewaehlt hat - sonst wuerde sich die Prozentzahl bei jedem
// Klick auf ein anderes Bild beziehen und waere nicht mehr vergleichbar.
const photoSuggestedKeep = new Map();
// Übereinstimmung je Gruppe, nachgeladen nachdem die Bilder schon stehen -
// die Berechnung braucht einen Moment und soll die Anzeige nicht aufhalten.
const photoSimilarity = new Map();
let photoGroupsCache = [];
let photoPage = { offset: 0, hasMore: false, total: 0 };

function formatBytes(n) {
  if (!n) return "";
  const mb = n / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.round(n / 1024)} KB`;
}

// Ohne Rueckgriff auf Admin-Rechte (server.statistics) bleibt available=false -
// dann einfach unauffaellig nichts anzeigen, statt eine Fehlermeldung fuer
// eine reine Zusatzinfo.
async function loadPhotoStats() {
  const el = document.getElementById("photos-stats");
  try {
    const s = await api("/immich/stats");
    if (!s.available) { el.classList.add("hidden"); return; }
    const totalGb = (s.usage_bytes / 1024 / 1024 / 1024).toFixed(1);
    el.textContent = `📚 Bibliothek: ${s.photos.toLocaleString("de-DE")} Fotos, ` +
      `${s.videos.toLocaleString("de-DE")} Videos, ${totalGb} GB belegt.`;
    el.classList.remove("hidden");
  } catch {
    el.classList.add("hidden");
  }
}

async function loadPhotosTab(offset = 0) {
  const hint = document.getElementById("photos-setup-hint");
  const hintText = document.getElementById("photos-setup-text");
  const summary = document.getElementById("photos-summary");
  const wrap = document.getElementById("photos-groups");

  const s = await api("/settings/immich");
  if (!s.url || !s.api_key_set) {
    hint.classList.remove("hidden");
    summary.classList.add("hidden");
    wrap.innerHTML = "";
    hintText.textContent = !s.url && !s.api_key_set
      ? "Es fehlen Server-Adresse und API-Schlüssel."
      : (!s.url ? "Es fehlt die Server-Adresse." : "Es fehlt der API-Schlüssel.");
    return;
  }
  hint.classList.add("hidden");
  loadPhotoStats();

  wrap.innerHTML = `<p class="page-sub loading-pulse">Suche doppelte Aufnahmen …</p>`;
  let data;
  try {
    data = await api(`/immich/duplicates?offset=${offset}&limit=20`);
  } catch (e) {
    summary.classList.add("hidden");
    wrap.innerHTML = `<div class="panel"><p class="page-sub">${esc(e.message)}</p></div>`;
    return;
  }

  photoPage = { offset: data.offset, hasMore: data.has_more, total: data.total_groups };
  photoTrash.clear();
  photoSuggestedKeep.clear();
  data.groups.forEach(g => {
    // Immichs Vorschlag übernehmen; falls keiner kommt, das erste Bild.
    const suggested = g.suggested_keep_ids.find(id => g.assets.some(a => a.id === id)) || g.assets[0]?.id;
    photoSuggestedKeep.set(g.duplicate_id, suggested);
    // Vorbelegung wie bisher (alles ausser dem Vorschlag zum Papierkorb) -
    // spart bei der haeufigsten Auswahl ("das beste Bild behalten") weiterhin
    // Klicks. Der Nutzer kann jedes Bild einzeln umschalten, auch den
    // Vorschlag selbst, bis hin zu "alles" oder "nichts".
    g.assets.sort((a, b) => (b.id === suggested) - (a.id === suggested));
    photoTrash.set(g.duplicate_id, new Set(g.assets.filter(a => a.id !== suggested).map(a => a.id)));
  });
  summary.classList.remove("hidden");
  if (data.total_groups === 0) {
    summary.innerHTML = `<strong>Keine Duplikate gefunden.</strong> Deine Bibliothek ist sauber.`;
    wrap.innerHTML = "";
    return;
  }
  // Der Papierkorb-Zustand kommt vom Server und ist keine Behauptung: Immich
  // löscht bei abgeschaltetem Papierkorb sofort endgültig.
  const trashNote = data.trash_enabled
    ? `Die übrigen wandern in Immichs Papierkorb und sind dort
       ${data.trash_days ? `${data.trash_days} Tage lang ` : ""}wiederherstellbar.`
    : `<span class="photos-warn">⚠️ Achtung: In Immich ist der Papierkorb abgeschaltet.
       Aufräumen ist deshalb gesperrt – sonst wären Bilder sofort unwiderruflich weg.</span>`;
  const from = data.offset + 1;
  const to = data.offset + data.groups.length;
  summary.innerHTML = `<strong>${data.total_groups} Gruppen</strong>
    mit insgesamt ${data.total_assets} Aufnahmen – angezeigt ${from}–${to}.
    Wähle je Gruppe, welche Bilder in den Papierkorb sollen – jedes Bild einzeln,
    auch alle oder keins. ${trashNote}`;

  // Auf Wunsch zuerst die staerksten Uebereinstimmungen zeigen (100% zuerst,
  // absteigend) statt Immichs eigener Reihenfolge. Das Backend liefert schon
  // best_similarity_percent je Gruppe mit (billiger Vorab-Vergleich, siehe
  // main._best_similarity) - damit steht die Sortierung sofort, ohne auf die
  // vollstaendigen Paar-Vergleiche zu warten. Sobald loadSimilarities() die
  // genauen Werte nachliefert, wird nochmal nachsortiert (kann die Reihenfolge
  // leicht verfeinern, das grobe Bild stimmt aber von Anfang an).
  data.groups.sort((a, b) => (b.best_similarity_percent ?? 0) - (a.best_similarity_percent ?? 0));
  photoGroupsCache = data.groups;
  renderPhotoGroups();

  await loadSimilarities(data.groups);
  data.groups.sort((a, b) => groupMaxSimilarity(b) - groupMaxSimilarity(a));
  photoGroupsCache = data.groups;
  renderPhotoGroups();
}

function groupMaxSimilarity(group) {
  const pairs = photoSimilarity.get(group.duplicate_id) || {};
  let max = 0;
  for (const inner of Object.values(pairs)) {
    for (const pct of Object.values(inner)) {
      if (pct > max) max = pct;
    }
  }
  // Fallback auf den billigen Backend-Wert, falls fuer diese Gruppe kein
  // Paar-Vergleich zustande kam (z.B. Netzwerkfehler, siehe loadSimilarities)
  // - sonst faellt eine an sich sehr aehnliche Gruppe faelschlich auf 0/ans Ende.
  return max || group.best_similarity_percent || 0;
}

// Nacheinander statt alle gleichzeitig: jede Gruppe bedeutet mehrere
// Bildabrufe, parallel wuerde das Immich unnoetig belasten.
async function loadSimilarities(groups) {
  for (const g of groups) {
    if (photoSimilarity.has(g.duplicate_id)) continue;
    try {
      const ids = g.assets.map(a => a.id).join(",");
      const s = await api(`/immich/duplicates/${g.duplicate_id}/similarity?asset_ids=${encodeURIComponent(ids)}`);
      photoSimilarity.set(g.duplicate_id, s.pairs);
    } catch (e) {
      photoSimilarity.set(g.duplicate_id, {});
    }
  }
}

// Beim Umwählen des zu behaltenden Bilds NUR die eine betroffene Gruppe
// aktualisieren - nicht renderPhotoGroups() (kompletter Neuaufbau aller 20
// sichtbaren Gruppen samt jedem einzelnen Bild) aufrufen. Das war der
// eigentliche Grund fuer "die ganze Seite laedt neu, aber es passiert
// nichts": ein einzelner Kartenklick liess bei jeder Betaetigung 40-100+
// Vorschaubilder gleichzeitig neu anfordern, was auf allen getesteten
// Browsern (iPhone/Mac Safari/Windows Firefox) als voller Seiten-Neuaufbau
// wahrgenommen wurde - der Zustand aendert sich dabei zwar korrekt, aber
// sichtbar wird davon in dem visuellen Chaos praktisch nichts.
// Aktualisiert nur die eine betroffene Gruppe (Kartenzustand, Papierkorb-
// Zaehler/-Knopf, Uebereinstimmungs-Plaketten) - kein renderPhotoGroups()
// (kompletter Neuaufbau aller sichtbaren Gruppen samt jedem Vorschaubild).
// Genau das war zuvor der Grund, warum ein einzelner Klick wie ein Neuladen
// der ganzen Seite wirkte.
function updateGroupSelectionUI(duplicateId) {
  const group = photoGroupsCache.find(g => g.duplicate_id === duplicateId);
  const groupEl = document.querySelector(`.photo-group[data-group="${CSS.escape(duplicateId)}"]`);
  if (!group || !groupEl) return;
  const trashSet = photoTrash.get(duplicateId) || new Set();

  groupEl.querySelectorAll(".photo-card").forEach(card => {
    const isTrash = trashSet.has(card.dataset.asset);
    card.classList.toggle("is-trash", isTrash);
    card.classList.toggle("is-keep", !isTrash);
    const badge = card.querySelector(".photo-badge");
    if (badge) badge.textContent = isTrash ? "Papierkorb" : "behalten";
  });

  const applyBtn = groupEl.querySelector("[data-apply]");
  if (applyBtn) {
    applyBtn.textContent = `${trashSet.size} in den Papierkorb`;
    applyBtn.classList.toggle("hidden", trashSet.size === 0);
  }

  updateSimilarityBadges(duplicateId);
}

function updateSimilarityBadges(duplicateId) {
  const groupEl = document.querySelector(`.photo-group[data-group="${CSS.escape(duplicateId)}"]`);
  if (!groupEl) return;
  // Fester Bezugspunkt (Immichs Vorschlag), unabhaengig von der aktuellen
  // Papierkorb-Auswahl - siehe Kommentar bei der Variable weiter oben.
  const refId = photoSuggestedKeep.get(duplicateId);
  const pairs = photoSimilarity.get(duplicateId) || {};
  groupEl.querySelectorAll(".photo-card").forEach(card => {
    const assetId = card.dataset.asset;
    const existing = card.querySelector(".photo-sim");
    if (assetId === refId) { existing?.remove(); return; }
    const pct = pairs[refId]?.[assetId];
    if (pct === undefined) { existing?.remove(); return; }
    const cls = pct >= 95 ? "sim-high" : pct >= 80 ? "sim-mid" : "sim-low";
    const title = pct >= 95 ? "praktisch identisch" : pct >= 80 ? "sehr ähnlich" : "nur ähnliche Aufnahme";
    if (existing) {
      existing.textContent = `${pct}%`;
      existing.className = `photo-sim ${cls}`;
      existing.title = title;
    } else {
      const span = document.createElement("span");
      span.className = `photo-sim ${cls}`;
      span.title = title;
      span.textContent = `${pct}%`;
      card.querySelector(".photo-badge")?.after(span);
    }
  });

  // Große Übereinstimmungsanzeige im Gruppentitel aktualisieren - die
  // Ähnlichkeit wird oft erst asynchron nachgeladen, nach dem ersten Rendern
  // der Gruppe. groupUniformPct() entscheidet, ob das bei dieser Gruppengröße
  // überhaupt eindeutig genug ist (siehe Kommentar dort).
  const group = photoGroupsCache.find(g => g.duplicate_id === duplicateId);
  const titleEl = groupEl.querySelector(".panel-title");
  if (group && titleEl) {
    titleEl.querySelector(".photo-sim-big")?.remove();
    const pct = groupUniformPct(group, refId);
    if (pct !== null) {
      const cls = pct >= 95 ? "sim-high" : pct >= 80 ? "sim-mid" : "sim-low";
      const span = document.createElement("span");
      span.className = `photo-sim-big ${cls}`;
      span.textContent = `${pct}% Übereinstimmung`;
      titleEl.appendChild(span);
    }
  }
}

// Bei genau zwei Aufnahmen ist die Übereinstimmung die zentrale Frage der
// ganzen Gruppe ("ist das wirklich dasselbe Foto?") - deshalb groß und direkt
// sichtbar statt nur als kleine Plakette an der Karte. Bei mehr als zwei
// Aufnahmen wäre eine einzelne Zahl mehrdeutig (welches Paar ist gemeint?) -
// AUSSER alle stimmen exakt zu 100% mit dem Vorschlag überein, dann ist die
// Aussage "das ist wirklich überall dasselbe Bild" trotzdem eindeutig.
function groupUniformPct(g, refId) {
  const others = g.assets.filter(a => a.id !== refId).map(a => a.id);
  if (!others.length) return null;
  const pairs = photoSimilarity.get(g.duplicate_id)?.[refId] || {};
  if (g.assets.length === 2) {
    const pct = pairs[others[0]];
    return (pct === undefined || pct === null) ? null : pct;
  }
  for (const id of others) {
    const pct = pairs[id];
    if (pct === undefined || pct === null || pct < 100) return null;
  }
  return 100;
}

function renderBigSimHtml(g, refId) {
  const pct = groupUniformPct(g, refId);
  if (pct === null) return "";
  const cls = pct >= 95 ? "sim-high" : pct >= 80 ? "sim-mid" : "sim-low";
  return `<span class="photo-sim-big ${cls}">${pct}% Übereinstimmung</span>`;
}

function videoBadgeHtml(type) {
  return type === "VIDEO" ? `<span class="photo-video-badge" title="Video">▶</span>` : "";
}

function renderPhotoGroups() {
  const wrap = document.getElementById("photos-groups");
  wrap.innerHTML = photoGroupsCache.map(g => {
    const trashSet = photoTrash.get(g.duplicate_id) || new Set();
    const refId = photoSuggestedKeep.get(g.duplicate_id);
    const cards = g.assets.map(a => {
      const isTrash = trashSet.has(a.id);
      const dims = a.width && a.height ? `${a.width}×${a.height}` : "";
      const meta = [dims, formatBytes(a.size_bytes)].filter(Boolean).join(" · ");
      // Übereinstimmung zu Immichs Vorschlag - beantwortet die Frage
      // "ist das wirklich dasselbe Foto oder nur eine ähnliche Aufnahme".
      const pct = a.id === refId ? null : photoSimilarity.get(g.duplicate_id)?.[refId]?.[a.id];
      const simBadge = pct === undefined || pct === null ? "" :
        `<span class="photo-sim ${pct >= 95 ? "sim-high" : pct >= 80 ? "sim-mid" : "sim-low"}"
           title="${pct >= 95 ? "praktisch identisch" : pct >= 80 ? "sehr ähnlich" : "nur ähnliche Aufnahme"}">${pct}%</span>`;
      const videoBadge = videoBadgeHtml(a.type);
      return `<button type="button" class="photo-card ${isTrash ? "is-trash" : "is-keep"}"
                data-group="${esc(g.duplicate_id)}" data-asset="${esc(a.id)}">
        <img loading="lazy" src="/api/immich/thumbnail/${esc(a.id)}" alt="">
        ${videoBadge}
        <span class="photo-zoom" data-zoom="${esc(a.id)}" data-caption="${esc(a.file_name || "")}"
              title="Vergrößern">🔍</span>
        <span class="photo-badge">${isTrash ? "Papierkorb" : "behalten"}</span>${simBadge}
        <span class="photo-meta">
          <span class="photo-name">${esc(a.file_name || "")}</span>
          ${meta ? `<span>${esc(meta)}</span>` : ""}
          ${a.created_at ? `<span>${fmtDate(a.created_at.slice(0, 10))}</span>` : ""}
        </span>
      </button>`;
    }).join("");

    // Gekürzt dargestellte Gruppe: dann darf nicht "in den Papierkorb"
    // angeboten werden, denn die nicht gezeigten Bilder wären mit betroffen,
    // ohne dass man sie je gesehen hat.
    const truncated = g.asset_count > g.assets.length;
    // Immer verfügbar (nicht nur bei bis zu 4 Bildern) und immer an erster
    // Stelle - bei mehr als 4 Aufnahmen vergleicht er nur die ersten 4. Sonst
    // rutschte an dieser Stelle bei größeren Gruppen "Sind keine Duplikate"
    // nach vorn, und Nutzer haben aus Gewohnheit an der ersten Position
    // geklickt und dabei echte Duplikatgruppen ausversehen verworfen.
    const compareBtn = g.assets.length >= 2
      ? `<button type="button" class="btn-ghost" data-compare="${esc(g.duplicate_id)}">🔍 ${g.assets.length > 4 ? "Erste 4 vergleichen" : "Nebeneinander vergleichen"}</button>`
      : "";
    // "Sind keine Duplikate" bewusst immer als LETZTER Button, nie an erster
    // Stelle - siehe Kommentar bei compareBtn oben.
    const actions = truncated
      ? `<button type="button" class="btn-ghost" data-dismiss="${esc(g.duplicate_id)}">Sind keine Duplikate</button>`
      : `${compareBtn}
         <button type="button" class="btn-ghost" data-select-all="${esc(g.duplicate_id)}">Alle Papierkorb</button>
         <button type="button" class="btn-ghost" data-select-none="${esc(g.duplicate_id)}">Alle behalten</button>
         <button type="button" class="btn-primary ${trashSet.size === 0 ? "hidden" : ""}" data-apply="${esc(g.duplicate_id)}">
           ${trashSet.size} in den Papierkorb
         </button>
         <button type="button" class="btn-ghost" data-dismiss="${esc(g.duplicate_id)}">Sind keine Duplikate</button>`;

    const bigSim = renderBigSimHtml(g, refId);

    return `<div class="panel photo-group" data-group="${esc(g.duplicate_id)}">
      <div class="photo-group-head">
        <h3 class="panel-title">${g.asset_count} ähnliche Aufnahmen${bigSim}</h3>
        <div class="photo-group-actions">${actions}</div>
      </div>
      ${truncated ? `<p class="photos-warn">Sehr große Gruppe – hier werden nur
        ${g.assets.length} von ${g.asset_count} Aufnahmen gezeigt. Bei dieser Menge sind das
        meist keine echten Duplikate (z.B. eine Serienaufnahme). Zum Aufräumen bitte direkt
        in Immich prüfen – hier wäre nicht sichtbar, was alles betroffen ist.</p>` : ""}
      <div class="photo-strip">${cards}</div>
    </div>`;
  }).join("");

  // Blätter-Schaltflächen
  const nav = [];
  if (photoPage.offset > 0) nav.push(`<button type="button" class="btn-ghost" data-page="${Math.max(0, photoPage.offset - 20)}">← Zurück</button>`);
  if (photoPage.hasMore) nav.push(`<button type="button" class="btn-primary" data-page="${photoPage.offset + 20}">Weitere 20 Gruppen →</button>`);
  if (nav.length) wrap.innerHTML += `<div class="photo-pager">${nav.join("")}</div>`;
}

// Klick auf ein Bild wählt es als das zu behaltende aus.
// ---------- Lupe: Bild vergrößert anzeigen ----------
// Baut 1 bis 4 Figuren dynamisch auf, statt fest verdrahteter 2 Slots -
// damit sich sowohl das einzelne Vergrößern als auch der Nebeneinander-
// Vergleich (jetzt bis zu 4 Aufnahmen) dieselbe Funktion teilen.
let lightboxAssetIds = [];
let lightboxGroupId = null;

function renderLightbox(items) {
  const box = document.getElementById("lightbox-images");
  box.innerHTML = items.map((it, i) => `<figure class="lightbox-figure">
      <img id="lightbox-img-${i}" alt="" src="/api/immich/thumbnail/${encodeURIComponent(it.id)}?size=preview">
      <figcaption class="lightbox-caption">${esc(it.caption || "")}</figcaption>
    </figure>`).join("");
  const isCompare = items.length > 1;
  document.getElementById("lightbox-box").classList.toggle("is-compare", isCompare);
  document.getElementById("lightbox-delete-all").classList.toggle("hidden", !isCompare);
  document.getElementById("photo-lightbox").classList.remove("hidden");
  lightboxAssetIds = items.map(it => it.id);
  document.getElementById("lightbox-ai-result").textContent = "";
}

function openLightbox(assetId, caption) {
  lightboxGroupId = null;
  renderLightbox([{ id: assetId, caption }]);
}

// Bei bis zu vier Aufnahmen lohnt sich ein direkter Nebeneinander-Vergleich
// besonders - bei mehr wäre die Übersicht zu unruhig, um noch zu erkennen,
// welche Details sich unterscheiden.
function openLightboxCompare(items, groupId = null) {
  lightboxGroupId = groupId;
  renderLightbox(items);
}

function closeLightbox() {
  document.getElementById("photo-lightbox").classList.add("hidden");
  document.getElementById("lightbox-images").innerHTML = "";
  lightboxAssetIds = [];
  lightboxGroupId = null;
}

document.getElementById("lightbox-delete-all").addEventListener("click", async () => {
  if (!lightboxAssetIds.length) return;
  if (!confirm(`${lightboxAssetIds.length} Aufnahme(n) in den Papierkorb verschieben?\n\nSie bleiben in Immich wiederherstellbar.`)) return;
  try {
    const res = await api("/immich/photos/trash", {
      method: "POST",
      body: JSON.stringify({ asset_ids: lightboxAssetIds }),
    });
    toast(`${res.trashed} Aufnahme(n) in den Papierkorb verschoben.`);
    const groupId = lightboxGroupId;
    closeLightbox();
    if (groupId) removePhotoGroupLocally(groupId);
  } catch (err) {
    toast("Fehler: " + err.message);
  }
});
document.getElementById("lightbox-close").addEventListener("click", closeLightbox);
document.getElementById("photo-lightbox").addEventListener("click", e => {
  if (e.target.id === "photo-lightbox") closeLightbox();
});

document.getElementById("lightbox-ai-btn").addEventListener("click", async () => {
  if (!lightboxAssetIds.length) return;
  const btn = document.getElementById("lightbox-ai-btn");
  const resultEl = document.getElementById("lightbox-ai-result");
  btn.disabled = true;
  resultEl.textContent = "Analysiere … (kann bei kleinen Modellen auf bescheidener Hardware einige Minuten dauern)";
  try {
    const res = await api("/immich/ai-suggestion", {
      method: "POST",
      body: JSON.stringify({ asset_ids: lightboxAssetIds }),
    });
    resultEl.textContent = res.error ? `Fehler: ${res.error}` : res.reason || "Keine Einschätzung erhalten.";
  } catch (err) {
    resultEl.textContent = "Fehler: " + err.message;
  } finally {
    btn.disabled = false;
  }
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeLightbox();
});

// Vor dem eigentlichen Auswahl-Klick abgefangen: ein Klick auf die Lupe soll
// das Bild vergrößern, nicht gleichzeitig als "behalten"/"auswählen" zählen.
function checkZoomClick(e) {
  const zoom = e.target.closest("[data-zoom]");
  if (!zoom) return false;
  openLightbox(zoom.dataset.zoom, zoom.dataset.caption);
  return true;
}

document.getElementById("photos-groups").addEventListener("click", async e => {
  if (checkZoomClick(e)) return;

  const compareId = e.target.closest("[data-compare]")?.dataset.compare;
  if (compareId) {
    const group = photoGroupsCache.find(g => g.duplicate_id === compareId);
    if (group) {
      // Nebeneinander passen nur bis zu 4 Bilder - bei mehr werden nur die
      // ersten 4 gezeigt (siehe Kommentar bei compareBtn oben).
      openLightboxCompare(group.assets.slice(0, 4).map(a => ({ id: a.id, caption: a.file_name })), compareId);
    }
    return;
  }

  const pageTo = e.target.closest("[data-page]")?.dataset.page;
  if (pageTo !== undefined) {
    await loadPhotosTab(parseInt(pageTo, 10));
    window.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }

  const card = e.target.closest(".photo-card");
  if (card) {
    const trashSet = photoTrash.get(card.dataset.group);
    // Unabhaengiges Umschalten NUR dieses einen Bilds - kein "genau eins
    // bleibt" mehr. Alle Bilder koennen einzeln in den Papierkorb, bis hin zu
    // allen oder keinem.
    trashSet.has(card.dataset.asset) ? trashSet.delete(card.dataset.asset) : trashSet.add(card.dataset.asset);
    updateGroupSelectionUI(card.dataset.group);
    return;
  }

  const selectAllId = e.target.closest("[data-select-all]")?.dataset.selectAll;
  if (selectAllId) {
    const group = photoGroupsCache.find(g => g.duplicate_id === selectAllId);
    photoTrash.set(selectAllId, new Set(group.assets.map(a => a.id)));
    updateGroupSelectionUI(selectAllId);
    // "Alle Papierkorb" heisst hier bewusst sofort anwenden, nicht nur
    // auswaehlen - wer den Knopf drueckt, hat die Entscheidung fuer die ganze
    // Gruppe schon getroffen und will nicht noch extra auf "Anwenden" klicken.
    await applyGroupTrash(selectAllId, true);
    return;
  }

  const selectNoneId = e.target.closest("[data-select-none]")?.dataset.selectNone;
  if (selectNoneId) {
    // "Alle behalten" heisst: mit dieser Gruppe gibt es nichts zu tun - genau
    // das drueckt Immichs Dismiss-Funktion aus (Gruppe nicht mehr als
    // Duplikat fuehren, nichts loeschen). Ohne das blieb die Gruppe nach
    // "alle behalten" einfach stehen, ohne dass es einen naechsten Schritt gab.
    await dismissGroup(selectNoneId);
    return;
  }

  const applyId = e.target.closest("[data-apply]")?.dataset.apply;
  if (applyId) {
    await applyGroupTrash(applyId);
    return;
  }

  const dismissId = e.target.closest("[data-dismiss]")?.dataset.dismiss;
  if (dismissId) {
    await dismissGroup(dismissId);
  }
});

// forceConfirm: "Alle Papierkorb" wirft die ganze Gruppe auf einmal weg und
// ist der Klick, bei dem Vertippen am teuersten ist (siehe Fehlklick-Fix oben)
// - dafür bleibt die Rückfrage IMMER bestehen, auch wenn "ohne Rückfrage"
// aktiviert ist. Die Einstellung gilt nur für bewusst manuell zusammengestellte
// Auswahl über die einzelnen Bild-Karten.
async function applyGroupTrash(duplicateId, forceConfirm = false) {
  const group = photoGroupsCache.find(g => g.duplicate_id === duplicateId);
  if (!group) return;
  const trashSet = photoTrash.get(duplicateId) || new Set();
  const trashIds = [...trashSet];
  const keepIds = group.assets.map(a => a.id).filter(id => !trashSet.has(id));
  if (!trashIds.length) return;
  const warnAll = keepIds.length === 0
    ? "\n\n⚠️ Es bleibt kein Bild dieser Gruppe übrig - alle wandern in den Papierkorb."
    : "";
  if ((forceConfirm || !immichSkipConfirm) &&
      !confirm(`${trashIds.length} Aufnahme(n) in den Papierkorb verschieben?${warnAll}\n\nSie bleiben in Immich wiederherstellbar.`)) return;
  try {
    const res = await api("/immich/duplicates/resolve", {
      method: "POST",
      body: JSON.stringify({ groups: [{ duplicate_id: duplicateId, keep_ids: keepIds, trash_ids: trashIds }] }),
    });
    toast(`${res.trashed_assets} Aufnahme(n) in den Papierkorb verschoben.`);
    removePhotoGroupLocally(duplicateId);
  } catch (err) {
    toast("Fehler: " + err.message);
  }
}

async function dismissGroup(duplicateId) {
  try {
    await api(`/immich/duplicates/${duplicateId}`, { method: "DELETE" });
    toast("Gruppe ausgeblendet, es wurde nichts gelöscht.");
    removePhotoGroupLocally(duplicateId);
  } catch (err) {
    toast("Fehler: " + err.message);
  }
}

// Entfernt eine erledigte Gruppe nur aus der aktuell angezeigten Seite, statt
// alle 20 Gruppen neu vom Server zu laden. Der Nutzer will bewusst auf dieser
// Seite bleiben, bis alle erledigt sind, und selbst entscheiden, wann er
// "Weitere laden" klickt - nicht nach jeder einzelnen Aktion einen kompletten
// Seiten-Neuaufbau erleben.
function removePhotoGroupLocally(duplicateId) {
  photoGroupsCache = photoGroupsCache.filter(g => g.duplicate_id !== duplicateId);
  photoTrash.delete(duplicateId);
  photoSuggestedKeep.delete(duplicateId);
  photoSimilarity.delete(duplicateId);
  document.querySelector(`.photo-group[data-group="${CSS.escape(duplicateId)}"]`)?.remove();

  const summary = document.getElementById("photos-summary");
  if (photoGroupsCache.length === 0) {
    summary.innerHTML = `Alle Gruppen dieser Seite sind erledigt. Auf "Weitere laden" klicken für mehr,
      oder <button type="button" class="link-btn" id="photos-reload-inline">neu laden</button>.`;
    document.getElementById("photos-reload-inline")?.addEventListener("click", () => loadPhotosTab(photoPage.offset));
  }
}

document.getElementById("photos-reload").addEventListener("click", () => loadPhotosTab());
document.getElementById("photos-goto-settings").addEventListener("click", () => {
  document.querySelector('.nav-btn[data-tab="settings"]').click();
});

// ---------- Alle Fotos (ungefiltert, nur Swipe-Modus) ----------
let allPhotosState = { offset: 0, hasMore: true, assets: [], trashEnabled: true };

async function loadAllPhotos(offset = 0) {
  let d;
  try {
    d = await api(`/immich/photos?offset=${offset}&limit=60&shuffle=true`);
  } catch (e) {
    toast("Fehler: " + e.message);
    allPhotosState = { ...allPhotosState, hasMore: false };
    return;
  }
  allPhotosState = { offset: d.offset, hasMore: d.has_more, assets: d.assets, trashEnabled: d.trash_enabled };
}

document.getElementById("photos-view-all").addEventListener("click", e => {
  if (checkZoomClick(e)) return;
  if (e.target.closest("[data-swipe-action]")) {
    commitSwipe("all", e.target.closest("[data-swipe-action]").dataset.swipeAction);
  }
});

// ---------- Screenshots ----------
const shotSelection = new Set();
let shotState = { months: 12, offset: 0, hasMore: false, assets: [], trashEnabled: true };

const SHOT_FILTERS = [
  { months: 0, label: "Alle" },
  { months: 6, label: "Älter als 6 Monate" },
  { months: 12, label: "Älter als 1 Jahr" },
  { months: 24, label: "Älter als 2 Jahre" },
];

document.getElementById("photos-subtabs").addEventListener("click", e => {
  const view = e.target.closest("[data-photos-view]")?.dataset.photosView;
  if (!view) return;
  document.querySelectorAll("#photos-subtabs .range-tab").forEach(b =>
    b.classList.toggle("active", b.dataset.photosView === view));
  document.getElementById("photos-view-duplicates").classList.toggle("hidden", view !== "duplicates");
  document.getElementById("photos-view-all").classList.toggle("hidden", view !== "all");
  document.getElementById("photos-view-screenshots").classList.toggle("hidden", view !== "screenshots");
  document.getElementById("photos-view-quality").classList.toggle("hidden", view !== "quality");
  document.getElementById("photos-view-people").classList.toggle("hidden", view !== "people");
  if (view === "screenshots" && !shotState.assets.length) loadScreenshots();
  if (view === "quality" && !qualityState.assets.length) loadQuality();
  if (view === "people" && !peopleCache.length) loadPeople();
  if (view === "all") {
    if (activeSwipeKind !== "all") enterSwipeMode("all");
  } else if (activeSwipeKind === "all") {
    activeSwipeKind = null;
  }
});

async function loadScreenshots(offset = 0) {
  const grid = document.getElementById("shots-grid");
  const summary = document.getElementById("shots-summary");
  grid.innerHTML = `<p class="page-sub">Suche Bildschirmfotos …</p>`;

  let d;
  try {
    d = await api(`/immich/screenshots?older_than_months=${shotState.months}&offset=${offset}&limit=60`);
  } catch (e) {
    grid.innerHTML = `<p class="page-sub">${esc(e.message)}</p>`;
    return;
  }

  shotState = { ...shotState, offset: d.offset, hasMore: d.has_more,
                assets: d.assets, trashEnabled: d.trash_enabled };
  // Auswahl beim Blättern/Filtern verwerfen - sonst würde man Bilder wegwerfen,
  // die man auf einer anderen Seite ausgewählt und längst vergessen hat.
  shotSelection.clear();

  document.getElementById("shot-filter").innerHTML = SHOT_FILTERS.map(f => {
    const n = f.months === 0 ? d.by_age.alle
      : (f.months === 6 ? d.by_age["6m"] : f.months === 12 ? d.by_age["1j"] : d.by_age["2j"]);
    return `<button type="button" class="range-tab ${f.months === shotState.months ? "active" : ""}"
             data-shot-months="${f.months}">${f.label} (${n})</button>`;
  }).join("");

  summary.classList.remove("hidden");
  const mb = (d.total_size_bytes / 1024 / 1024).toFixed(0);
  summary.innerHTML = d.total === 0
    ? `Keine Bildschirmfotos in diesem Zeitraum.`
    : `<strong>${d.total} Bildschirmfotos</strong> (${mb} MB) – angezeigt
       ${d.offset + 1}–${d.offset + d.assets.length}.
       ${d.trash_enabled
         ? `Ausgewählte wandern in Immichs Papierkorb, ${d.trash_days ? `${d.trash_days} Tage lang ` : ""}wiederherstellbar.`
         : `<span class="photos-warn">⚠️ Papierkorb in Immich abgeschaltet – Aufräumen ist gesperrt.</span>`}`;

  renderShots();
}

function renderShots() {
  const grid = document.getElementById("shots-grid");
  if (!shotState.assets.length) { grid.innerHTML = ""; document.getElementById("shots-pager").innerHTML = ""; return; }

  grid.innerHTML = shotState.assets.map(a => {
    const sel = shotSelection.has(a.id);
    return `<button type="button" class="shot-card ${sel ? "is-selected" : ""}" data-shot="${esc(a.id)}">
      <img loading="lazy" src="/api/immich/thumbnail/${esc(a.id)}" alt="">
      <span class="photo-zoom" data-zoom="${esc(a.id)}" data-caption="Bildschirmfoto" title="Vergrößern">🔍</span>
      <span class="shot-check">${sel ? "✓" : ""}</span>
      <span class="shot-meta">
        <span>${a.created_at ? fmtDate(a.created_at.slice(0, 10)) : ""}</span>
        <span>${formatBytes(a.size_bytes)}</span>
      </span>
    </button>`;
  }).join("");

  const selBytes = shotState.assets.filter(a => shotSelection.has(a.id))
    .reduce((s, a) => s + (a.size_bytes || 0), 0);
  const alleGewaehlt = shotSelection.size === shotState.assets.length;

  const pager = [];
  pager.push(`<button type="button" class="btn-ghost" data-shot-all="${alleGewaehlt ? "0" : "1"}">
    ${alleGewaehlt ? "Auswahl aufheben" : `Alle ${shotState.assets.length} auswählen`}</button>`);
  if (shotSelection.size && shotState.trashEnabled) {
    pager.push(`<button type="button" class="btn-primary" data-shot-trash="1">
      ${shotSelection.size} in den Papierkorb (${formatBytes(selBytes)})</button>`);
  }
  if (shotState.offset > 0) pager.push(`<button type="button" class="btn-ghost" data-shot-page="${Math.max(0, shotState.offset - 60)}">← Zurück</button>`);
  if (shotState.hasMore) pager.push(`<button type="button" class="btn-ghost" data-shot-page="${shotState.offset + 60}">Weitere →</button>`);
  document.getElementById("shots-pager").innerHTML = pager.join("");
}

document.getElementById("photos-view-screenshots").addEventListener("click", async e => {
  if (checkZoomClick(e)) return;
  if (e.target.closest("[data-swipe-toggle]")) {
    activeSwipeKind === "shot" ? exitSwipeMode("shot") : enterSwipeMode("shot");
    return;
  }
  if (e.target.closest("[data-swipe-action]")) {
    commitSwipe("shot", e.target.closest("[data-swipe-action]").dataset.swipeAction);
    return;
  }
  const months = e.target.closest("[data-shot-months]")?.dataset.shotMonths;
  if (months !== undefined) {
    shotState.months = parseInt(months, 10);
    await loadScreenshots(0);
    return;
  }
  const page = e.target.closest("[data-shot-page]")?.dataset.shotPage;
  if (page !== undefined) {
    await loadScreenshots(parseInt(page, 10));
    window.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  const card = e.target.closest("[data-shot]");
  if (card) {
    const id = card.dataset.shot;
    shotSelection.has(id) ? shotSelection.delete(id) : shotSelection.add(id);
    renderShots();
    return;
  }
  const all = e.target.closest("[data-shot-all]")?.dataset.shotAll;
  if (all !== undefined) {
    shotSelection.clear();
    if (all === "1") shotState.assets.forEach(a => shotSelection.add(a.id));
    renderShots();
    return;
  }
  if (e.target.closest("[data-shot-trash]")) {
    const ids = [...shotSelection];
    if (!immichSkipConfirm &&
        !confirm(`${ids.length} Bildschirmfoto(s) in den Papierkorb verschieben?\n\nSie bleiben in Immich wiederherstellbar.`)) return;
    try {
      const r = await api("/immich/screenshots/trash", {
        method: "POST", body: JSON.stringify({ asset_ids: ids }),
      });
      toast(`${r.trashed} verschoben, ${formatBytes(r.freed_bytes)} frei.`);
      await loadScreenshots(shotState.offset);
    } catch (err) {
      toast("Fehler: " + err.message);
    }
  }
});

// ---------- Unnötige Fotos (unscharf/leer) ----------
const qualitySelection = new Set();
let qualityState = { reason: "", offset: 0, hasMore: false, assets: [], trashEnabled: true, byReason: {} };

const QUALITY_FILTERS = [
  { reason: "", label: "Alle" },
  { reason: "blur", label: "Unscharf" },
  { reason: "blank", label: "Leer/einfarbig" },
];

async function loadQuality(offset = 0) {
  const grid = document.getElementById("quality-grid");
  const summary = document.getElementById("quality-summary");
  grid.innerHTML = `<p class="page-sub">Lade …</p>`;

  let d;
  try {
    d = await api(`/immich/quality?offset=${offset}&limit=60&reason=${encodeURIComponent(qualityState.reason)}`);
  } catch (e) {
    grid.innerHTML = `<p class="page-sub">${esc(e.message)}</p>`;
    return;
  }

  qualityState = { ...qualityState, offset: d.offset, hasMore: d.has_more,
                    assets: d.assets, trashEnabled: d.trash_enabled, byReason: d.by_reason };
  qualitySelection.clear();

  document.getElementById("quality-filter").innerHTML = QUALITY_FILTERS.map(f => {
    const n = f.reason === "" ? d.total : (d.by_reason[f.reason] || 0);
    return `<button type="button" class="range-tab ${f.reason === qualityState.reason ? "active" : ""}"
             data-quality-reason="${f.reason}">${f.label} (${n})</button>`;
  }).join("");

  summary.classList.remove("hidden");
  const mb = (d.total_size_bytes / 1024 / 1024).toFixed(0);
  summary.innerHTML = d.total === 0
    ? `Bisher keine unnötigen Fotos gefunden. Der Hintergrund-Scan hat die Bibliothek bis
       Seite ${d.scan_page} durchsucht und läuft alle paar Minuten weiter.`
    : `<strong>${d.total} unnötige Fotos</strong> (${mb} MB) – Scan-Fortschritt: Seite ${d.scan_page}.
       ${d.trash_enabled
         ? `Ausgewählte wandern in Immichs Papierkorb, ${d.trash_days ? `${d.trash_days} Tage lang ` : ""}wiederherstellbar.`
         : `<span class="photos-warn">⚠️ Papierkorb in Immich abgeschaltet – Aufräumen ist gesperrt.</span>`}`;

  renderQuality();
}

function renderQuality() {
  const grid = document.getElementById("quality-grid");
  if (!qualityState.assets.length) { grid.innerHTML = ""; document.getElementById("quality-pager").innerHTML = ""; return; }

  grid.innerHTML = qualityState.assets.map(a => {
    const sel = qualitySelection.has(a.id);
    const label = a.reason === "blur" ? "Unscharf" : "Leer";
    return `<button type="button" class="shot-card ${sel ? "is-selected" : ""}" data-quality="${esc(a.id)}">
      <img loading="lazy" src="/api/immich/thumbnail/${esc(a.id)}" alt="">
      ${videoBadgeHtml(a.type)}
      <span class="photo-zoom" data-zoom="${esc(a.id)}" data-caption="${esc(a.file_name || "")}" title="Vergrößern">🔍</span>
      <span class="shot-check">${sel ? "✓" : ""}</span>
      <span class="photo-badge" style="left:auto;right:8px;background:var(--warn)">${label}</span>
      <span class="shot-meta">
        <span>${a.created_at ? fmtDate(a.created_at.slice(0, 10)) : ""}</span>
        <span>${formatBytes(a.size_bytes)}</span>
      </span>
    </button>`;
  }).join("");

  const selBytes = qualityState.assets.filter(a => qualitySelection.has(a.id))
    .reduce((s, a) => s + (a.size_bytes || 0), 0);
  const alleGewaehlt = qualitySelection.size === qualityState.assets.length;

  const pager = [];
  pager.push(`<button type="button" class="btn-ghost" data-quality-all="${alleGewaehlt ? "0" : "1"}">
    ${alleGewaehlt ? "Auswahl aufheben" : `Alle ${qualityState.assets.length} auswählen`}</button>`);
  if (qualitySelection.size) {
    pager.push(`<button type="button" class="btn-ghost" data-quality-dismiss="1">
      ${qualitySelection.size} als okay behalten</button>`);
  }
  if (qualitySelection.size && qualityState.trashEnabled) {
    pager.push(`<button type="button" class="btn-primary" data-quality-trash="1">
      ${qualitySelection.size} in den Papierkorb (${formatBytes(selBytes)})</button>`);
  }
  if (qualityState.offset > 0) pager.push(`<button type="button" class="btn-ghost" data-quality-page="${Math.max(0, qualityState.offset - 60)}">← Zurück</button>`);
  if (qualityState.hasMore) pager.push(`<button type="button" class="btn-ghost" data-quality-page="${qualityState.offset + 60}">Weitere →</button>`);
  document.getElementById("quality-pager").innerHTML = pager.join("");
}

document.getElementById("photos-view-quality").addEventListener("click", async e => {
  if (checkZoomClick(e)) return;
  if (e.target.closest("[data-swipe-toggle]")) {
    activeSwipeKind === "quality" ? exitSwipeMode("quality") : enterSwipeMode("quality");
    return;
  }
  if (e.target.closest("[data-swipe-action]")) {
    commitSwipe("quality", e.target.closest("[data-swipe-action]").dataset.swipeAction);
    return;
  }

  const reason = e.target.closest("[data-quality-reason]")?.dataset.qualityReason;
  if (reason !== undefined) {
    qualityState.reason = reason;
    await loadQuality(0);
    return;
  }
  const page = e.target.closest("[data-quality-page]")?.dataset.qualityPage;
  if (page !== undefined) {
    await loadQuality(parseInt(page, 10));
    window.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  const card = e.target.closest("[data-quality]");
  if (card) {
    const id = card.dataset.quality;
    qualitySelection.has(id) ? qualitySelection.delete(id) : qualitySelection.add(id);
    renderQuality();
    return;
  }
  const all = e.target.closest("[data-quality-all]")?.dataset.qualityAll;
  if (all !== undefined) {
    qualitySelection.clear();
    if (all === "1") qualityState.assets.forEach(a => qualitySelection.add(a.id));
    renderQuality();
    return;
  }
  if (e.target.closest("[data-quality-dismiss]")) {
    const ids = [...qualitySelection];
    try {
      await Promise.all(ids.map(id => api(`/immich/quality/${id}`, { method: "DELETE" })));
      toast(`${ids.length} Foto(s) als okay markiert.`);
      await loadQuality(qualityState.offset);
    } catch (err) {
      toast("Fehler: " + err.message);
    }
    return;
  }
  if (e.target.closest("[data-quality-trash]")) {
    const ids = [...qualitySelection];
    if (!immichSkipConfirm &&
        !confirm(`${ids.length} Foto(s) in den Papierkorb verschieben?\n\nSie bleiben in Immich wiederherstellbar.`)) return;
    try {
      const r = await api("/immich/quality/trash", {
        method: "POST", body: JSON.stringify({ asset_ids: ids }),
      });
      toast(`${r.trashed} verschoben, ${formatBytes(r.freed_bytes)} frei.`);
      await loadQuality(qualityState.offset);
    } catch (err) {
      toast("Fehler: " + err.message);
    }
  }
});

// ---------- Swipe-Modus (Tinder-artig: rechts=behalten, links=Papierkorb) ----------
// Bewusst clientseitig auf der schon geladenen Seite (max. 60 Fotos) statt eigenem
// Backend-Endpunkt - Screenshots/Unnötige Fotos liefern ohnehin nur "Kandidat oder
// nicht", kein Rank-Algorithmus, den man serverseitig fortschreiben müsste.
const ICON_SWIPE = '<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16 3l4 4-4 4"/><path d="M20 7H4"/><path d="M8 21l-4-4 4-4"/><path d="M4 17h16"/></svg>';
const ICON_GRID = '<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="8" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/><rect x="13" y="13" width="8" height="8" rx="1.5"/></svg>';

const SWIPE_CONFIG = {
  shot: {
    containerId: "shot-swipe", gridId: "shots-grid", pagerId: "shots-pager",
    getState: () => shotState,
    loadPage: offset => loadScreenshots(offset),
    trashUrl: "/immich/screenshots/trash",
    keepOne: null, // "behalten" heisst hier nur: nicht anfassen, kein eigener Aufruf noetig
    caption: () => "Bildschirmfoto",
  },
  quality: {
    containerId: "quality-swipe", gridId: "quality-grid", pagerId: "quality-pager",
    getState: () => qualityState,
    loadPage: offset => loadQuality(offset),
    trashUrl: "/immich/quality/trash",
    keepOne: id => api(`/immich/quality/${id}`, { method: "DELETE" }),
    caption: a => (a.reason === "blur" ? "Unscharf" : "Leer/einfarbig"),
  },
  // Kein Grid/Pager - dieser Tab zeigt ausschliesslich den Swipe-Stack, ohne
  // Umschalt-Button (siehe photos-subtabs-Handler, der enterSwipeMode direkt
  // beim Reinklicken in den Tab aufruft statt erst auf einen Klick zu warten).
  all: {
    containerId: "all-swipe", gridId: null, pagerId: null,
    getState: () => allPhotosState,
    loadPage: offset => loadAllPhotos(offset),
    trashUrl: "/immich/photos/trash",
    keepOne: null,
    caption: () => "",
  },
};

let activeSwipeKind = null;
const swipeQueues = { shot: [], quality: [], all: [] };

function enterSwipeMode(kind) {
  activeSwipeKind = kind;
  const cfg = SWIPE_CONFIG[kind];
  swipeQueues[kind] = [...cfg.getState().assets];
  document.getElementById(cfg.gridId)?.classList.add("hidden");
  document.getElementById(cfg.pagerId)?.classList.add("hidden");
  document.getElementById(cfg.containerId).classList.remove("hidden");
  const toggleBtn = document.querySelector(`[data-swipe-toggle="${kind}"]`);
  if (toggleBtn) toggleBtn.innerHTML = ICON_GRID + " Rasteransicht";
  renderSwipeStack(kind);
}

function exitSwipeMode(kind) {
  activeSwipeKind = null;
  const cfg = SWIPE_CONFIG[kind];
  document.getElementById(cfg.gridId)?.classList.remove("hidden");
  document.getElementById(cfg.pagerId)?.classList.remove("hidden");
  document.getElementById(cfg.containerId).classList.add("hidden");
  const toggleBtn = document.querySelector(`[data-swipe-toggle="${kind}"]`);
  if (toggleBtn) toggleBtn.innerHTML = ICON_SWIPE + " Swipe-Modus";
}

function renderSwipeStack(kind) {
  const cfg = SWIPE_CONFIG[kind];
  const container = document.getElementById(cfg.containerId);
  const queue = swipeQueues[kind];

  if (!queue.length) {
    const st = cfg.getState();
    if (st.hasMore) {
      container.innerHTML = `<p class="swipe-done">Lade weitere …</p>`;
      cfg.loadPage(st.offset + 60).then(() => {
        if (activeSwipeKind !== kind) return;
        swipeQueues[kind] = [...cfg.getState().assets];
        renderSwipeStack(kind);
      });
      return;
    }
    container.innerHTML = `<p class="swipe-done">🎉 Alles durchgesehen.</p>`;
    return;
  }

  const top = queue[0];
  const next = queue[1];
  container.innerHTML = `
    <div class="swipe-progress">${queue.length} übrig</div>
    <div class="swipe-stack">
      ${next ? `<div class="swipe-card is-behind"><img src="/api/immich/thumbnail/${esc(next.id)}" alt="">${videoBadgeHtml(next.type)}</div>` : ""}
      <div class="swipe-card is-top" id="swipe-top-card" data-swipe-id="${esc(top.id)}">
        <span class="swipe-hint keep">Behalten</span>
        <span class="swipe-hint trash">Papierkorb</span>
        <img src="/api/immich/thumbnail/${esc(top.id)}" alt="" draggable="false">
        ${videoBadgeHtml(top.type)}
        <div class="swipe-card-meta">
          <span>${top.created_at ? fmtDate(top.created_at.slice(0, 10)) : ""}</span>
          <span>${cfg.caption(top)} · ${formatBytes(top.size_bytes)}</span>
        </div>
      </div>
    </div>
    <div class="swipe-actions">
      <button type="button" class="swipe-action-btn trash" data-swipe-action="trash" title="In den Papierkorb">✕</button>
      <button type="button" class="swipe-action-btn keep" data-swipe-action="keep" title="Behalten">✓</button>
    </div>`;

  attachSwipeDrag(kind);
}

function attachSwipeDrag(kind) {
  const card = document.getElementById("swipe-top-card");
  if (!card) return;
  const keepHint = card.querySelector(".swipe-hint.keep");
  const trashHint = card.querySelector(".swipe-hint.trash");
  let startX = 0, dx = 0, dragging = false;

  card.addEventListener("pointerdown", e => {
    dragging = true;
    dx = 0;
    card.classList.add("is-dragging");
    startX = e.clientX;
    card.setPointerCapture(e.pointerId);
  });
  card.addEventListener("pointermove", e => {
    if (!dragging) return;
    dx = e.clientX - startX;
    card.style.transform = `translateX(${dx}px) rotate(${dx / 18}deg)`;
    const strength = Math.min(Math.abs(dx) / 100, 1);
    keepHint.style.opacity = dx > 0 ? strength : 0;
    trashHint.style.opacity = dx < 0 ? strength : 0;
  });
  const release = () => {
    if (!dragging) return;
    dragging = false;
    card.classList.remove("is-dragging");
    if (Math.abs(dx) > 100) {
      commitSwipe(kind, dx > 0 ? "keep" : "trash");
    } else {
      card.classList.add("snap-back");
      card.style.transform = "";
      keepHint.style.opacity = 0;
      trashHint.style.opacity = 0;
    }
  };
  card.addEventListener("pointerup", release);
  card.addEventListener("pointercancel", release);
}

async function commitSwipe(kind, direction) {
  const cfg = SWIPE_CONFIG[kind];
  const card = document.getElementById("swipe-top-card");
  const id = card?.dataset.swipeId;
  if (!id) return;
  const flyX = direction === "keep" ? 700 : -700;
  card.classList.add("fly-out");
  card.style.transform = `translateX(${flyX}px) rotate(${direction === "keep" ? 20 : -20}deg)`;

  swipeQueues[kind].shift();
  setTimeout(() => { if (activeSwipeKind === kind) renderSwipeStack(kind); }, 220);

  try {
    if (direction === "trash") {
      await api(cfg.trashUrl, { method: "POST", body: JSON.stringify({ asset_ids: [id] }) });
    } else if (cfg.keepOne) {
      await cfg.keepOne(id);
    }
  } catch (err) {
    toast("Fehler: " + err.message);
  }
}

// ---------- Personen (Immichs Gesichtserkennung) ----------
let peopleCache = [];
let personSelection = new Set();
let personState = { id: null, name: "", page: 1, hasMore: false, assets: [], trashEnabled: true };

async function loadPeople() {
  const grid = document.getElementById("people-grid");
  grid.innerHTML = `<p class="page-sub">Lade Personen …</p>`;
  try {
    const d = await api("/immich/people");
    peopleCache = d.people;
  } catch (e) {
    grid.innerHTML = `<p class="page-sub">${esc(e.message)}</p>`;
    return;
  }
  if (!peopleCache.length) {
    grid.innerHTML = `<p class="page-sub">Immich hat noch keine benannten Personen erkannt.</p>`;
    return;
  }
  grid.innerHTML = peopleCache.map(p => `
    <button type="button" class="shot-card" data-person="${esc(p.id)}">
      <img loading="lazy" src="/api/immich/people/${esc(p.id)}/thumbnail" alt="">
      <span class="shot-meta">
        <span>${esc(p.name)}</span>
        <span>${p.asset_count} Fotos</span>
      </span>
    </button>`).join("");
}

async function loadPersonAssets(page = 1) {
  const grid = document.getElementById("person-grid");
  const summary = document.getElementById("person-summary");
  grid.innerHTML = `<p class="page-sub">Lade Fotos …</p>`;

  let d;
  try {
    d = await api(`/immich/people/${personState.id}/assets?page=${page}`);
  } catch (e) {
    grid.innerHTML = `<p class="page-sub">${esc(e.message)}</p>`;
    return;
  }
  personState = { ...personState, page: d.page, hasMore: d.has_more, assets: d.assets, trashEnabled: d.trash_enabled };
  personSelection.clear();
  summary.classList.remove("hidden");
  summary.innerHTML = `Seite ${d.page}.
    ${d.trash_enabled
      ? `Ausgewählte wandern in Immichs Papierkorb, wiederherstellbar.`
      : `<span class="photos-warn">⚠️ Papierkorb in Immich abgeschaltet – Aufräumen ist gesperrt.</span>`}`;
  renderPersonAssets();
}

function renderPersonAssets() {
  const grid = document.getElementById("person-grid");
  if (!personState.assets.length) { grid.innerHTML = `<p class="page-sub">Keine Fotos auf dieser Seite.</p>`; document.getElementById("person-pager").innerHTML = ""; return; }

  grid.innerHTML = personState.assets.map(a => {
    const sel = personSelection.has(a.id);
    return `<button type="button" class="shot-card ${sel ? "is-selected" : ""}" data-person-asset="${esc(a.id)}">
      <img loading="lazy" src="/api/immich/thumbnail/${esc(a.id)}" alt="">
      <span class="photo-zoom" data-zoom="${esc(a.id)}" data-caption="${esc(a.file_name || "")}" title="Vergrößern">🔍</span>
      <span class="shot-check">${sel ? "✓" : ""}</span>
      <span class="shot-meta">
        <span>${a.created_at ? fmtDate(a.created_at.slice(0, 10)) : ""}</span>
        <span>${formatBytes(a.size_bytes)}</span>
      </span>
    </button>`;
  }).join("");

  const pager = [];
  if (personSelection.size && personState.trashEnabled) {
    pager.push(`<button type="button" class="btn-primary" data-person-trash="1">
      ${personSelection.size} in den Papierkorb</button>`);
  }
  if (personState.page > 1) pager.push(`<button type="button" class="btn-ghost" data-person-page="${personState.page - 1}">← Zurück</button>`);
  if (personState.hasMore) pager.push(`<button type="button" class="btn-ghost" data-person-page="${personState.page + 1}">Weitere →</button>`);
  document.getElementById("person-pager").innerHTML = pager.join("");
}

document.getElementById("photos-view-people").addEventListener("click", async e => {
  if (checkZoomClick(e)) return;

  const personId = e.target.closest("[data-person]")?.dataset.person;
  if (personId) {
    const person = peopleCache.find(p => p.id === personId);
    personState = { id: personId, name: person?.name || "", page: 1, hasMore: false, assets: [], trashEnabled: true };
    document.getElementById("person-detail-title").textContent = `🙂 ${person?.name || ""}`;
    document.getElementById("person-detail").classList.remove("hidden");
    document.getElementById("people-grid").classList.add("hidden");
    await loadPersonAssets(1);
    return;
  }
  if (e.target.closest("#person-back")) {
    document.getElementById("person-detail").classList.add("hidden");
    document.getElementById("people-grid").classList.remove("hidden");
    return;
  }
  const page = e.target.closest("[data-person-page]")?.dataset.personPage;
  if (page !== undefined) {
    await loadPersonAssets(parseInt(page, 10));
    window.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  const card = e.target.closest("[data-person-asset]");
  if (card) {
    const id = card.dataset.personAsset;
    personSelection.has(id) ? personSelection.delete(id) : personSelection.add(id);
    renderPersonAssets();
    return;
  }
  if (e.target.closest("[data-person-trash]")) {
    const ids = [...personSelection];
    if (!immichSkipConfirm &&
        !confirm(`${ids.length} Foto(s) in den Papierkorb verschieben?\n\nSie bleiben in Immich wiederherstellbar.`)) return;
    try {
      const r = await api(`/immich/people/${personState.id}/trash`, {
        method: "POST", body: JSON.stringify({ asset_ids: ids }),
      });
      toast(`${r.trashed} verschoben, ${formatBytes(r.freed_bytes)} frei.`);
      await loadPersonAssets(personState.page);
    } catch (err) {
      toast("Fehler: " + err.message);
    }
  }
});

// ================= BELEGE AUS E-MAILS =================
async function loadMailSettings() {
  const s = await api("/settings/mail");
  document.getElementById("mail-host").value = s.host || "";
  document.getElementById("mail-port").value = s.port || 993;
  document.getElementById("mail-user").value = s.user || "";
  document.getElementById("mail-folder").value = s.folder || "INBOX";
  document.getElementById("mail-enabled").checked = s.enabled;
  document.getElementById("mail-remove").classList.toggle("hidden", !s.host);
  document.getElementById("mail-password").placeholder = s.password_set
    ? "gespeichert – leer lassen behält das bisherige"
    : "wird verschlüsselt gespeichert";
  if (s.last_sync_at) {
    document.getElementById("mail-status").textContent =
      "Zuletzt abgeholt: " + relativeTimeDe(new Date(s.last_sync_at));
  }
}

document.getElementById("mail-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const pw = document.getElementById("mail-password").value.trim();
  const body = {
    enabled: document.getElementById("mail-enabled").checked,
    host: document.getElementById("mail-host").value.trim(),
    port: parseInt(document.getElementById("mail-port").value, 10) || 993,
    user: document.getElementById("mail-user").value.trim(),
    folder: document.getElementById("mail-folder").value.trim() || "INBOX",
  };
  if (pw) body.password = pw;
  await api("/settings/mail", { method: "PUT", body: JSON.stringify(body) });
  document.getElementById("mail-password").value = "";
  toast("Postfach-Einstellungen gespeichert.");
  await loadMailSettings();
  refreshIntegrationBadge();
});

document.getElementById("mail-test").addEventListener("click", async () => {
  const el = document.getElementById("mail-status");
  el.textContent = "Teste Verbindung …";
  const r = await api("/mail/test", { method: "POST" });
  el.textContent = r.ok
    ? `✓ Verbunden – Ordner „${r.folder}" mit ${r.message_count} Nachrichten.`
    : `✗ ${r.error}`;
});

document.getElementById("mail-sync-now").addEventListener("click", async () => {
  const el = document.getElementById("mail-status");
  el.textContent = "Hole Anhänge … (kann bei vielen Mails dauern)";
  try {
    const r = await api("/mail/sync", { method: "POST" });
    el.textContent = `${r.new_attachments} neue Anhänge, davon ${r.auto_attached} automatisch zugeordnet. ${r.skipped} schon bekannt.`;
    toast(`${r.new_attachments} neue Belege geholt.`);
    await loadMailInbox();
  } catch (err) {
    el.textContent = "✗ " + err.message;
  }
});

document.getElementById("mail-remove").addEventListener("click", async () => {
  if (!confirm("Postfach-Verbindung entfernen?")) return;
  await api("/settings/mail", { method: "DELETE" });
  toast("Postfach-Verbindung entfernt.");
  await loadMailSettings();
  refreshIntegrationBadge();
});

async function loadCreditCardSettings() {
  if (!accountsCache.length) accountsCache = await api("/accounts");
  if (!debtsCache.length) debtsCache = await api("/debts");
  const select = document.getElementById("creditcard-account-select");
  select.innerHTML = '<option value="">– auswählen –</option>' +
    accountsCache.map(a => `<option value="acc:${a.id}">${esc(a.name)} (Konto)</option>`).join("") +
    debtsCache.map(d => `<option value="debt:${d.id}">${esc(d.name)} (Schuld)</option>`).join("");
  const s = await api("/settings/creditcard");
  document.getElementById("creditcard-mail-sender").value = s.mail_sender || "";
  select.value = s.account_id ? `acc:${s.account_id}` : s.debt_id ? `debt:${s.debt_id}` : "";
}

document.getElementById("creditcard-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const sel = document.getElementById("creditcard-account-select").value;
  const [kind, id] = sel ? sel.split(":") : [null, null];
  const body = {
    mail_sender: document.getElementById("creditcard-mail-sender").value.trim(),
    account_id: kind === "acc" ? parseInt(id, 10) : null,
    debt_id: kind === "debt" ? parseInt(id, 10) : null,
  };
  await api("/settings/creditcard", { method: "PUT", body: JSON.stringify(body) });
  toast("Kreditkarten-Einstellungen gespeichert.");
});

// ---------- Beleg-Eingang ----------
async function loadDuplicateTransactions() {
  const panel = document.getElementById("dup-tx-panel");
  let groups = [];
  try {
    groups = await api("/transactions/duplicates");
  } catch (e) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.toggle("hidden", groups.length === 0);
  document.getElementById("dup-tx-count").textContent = groups.length;
  if (!groups.length) return;

  document.getElementById("dup-tx-list").innerHTML = groups.map((g, i) => `
    <div class="mail-item">
      <div>
        <strong>${g.transaction_ids.length}× ${esc(g.description || "(ohne Beschreibung)")}</strong><br>
        <span class="page-sub">${esc(g.account_name)} · ${fmtDate(g.date)} · ${eur(g.amount)}</span>
      </div>
      <button type="button" class="btn-ghost" data-dup-resolve="${i}">
        ${g.transaction_ids.length - 1} überzählige löschen (behält eine)
      </button>
    </div>`).join("");

  document.querySelectorAll("[data-dup-resolve]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const g = groups[parseInt(btn.dataset.dupResolve, 10)];
      const toDelete = g.transaction_ids.slice(1);
      if (!confirm(`${toDelete.length} doppelte Buchung(en) löschen? Die erste bleibt erhalten.`)) return;
      btn.disabled = true;
      for (const id of toDelete) {
        try { await api(`/transactions/${id}`, { method: "DELETE" }); } catch { /* einzelne fehlgeschlagene Loeschung nicht die ganze Aktion abbrechen lassen */ }
      }
      toast(`${toDelete.length} doppelte Buchung(en) gelöscht.`);
      await loadDuplicateTransactions();
      await loadTransactions();
    });
  });
}

async function loadMailInbox() {
  const panel = document.getElementById("mail-inbox-panel");
  const list = document.getElementById("mail-inbox-list");
  let items = [];
  try {
    items = await api("/mail/attachments?status=pending");
  } catch (e) {
    panel.classList.add("hidden");
    return;
  }
  // Panel nur zeigen, wenn wirklich etwas offen ist - sonst nimmt es im
  // Buchungen-Tab dauerhaft Platz weg.
  panel.classList.toggle("hidden", items.length === 0);
  document.getElementById("mail-inbox-count").textContent = items.length;
  if (!items.length) return;

  // Absicherung gegen den seltenen Fall, dass der Beleg-Eingang gerendert
  // wird, bevor die Start-Ladung von Konten/Kategorien durch ist - sonst
  // stünden leere Auswahlfelder im "neue Buchung"-Formular.
  if (!accountsCache.length) accountsCache = await api("/accounts");
  if (!categoriesCache.length) categoriesCache = await api("/categories");

  const kontoOptions = accountsCache.map(k => `<option value="${k.id}">${esc(k.name)}</option>`).join("");
  const katOptions = categoriesCache.map(k => `<option value="${k.id}">${esc(k.name)}</option>`).join("");

  list.innerHTML = items.map(a => {
    const erkannt = a.parsed_date && a.parsed_amount
      ? `erkannt: ${fmtDate(a.parsed_date)} · ${eur(a.parsed_amount)}`
      : `<span class="mail-warn">nicht auslesbar${a.parse_error ? ` (${esc(a.parse_error)})` : ""}</span>`;
    const vorschlaege = a.suggestions.length
      ? a.suggestions.map(s => `<button type="button" class="btn-primary mail-suggest"
           data-attach="${a.id}" data-tx="${s.id}">An ${fmtDate(s.date)} · ${eur(s.amount)} anhängen</button>`).join("")
      : "";
    // Kein Treffer heisst nicht zwangsläufig "es gibt keine Buchung" - der
    // Kontoumsatz kann einfach noch nicht importiert sein. Dafür direkt hier
    // eine neue Buchung anlegen können, statt den Beleg erst wegzulegen und
    // später wiederzufinden.
    const neueBuchung = `
      <details class="mail-new-tx">
        <summary class="btn-ghost">${a.suggestions.length ? "Stattdessen neue Buchung" : "Keine passende Buchung – neu anlegen"}</summary>
        <form class="form-grid mail-new-tx-form" data-new-tx="${a.id}">
          <label>Datum <input type="date" name="date" value="${esc(a.parsed_date || "")}" required></label>
          <label>Betrag <input type="number" step="0.01" name="amount" value="${a.parsed_amount ?? ""}" required></label>
          <label>Konto <select name="account_id" required>${kontoOptions}</select></label>
          <label>Kategorie <select name="category_id"><option value="">–</option>${katOptions}</select></label>
          <label class="wide">Beschreibung <input type="text" name="description" value="${esc(a.subject || a.filename)}"></label>
          <div class="form-actions"><button type="submit" class="btn-primary">Buchung anlegen &amp; Beleg anhängen</button></div>
        </form>
      </details>`;
    return `<div class="mail-item">
      <div class="mail-item-main">
        <a href="/api/receipts/${esc(a.stored_filename)}" target="_blank" rel="noopener" class="mail-file">${esc(a.filename)}</a>
        <span class="mail-meta">${esc(a.sender || "")} · ${esc(a.subject || "")}</span>
        <span class="mail-meta">${erkannt}</span>
        ${neueBuchung}
      </div>
      <div class="mail-item-actions">
        ${vorschlaege}
        <button type="button" class="btn-ghost" data-ignore="${a.id}">Ablegen</button>
      </div>
    </div>`;
  }).join("");
}

document.getElementById("mail-inbox-list").addEventListener("submit", async e => {
  const form = e.target.closest("[data-new-tx]");
  if (!form) return;
  e.preventDefault();
  const fd = new FormData(form);
  const body = {
    account_id: parseInt(fd.get("account_id"), 10),
    category_id: fd.get("category_id") ? parseInt(fd.get("category_id"), 10) : null,
    date: fd.get("date"),
    amount: parseFloat(fd.get("amount")),
    description: fd.get("description") || null,
  };
  try {
    await api(`/mail/attachments/${form.dataset.newTx}/create-transaction`, {
      method: "POST", body: JSON.stringify(body),
    });
    toast("Buchung angelegt, Beleg angehängt.");
    await loadMailInbox();
    await loadTransactions();
  } catch (err) {
    toast("Fehler: " + err.message);
  }
});

document.getElementById("mail-inbox-list").addEventListener("click", async e => {
  const attach = e.target.closest("[data-attach]");
  if (attach) {
    await api(`/mail/attachments/${attach.dataset.attach}/attach`, {
      method: "POST", body: JSON.stringify({ transaction_id: parseInt(attach.dataset.tx, 10) }),
    });
    toast("Beleg an Buchung angehängt.");
    await loadMailInbox();
    await loadTransactions();
    return;
  }
  const ign = e.target.closest("[data-ignore]");
  if (ign) {
    await api(`/mail/attachments/${ign.dataset.ignore}/ignore`, { method: "POST" });
    toast("Beleg abgelegt.");
    await loadMailInbox();
  }
});

// ---------- Immich-Einstellungen ----------
// Global gemerkt, damit die Papierkorb-Handler im Fotos-Tab nicht bei jedem
// Klick erst die Einstellungen nachladen müssen.
let immichSkipConfirm = false;

async function loadImmichSettings() {
  const s = await api("/settings/immich");
  document.getElementById("immich-url").value = s.url || "";
  document.getElementById("immich-remove").classList.toggle("hidden", !s.url && !s.api_key_set);
  document.getElementById("immich-api-key").placeholder = s.api_key_set
    ? "gespeichert – leer lassen behält den bisherigen"
    : "wird verschlüsselt gespeichert";
  document.getElementById("immich-skip-confirm").checked = s.skip_confirm;
  immichSkipConfirm = s.skip_confirm;
}

document.getElementById("immich-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const url = document.getElementById("immich-url").value.trim();
  if (!url) return;
  const keyInput = document.getElementById("immich-api-key");
  const body = { url, skip_confirm: document.getElementById("immich-skip-confirm").checked };
  if (keyInput.value.trim()) body.api_key = keyInput.value.trim();
  await api("/settings/immich", { method: "PUT", body: JSON.stringify(body) });
  keyInput.value = "";
  toast("Immich-Einstellungen gespeichert.");
  await loadImmichSettings();
  refreshIntegrationBadge();
});

document.getElementById("immich-test").addEventListener("click", async () => {
  const statusEl = document.getElementById("immich-status");
  statusEl.textContent = "Teste Verbindung …";
  const r = await api("/immich/test", { method: "POST" });
  statusEl.textContent = r.ok
    ? `✓ Verbunden mit Immich ${r.version} – ${r.duplicate_groups} Duplikatgruppe(n) gefunden.`
    : `✗ ${r.error}`;
});

document.getElementById("immich-remove").addEventListener("click", async () => {
  if (!confirm("Immich-Verbindung entfernen?")) return;
  await api("/settings/immich", { method: "DELETE" });
  document.getElementById("immich-status").textContent = "";
  toast("Immich-Verbindung entfernt.");
  await loadImmichSettings();
  refreshIntegrationBadge();
});

// ================= EINGEHENDER WEBHOOK (n8n) =================
async function loadWebhookSettings() {
  const s = await api("/settings/webhook");
  document.getElementById("webhook-secret").value = s.secret || "";
  document.getElementById("webhook-secret").placeholder = s.configured ? "" : "Noch kein Secret erzeugt";
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
  document.getElementById("native-sync-secret").value = s.secret || "";
  document.getElementById("native-sync-secret").placeholder = s.configured ? "" : "Noch kein Secret erzeugt";
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

// ================= VERMÖGENSVERGLEICH =================
let benchmarkChart = null;

async function loadBenchmark() {
  const data = await api("/benchmark");
  const box = document.getElementById("benchmark-result");
  const hint = document.getElementById("benchmark-hint");

  document.getElementById("profile-birth-year").value = data.birth_year ?? "";

  if (!data.configured) {
    box.classList.add("hidden");
    hint.classList.remove("hidden");
    return;
  }
  box.classList.remove("hidden");
  hint.classList.add("hidden");

  const own = data.brackets.find(b => b.is_own);
  // Bei Werten ausserhalb der belegten Marken ist nur die Grenze bekannt -
  // dann keine Scheingenauigkeit vortäuschen.
  const pctText = data.percentile_exact
    ? `rund ${Math.round(data.percentile)} %`
    : (data.percentile >= 90 ? "über 90 %" : "unter 10 %");

  document.getElementById("benchmark-headline").innerHTML =
    `Mit ${data.age} Jahren gehörst du zur Gruppe <strong>${esc(own.label)}</strong>.
     Dein Nettovermögen von <strong>${eur(data.net_worth)}</strong> liegt über dem von
     <strong>${pctText}</strong> der Haushalte dieser Gruppe.<br>
     <span class="benchmark-verdict">${esc(data.verdict)}</span>`;

  // Skala der eigenen Gruppe: die drei belegten Marken plus die eigene Lage.
  document.getElementById("benchmark-scale").innerHTML = `
    <div class="benchmark-marks">
      <div><span class="benchmark-mark-label">Untere 10 %</span><span>${eur(own.p10)}</span></div>
      <div><span class="benchmark-mark-label">Median (50 %)</span><span>${eur(own.p50)}</span></div>
      <div><span class="benchmark-mark-label">Obere 10 % ab</span><span>${eur(own.p90)}</span></div>
    </div>`;

  const labels = data.brackets.map(b => b.label);
  const medians = data.brackets.map(b => toDisplay(b.p50));
  const eigen = data.brackets.map(() => toDisplay(data.net_worth));

  if (benchmarkChart) benchmarkChart.destroy();
  benchmarkChart = new Chart(document.getElementById("benchmark-chart"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: `Median der Altersgruppe (${data.data_year})`,
          data: medians,
          // Die eigene Gruppe hervorheben, die anderen zurücknehmen.
          backgroundColor: data.brackets.map(b =>
            b.is_own ? cssVar("--accent-strong") : cssVar("--border-strong")),
          borderRadius: 6,
        },
        {
          label: "Dein Nettovermögen",
          data: eigen,
          type: "line",
          borderColor: cssVar("--pos"),
          borderWidth: 2,
          borderDash: [6, 4],
          pointRadius: 0,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: cssVar("--text-secondary") } },
        tooltip: { callbacks: { label: c => `${c.dataset.label}: ${eur(c.raw / displayRate)}` } },
      },
      scales: {
        x: { ticks: { color: cssVar("--muted") }, grid: { display: false } },
        y: {
          ticks: { color: cssVar("--muted"), callback: v => eur(v / displayRate) },
          grid: { color: cssVar("--border") },
        },
      },
    },
  });

  document.getElementById("benchmark-note").innerHTML =
    `Quelle: ${esc(data.source)} (Stand ${data.data_year}).
     <a href="${esc(data.source_url)}" target="_blank" rel="noopener">Zur Studie</a>.
     Verglichen werden <strong>Haushalts</strong>vermögen, zugeordnet nach dem Alter der ältesten
     Person im Haushalt – bei einem Paarhaushalt steht dort also das Vermögen von zwei Personen.
     Enthalten sind dort auch Immobilien, Fahrzeuge und Betriebsvermögen: Was du hier in der App
     nicht erfasst hast, fehlt auf deiner Seite des Vergleichs.`;
}

document.getElementById("birth-year-form").addEventListener("submit", async e => {
  e.preventDefault();
  const raw = document.getElementById("profile-birth-year").value;
  const birth_year = raw === "" ? null : parseInt(raw, 10);
  await api("/settings/birth-year", { method: "PUT", body: JSON.stringify({ birth_year }) });
  toast("Geburtsjahr gespeichert.");
  await loadBenchmark();
});

// ================= SETTINGS: BUDGETS =================
function populateBudgetCategorySelect() {
  const sel = document.getElementById("budget-category");
  sel.innerHTML = "";
  categoriesCache.filter(c => c.type === "ausgabe").forEach(c => {
    const opt = document.createElement("option");
    opt.value = c.id; opt.textContent = c.name;
    sel.appendChild(opt);
  });
}

async function loadBudgets() {
  if (!categoriesCache.length) await loadCategories();
  populateBudgetCategorySelect();
  const budgets = await api("/budgets");
  const tbody = document.getElementById("budget-list");
  tbody.innerHTML = "";
  if (budgets.length === 0) {
    tbody.innerHTML = emptyRow(3, "target", "Noch keine Budgets festgelegt.");
  }
  budgets.forEach(b => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${b.category_name}</td><td>${eur(b.monthly_limit)}</td>
      <td><button class="link-btn" onclick="deleteBudget(${b.category_id})">Löschen</button></td>`;
    tbody.appendChild(tr);
  });
  loadBudgetSuggestions();
}

async function loadBudgetSuggestions() {
  const wrap = document.getElementById("budget-suggestions-wrap");
  let suggestions = [];
  try {
    suggestions = await api("/budgets/suggestions");
  } catch (e) {
    wrap.classList.add("hidden");
    return;
  }
  wrap.classList.toggle("hidden", suggestions.length === 0);
  if (!suggestions.length) return;
  document.getElementById("budget-suggestions-list").innerHTML = suggestions.map(s => `
    <tr>
      <td>${esc(s.category_name)}</td>
      <td>${eur(s.avg_monthly_spend)}</td>
      <td>${eur(s.suggested_limit)}</td>
      <td><button type="button" class="link-btn" data-apply-budget="${s.category_id}" data-apply-limit="${s.suggested_limit}">Übernehmen</button></td>
    </tr>`).join("");
  document.querySelectorAll("[data-apply-budget]").forEach(btn => {
    btn.addEventListener("click", async () => {
      await api("/budgets", {
        method: "POST",
        body: JSON.stringify({
          category_id: parseInt(btn.dataset.applyBudget, 10),
          monthly_limit: parseFloat(btn.dataset.applyLimit),
        }),
      });
      toast("Budget übernommen.");
      loadBudgets();
    });
  });
}

document.getElementById("budget-form").addEventListener("submit", async e => {
  e.preventDefault();
  const category_id = parseInt(document.getElementById("budget-category").value);
  const monthly_limit = parseFloat(document.getElementById("budget-limit").value);
  await api("/budgets", { method: "POST", body: JSON.stringify({ category_id, monthly_limit }) });
  document.getElementById("budget-form").reset();
  loadBudgets();
});

window.deleteBudget = async categoryId => {
  if (!confirm("Budget wirklich löschen?")) return;
  await api(`/budgets/${categoryId}`, { method: "DELETE" });
  loadBudgets();
};

// ================= SETTINGS: EXPORT / IMPORT / BACKUP =================
document.getElementById("export-csv-btn").addEventListener("click", () => {
  window.location.href = API + "/export/transactions.csv";
});

document.getElementById("import-csv-btn").addEventListener("click", async () => {
  const fileInput = document.getElementById("import-csv-file");
  const resultEl = document.getElementById("import-result");
  if (!fileInput.files.length) {
    resultEl.textContent = "Bitte zuerst eine CSV-Datei auswählen.";
    return;
  }
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  const result = await api("/import/transactions", { method: "POST", body: fd });
  resultEl.textContent = `${result.imported} importiert, ${result.skipped} übersprungen.`
    + (result.errors.length ? "\n" + result.errors.join("\n") : "");
  fileInput.value = "";
  loadTransactions();
  loadAccounts();
});

document.getElementById("export-holdings-csv-btn").addEventListener("click", () => {
  window.location.href = API + "/export/holdings.csv";
});

async function loadTaxExportFilters() {
  if (!accountsCache.length) await loadAccounts();
  if (!categoriesCache.length) await loadCategories();
  document.getElementById("tax-export-account").innerHTML = '<option value="">Alle</option>' +
    accountsCache.map(a => `<option value="${a.id}">${esc(a.name)}</option>`).join("");
  document.getElementById("tax-export-category").innerHTML = '<option value="">Alle</option>' +
    categoriesCache.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
}

function taxExportQuery() {
  const params = new URLSearchParams();
  const from = document.getElementById("tax-export-from").value;
  const to = document.getElementById("tax-export-to").value;
  const account = document.getElementById("tax-export-account").value;
  const category = document.getElementById("tax-export-category").value;
  const business = document.getElementById("tax-export-business").value;
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  if (account) params.set("account_id", account);
  if (category) params.set("category_id", category);
  if (business) params.set("is_business", business);
  return params.toString();
}

document.getElementById("tax-export-csv-btn").addEventListener("click", () => {
  window.location.href = `${API}/export/tax.csv?${taxExportQuery()}`;
});
document.getElementById("tax-export-pdf-btn").addEventListener("click", () => {
  window.location.href = `${API}/export/tax.pdf?${taxExportQuery()}`;
});

document.getElementById("import-holdings-csv-btn").addEventListener("click", async () => {
  const fileInput = document.getElementById("import-holdings-csv-file");
  const resultEl = document.getElementById("import-holdings-result");
  if (!fileInput.files.length) {
    resultEl.textContent = "Bitte zuerst eine CSV-Datei auswählen.";
    return;
  }
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  const result = await api("/import/holdings", { method: "POST", body: fd });
  resultEl.textContent = `${result.created} neue Position(en), ${result.added_lots} zusätzliche(r) Kauf(e), ${result.skipped} übersprungen.`
    + (result.errors.length ? "\n" + result.errors.join("\n") : "");
  fileInput.value = "";
  await loadInvestmentsTab();
});

// ================= SETTINGS: AUTOMATISCHE BACKUPS =================
function fmtBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

async function loadBackupSettings() {
  const sel = document.getElementById("backup-hour");
  if (!sel.options.length) {
    for (let h = 0; h < 24; h++) {
      const opt = document.createElement("option");
      opt.value = h;
      opt.textContent = `${String(h).padStart(2, "0")}:00 Uhr`;
      sel.appendChild(opt);
    }
  }
  const s = await api("/settings/backup");
  document.getElementById("backup-enabled").checked = s.enabled;
  sel.value = s.hour;
  document.getElementById("backup-retention").value = s.retention;
}

async function loadBackupsList() {
  const backups = await api("/backups");
  const tbody = document.getElementById("backup-list");
  tbody.innerHTML = "";
  if (backups.length === 0) {
    tbody.innerHTML = emptyRow(3, "database", "Noch kein automatisches Backup erstellt.");
  }
  backups.forEach(b => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${new Date(b.created_at).toLocaleString("de-DE")}</td>
      <td>${fmtBytes(b.size_bytes)}</td>
      <td>
        <a class="link-btn" href="${API}/backups/${encodeURIComponent(b.filename)}">Herunterladen</a>
        <button class="link-btn" onclick="deleteBackupFile('${b.filename}')">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });
}

document.getElementById("backup-schedule-form").addEventListener("submit", async e => {
  e.preventDefault();
  const payload = {
    enabled: document.getElementById("backup-enabled").checked,
    hour: parseInt(document.getElementById("backup-hour").value),
    retention: parseInt(document.getElementById("backup-retention").value),
  };
  await api("/settings/backup", { method: "PUT", body: JSON.stringify(payload) });
  toast(payload.enabled
    ? `Gespeichert – Backup täglich um ${String(payload.hour).padStart(2, "0")}:00 Uhr, ${payload.retention} Stück werden aufbewahrt.`
    : "Gespeichert – automatische Backups sind ausgeschaltet.");
});

document.getElementById("backup-run-now").addEventListener("click", async () => {
  await api("/backups/run", { method: "POST" });
  await loadBackupsList();
});

window.deleteBackupFile = async filename => {
  if (!confirm("Dieses Backup wirklich löschen?")) return;
  await api(`/backups/${encodeURIComponent(filename)}`, { method: "DELETE" });
  await loadBackupsList();
};

document.getElementById("backup-btn").addEventListener("click", () => {
  window.location.href = API + "/backup";
});

document.getElementById("restore-btn").addEventListener("click", async () => {
  const fileInput = document.getElementById("restore-file");
  const resultEl = document.getElementById("restore-result");
  if (!fileInput.files.length) {
    resultEl.textContent = "Bitte zuerst eine Backup-ZIP-Datei auswählen.";
    return;
  }
  if (!confirm("Achtung: Das überschreibt ALLE aktuellen Daten unwiderruflich mit dem Inhalt des Backups. Fortfahren?")) return;
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  const result = await api("/restore", { method: "POST", body: fd });
  resultEl.textContent = result.message;
  fileInput.value = "";
});

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
  document.getElementById("telegram-remove").classList.toggle("hidden", !s.telegram_configured);
  document.getElementById("telegram-bot-token").placeholder = s.telegram_configured
    ? "gespeichert – zum Ändern neuen Token eingeben" : "wird verschlüsselt gespeichert";
  document.getElementById("telegram-chat-id").placeholder = s.telegram_configured
    ? "gespeichert" : "z.B. 123456789";
}

document.getElementById("notifications-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const tokenInput = document.getElementById("telegram-bot-token");
  const chatIdInput = document.getElementById("telegram-chat-id");
  const payload = {
    enabled: document.getElementById("notifications-enabled").checked,
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

document.getElementById("telegram-remove").addEventListener("click", async () => {
  await api("/settings/notifications/telegram", { method: "DELETE" });
  toast("Telegram entfernt.");
  loadNotificationSettings();
});

// ================= EIGENE REGELN =================
const ALERT_RULE_LABELS = {
  category_spend_above: "Ausgaben über Betrag",
  account_balance_below: "Kontostand unter Betrag",
  category_deviation: "Abweichung vom Schnitt",
  goal_progress_above: "Ziel-Fortschritt erreicht",
};

async function loadAlertRules() {
  if (!categoriesCache.length) await loadCategories();
  if (!accountsCache.length) accountsCache = await api("/accounts");

  const catSel = document.getElementById("alert-rule-category");
  catSel.innerHTML = categoriesCache.filter(c => c.type === "ausgabe")
    .map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
  const accSel = document.getElementById("alert-rule-account");
  accSel.innerHTML = accountsCache.map(a => `<option value="${a.id}">${esc(a.name)}</option>`).join("");
  // Nur offene, automatisch messbare Ziele - manuelle Meilensteine haben keinen
  // Fortschritt in Prozent, das Backend lehnt sie fuer diese Regel auch ab.
  const goalSel = document.getElementById("alert-rule-goal");
  const measurableGoals = (await api("/goals").catch(() => []))
    .filter(g => g.status === "open" && g.goal_type === "auto_financial");
  goalSel.innerHTML = measurableGoals.length
    ? measurableGoals.map(g => `<option value="${g.id}">${esc(g.title)}</option>`).join("")
    : `<option value="">Kein automatisch messbares Ziel vorhanden</option>`;

  const rules = await api("/alert-rules");
  const list = document.getElementById("alert-rules-list");
  if (!rules.length) {
    list.innerHTML = `<p class="page-sub">Noch keine eigenen Regeln angelegt.</p>`;
    return;
  }
  list.innerHTML = rules.map(r => {
    const target = r.category_name || r.account_name || r.goal_title || "?";
    const unit = (r.rule_type === "category_deviation" || r.rule_type === "goal_progress_above") ? "%" : "€";
    return `
      <div class="todo-row">
        <span class="todo-title">
          ${esc(ALERT_RULE_LABELS[r.rule_type] || r.rule_type)} · ${esc(target)}
          <span class="page-sub" style="display:inline">– Schwelle ${r.threshold}${unit}</span>
        </span>
        <label class="checkbox-label" style="margin:0">
          <input type="checkbox" data-alert-rule-toggle="${r.id}" ${r.active ? "checked" : ""}>
          <span>aktiv</span>
        </label>
        <button type="button" class="link-btn" data-alert-rule-delete="${r.id}">Löschen</button>
      </div>`;
  }).join("");
}

function syncAlertRuleFormFields() {
  const type = document.getElementById("alert-rule-type").value;
  const usesCategory = type === "category_spend_above" || type === "category_deviation";
  document.getElementById("alert-rule-category-wrap").classList.toggle("hidden", !usesCategory);
  document.getElementById("alert-rule-account-wrap").classList.toggle("hidden", type !== "account_balance_below");
  document.getElementById("alert-rule-goal-wrap").classList.toggle("hidden", type !== "goal_progress_above");
  document.getElementById("alert-rule-threshold-wrap").firstChild.textContent =
    (type === "category_deviation" || type === "goal_progress_above") ? "Schwellwert (%) " : "Schwellwert (€) ";
}
document.getElementById("alert-rule-type").addEventListener("change", syncAlertRuleFormFields);

document.getElementById("alert-rule-form").addEventListener("submit", async e => {
  e.preventDefault();
  const type = document.getElementById("alert-rule-type").value;
  const payload = {
    rule_type: type,
    threshold: parseFloat(document.getElementById("alert-rule-threshold").value),
    category_id: (type === "category_spend_above" || type === "category_deviation")
      ? parseInt(document.getElementById("alert-rule-category").value, 10) : null,
    account_id: type === "account_balance_below" ? parseInt(document.getElementById("alert-rule-account").value, 10) : null,
    goal_id: type === "goal_progress_above" ? parseInt(document.getElementById("alert-rule-goal").value, 10) || null : null,
  };
  if (type === "goal_progress_above" && !payload.goal_id) {
    toast("Kein automatisch messbares Ziel vorhanden – erst ein Ziel mit Auswertungsregel anlegen.");
    return;
  }
  await api("/alert-rules", { method: "POST", body: JSON.stringify(payload) });
  document.getElementById("alert-rule-threshold").value = "";
  toast("Regel angelegt.");
  loadAlertRules();
});

document.getElementById("alert-rules-list").addEventListener("change", async e => {
  const id = e.target.closest("[data-alert-rule-toggle]")?.dataset.alertRuleToggle;
  if (id) {
    await api(`/alert-rules/${id}`, { method: "PATCH", body: JSON.stringify({ active: e.target.checked }) });
  }
});

document.getElementById("alert-rules-list").addEventListener("click", async e => {
  const id = e.target.closest("[data-alert-rule-delete]")?.dataset.alertRuleDelete;
  if (id) {
    await api(`/alert-rules/${id}`, { method: "DELETE" });
    loadAlertRules();
  }
});

async function loadCallSettings() {
  const s = await api("/settings/calls");
  document.getElementById("calls-enabled").checked = s.enabled;
  document.getElementById("twilio-remove").classList.toggle("hidden", !s.twilio_configured);
  document.getElementById("twilio-token").placeholder = s.twilio_configured
    ? "gespeichert – zum Ändern neuen Token eingeben" : "wird verschlüsselt gespeichert";
}

document.getElementById("calls-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const sidInput = document.getElementById("twilio-sid");
  const tokenInput = document.getElementById("twilio-token");
  const fromInput = document.getElementById("twilio-from");
  const toInput = document.getElementById("twilio-to");
  const payload = {
    enabled: document.getElementById("calls-enabled").checked,
    twilio_account_sid: sidInput.value.trim() || null,
    twilio_auth_token: tokenInput.value.trim() || null,
    twilio_from_number: fromInput.value.trim() || null,
    twilio_to_number: toInput.value.trim() || null,
  };
  await api("/settings/calls", { method: "PUT", body: JSON.stringify(payload) });
  tokenInput.value = "";
  toast("Gespeichert.");
  loadCallSettings();
});

document.getElementById("calls-test").addEventListener("click", async () => {
  const statusEl = document.getElementById("calls-status");
  statusEl.textContent = "Löse Anruf aus …";
  try {
    const r = await api("/calls/test", { method: "POST" });
    statusEl.textContent = r.message;
  } catch (e) {
    // api() zeigt den Fehler bereits per alert() an
  }
});

document.getElementById("twilio-remove").addEventListener("click", async () => {
  await api("/settings/calls/twilio", { method: "DELETE" });
  toast("Twilio entfernt.");
  loadCallSettings();
});

document.getElementById("sync-schedule-form").addEventListener("submit", async e => {
  e.preventDefault();
  const hour = parseInt(document.getElementById("sync-hour").value);
  await api("/settings/sync-schedule", { method: "PUT", body: JSON.stringify({ hour }) });
  toast(`Gespeichert – automatischer Sync läuft künftig um ${String(hour).padStart(2, "0")}:00 Uhr.`);
});

// ================= SETTINGS: FINTS BANK-SYNC =================
async function loadFintsSettings() {
  const s = await api("/settings/fints");
  document.getElementById("fints-product-id").value = s.fints_product_id || "";
}

document.getElementById("fints-product-form").addEventListener("submit", async e => {
  e.preventDefault();
  const fints_product_id = document.getElementById("fints-product-id").value;
  await api("/settings/fints", { method: "PUT", body: JSON.stringify({ fints_product_id }) });
  toast("FinTS-Produkt-ID gespeichert.");
});

function populateBankAccountSelect() {
  const sel = document.getElementById("bank-account");
  sel.innerHTML = "";
  accountsCache.forEach(a => {
    const opt = document.createElement("option");
    opt.value = a.id; opt.textContent = a.name;
    sel.appendChild(opt);
  });
}

async function loadBankConnections() {
  if (!accountsCache.length) await loadAccounts();
  populateBankAccountSelect();
  const conns = await api("/bank-connections");
  const tbody = document.getElementById("bank-conn-list");
  tbody.innerHTML = "";
  if (conns.length === 0) {
    tbody.innerHTML = emptyRow(5, "landmark", "Noch keine Bank-Verbindung angelegt.");
  }
  conns.forEach(c => {
    const tr = document.createElement("tr");
    const lastSync = c.last_sync_at ? new Date(c.last_sync_at).toLocaleString("de-DE") : "noch nie";
    tr.innerHTML = `
      <td>${c.name}</td>
      <td>${c.iban || "–"}</td>
      <td>${lastSync}</td>
      <td>${c.last_sync_status || "–"}</td>
      <td>
        <button class="link-btn" onclick="syncBankConnection(${c.id})">Jetzt synchronisieren</button>
        <button class="link-btn" onclick="deleteBankConnection(${c.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
    const tanRow = document.createElement("tr");
    tanRow.id = `tan-row-${c.id}`;
    tanRow.style.display = "none";
    tanRow.innerHTML = `<td colspan="5">
      <div class="filter-row">
        <span id="tan-challenge-${c.id}" class="page-sub"></span>
        <input type="text" id="tan-input-${c.id}" placeholder="TAN eingeben">
        <button class="btn-primary" onclick="submitTan(${c.id})">TAN bestätigen</button>
      </div>
    </td>`;
    tbody.appendChild(tanRow);
  });
}

document.getElementById("bank-conn-form").addEventListener("submit", async e => {
  e.preventDefault();
  const payload = {
    name: document.getElementById("bank-name").value,
    blz: document.getElementById("bank-blz").value,
    fints_url: document.getElementById("bank-fints-url").value,
    login: document.getElementById("bank-login").value,
    pin: document.getElementById("bank-pin").value,
    iban: document.getElementById("bank-iban").value,
    account_id: parseInt(document.getElementById("bank-account").value),
  };
  await api("/bank-connections", { method: "POST", body: JSON.stringify(payload) });
  document.getElementById("bank-conn-form").reset();
  loadBankConnections();
});

window.deleteBankConnection = async id => {
  if (!confirm("Bank-Verbindung wirklich löschen? Bereits importierte Buchungen bleiben erhalten.")) return;
  await api(`/bank-connections/${id}`, { method: "DELETE" });
  loadBankConnections();
};

function handleSyncResult(id, result) {
  const tanRow = document.getElementById(`tan-row-${id}`);
  if (result.tan_required) {
    document.getElementById(`tan-challenge-${id}`).textContent = result.challenge || "TAN erforderlich";
    tanRow.style.display = "table-row";
  } else {
    tanRow.style.display = "none";
    if (result.error) {
      alert("Sync-Fehler: " + result.error);
    } else {
      alert(`Sync abgeschlossen: ${result.imported} neue Buchung(en), ${result.skipped} bereits vorhanden.`);
      loadTransactions();
      loadAccounts();
    }
    loadBankConnections();
  }
}

window.syncBankConnection = async id => {
  const result = await api(`/bank-connections/${id}/sync`, { method: "POST" });
  handleSyncResult(id, result);
};

window.submitTan = async id => {
  const tan = document.getElementById(`tan-input-${id}`).value;
  if (!tan) return;
  const result = await api(`/bank-connections/${id}/submit-tan`, { method: "POST", body: JSON.stringify({ tan }) });
  handleSyncResult(id, result);
};

// ================= SETTINGS: BITVAVO =================
async function loadBitvavoConnections() {
  const conns = await api("/bitvavo-connections");
  const tbody = document.getElementById("bitvavo-conn-list");
  tbody.innerHTML = "";
  if (conns.length === 0) {
    tbody.innerHTML = emptyRow(4, "coins", "Noch keine Bitvavo-Verbindung angelegt.");
  }
  conns.forEach(c => {
    const tr = document.createElement("tr");
    const lastSync = c.last_sync_at ? new Date(c.last_sync_at).toLocaleString("de-DE") : "noch nie";
    tr.innerHTML = `
      <td>${c.name}</td>
      <td>${lastSync}</td>
      <td>${c.last_sync_status || "–"}</td>
      <td>
        <button class="link-btn" onclick="syncBitvavoConnection(${c.id})">Jetzt synchronisieren</button>
        <button class="link-btn" onclick="deleteBitvavoConnection(${c.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });
}

document.getElementById("bitvavo-form").addEventListener("submit", async e => {
  e.preventDefault();
  const payload = {
    name: document.getElementById("bitvavo-name").value,
    api_key: document.getElementById("bitvavo-key").value,
    api_secret: document.getElementById("bitvavo-secret").value,
  };
  await api("/bitvavo-connections", { method: "POST", body: JSON.stringify(payload) });
  document.getElementById("bitvavo-form").reset();
  loadBitvavoConnections();
});

window.syncBitvavoConnection = async id => {
  const result = await api(`/bitvavo-connections/${id}/sync`, { method: "POST" });
  if (result.error) {
    alert("Sync-Fehler: " + result.error);
  } else {
    alert(`Sync abgeschlossen: ${result.created} neue Position(en), ${result.updated} aktualisiert.`
      + (result.failed.length ? "\nOhne Kurs:\n" + result.failed.join("\n") : ""));
    loadHoldings();
  }
  loadBitvavoConnections();
};

window.deleteBitvavoConnection = async id => {
  if (!confirm("Bitvavo-Verbindung wirklich löschen?")) return;
  await api(`/bitvavo-connections/${id}`, { method: "DELETE" });
  loadBitvavoConnections();
};

// ================= SETTINGS: PAYPAL =================
function populatePaypalAccountSelect() {
  const sel = document.getElementById("paypal-account");
  sel.innerHTML = "";
  accountsCache.forEach(a => {
    const opt = document.createElement("option");
    opt.value = a.id; opt.textContent = a.name;
    sel.appendChild(opt);
  });
}

async function loadPaypalConnections() {
  if (!accountsCache.length) await loadAccounts();
  populatePaypalAccountSelect();
  const conns = await api("/paypal-connections");
  const tbody = document.getElementById("paypal-conn-list");
  tbody.innerHTML = "";
  if (conns.length === 0) {
    tbody.innerHTML = emptyRow(4, "credit-card", "Noch keine PayPal-Verbindung angelegt.");
  }
  conns.forEach(c => {
    const tr = document.createElement("tr");
    const lastSync = c.last_sync_at ? new Date(c.last_sync_at).toLocaleString("de-DE") : "noch nie";
    tr.innerHTML = `
      <td>${c.name}</td>
      <td>${lastSync}</td>
      <td>${c.last_sync_status || "–"}</td>
      <td>
        <button class="link-btn" onclick="syncPaypalConnection(${c.id})">Jetzt synchronisieren</button>
        <button class="link-btn" onclick="deletePaypalConnection(${c.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });
}

document.getElementById("paypal-form").addEventListener("submit", async e => {
  e.preventDefault();
  const payload = {
    name: document.getElementById("paypal-name").value,
    client_id: document.getElementById("paypal-client-id").value,
    client_secret: document.getElementById("paypal-client-secret").value,
    account_id: parseInt(document.getElementById("paypal-account").value),
  };
  await api("/paypal-connections", { method: "POST", body: JSON.stringify(payload) });
  document.getElementById("paypal-form").reset();
  loadPaypalConnections();
});

window.syncPaypalConnection = async id => {
  const result = await api(`/paypal-connections/${id}/sync`, { method: "POST" });
  if (result.error) {
    alert("Sync-Fehler: " + result.error);
  } else {
    alert(`Sync abgeschlossen: ${result.imported} neue Buchung(en), ${result.skipped} bereits vorhanden.`);
    loadTransactions();
    loadAccounts();
  }
  loadPaypalConnections();
};

window.deletePaypalConnection = async id => {
  if (!confirm("PayPal-Verbindung wirklich löschen? Bereits importierte Buchungen bleiben erhalten.")) return;
  await api(`/paypal-connections/${id}`, { method: "DELETE" });
  loadPaypalConnections();
};

// ================= SETTINGS: ENABLE BANKING =================
async function loadEnableBankingSettings() {
  const s = await api("/settings/enablebanking");
  document.getElementById("eb-app-id").value = s.app_id || "";
  document.getElementById("eb-redirect-base").value = s.redirect_base_url || "";
  document.getElementById("eb-key-status").textContent = s.private_key_set
    ? "Privater Schlüssel ist hinterlegt (wird aus Sicherheitsgründen nicht wieder angezeigt)."
    : "Noch kein privater Schlüssel hinterlegt.";
  const base = s.redirect_base_url || location.origin;
  document.getElementById("eb-redirect-hint").textContent = base + "/api/enablebanking/callback";
}

document.getElementById("eb-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const app_id = document.getElementById("eb-app-id").value;
  const private_key = document.getElementById("eb-private-key").value;
  const redirect_base_url = document.getElementById("eb-redirect-base").value.trim();
  if (!private_key.trim()) {
    alert("Bitte den privaten Schlüssel (PEM) einfügen.");
    return;
  }
  await api("/settings/enablebanking", { method: "PUT", body: JSON.stringify({ app_id, private_key, redirect_base_url: redirect_base_url || null }) });
  document.getElementById("eb-private-key").value = "";
  loadEnableBankingSettings();
  toast("Enable-Banking-Zugang gespeichert.");
});

document.getElementById("eb-load-banks").addEventListener("click", async () => {
  const country = document.getElementById("eb-country").value;
  const sel = document.getElementById("eb-aspsp");
  sel.innerHTML = '<option value="">Lädt …</option>';
  try {
    const aspsps = await api(`/enablebanking/aspsps?country=${country}`);
    sel.innerHTML = "";
    if (aspsps.length === 0) sel.innerHTML = '<option value="">Keine Banken gefunden</option>';
    aspsps.forEach(a => {
      const opt = document.createElement("option");
      opt.value = a.name; opt.dataset.country = a.country; opt.textContent = a.name;
      sel.appendChild(opt);
    });
  } catch (e) {
    sel.innerHTML = '<option value="">Fehler beim Laden</option>';
  }
});

function populateEbAccountSelect() {
  const sel = document.getElementById("eb-account");
  sel.innerHTML = "";
  accountsCache.forEach(a => {
    const opt = document.createElement("option");
    opt.value = a.id; opt.textContent = a.name;
    sel.appendChild(opt);
  });
}

const EB_STATUS_LABELS = { pending: "Autorisierung ausstehend", linked: "Verbunden", error: "Fehler" };

async function loadEnableBankingConnections() {
  if (!accountsCache.length) await loadAccounts();
  populateEbAccountSelect();
  const conns = await api("/enablebanking/connections");
  const tbody = document.getElementById("eb-conn-list");
  tbody.innerHTML = "";
  if (conns.length === 0) {
    tbody.innerHTML = emptyRow(4, "landmark", "Noch keine Verbindung angelegt.");
  }
  conns.forEach(c => {
    const tr = document.createElement("tr");
    const lastSync = c.last_sync_at ? new Date(c.last_sync_at).toLocaleString("de-DE") : "noch nie";
    tr.innerHTML = `
      <td>${c.aspsp_name} (${c.aspsp_country})</td>
      <td>${EB_STATUS_LABELS[c.status] || c.status}${c.last_sync_status ? `<br><span class="page-sub">${c.last_sync_status}</span>` : ""}</td>
      <td>${lastSync}</td>
      <td>
        ${c.status === "linked" ? `<button class="link-btn" onclick="syncEbConnection(${c.id})">Jetzt synchronisieren</button>` : ""}
        <button class="link-btn" onclick="deleteEbConnection(${c.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });
}

document.getElementById("eb-conn-form").addEventListener("submit", async e => {
  e.preventDefault();
  const sel = document.getElementById("eb-aspsp");
  const opt = sel.selectedOptions[0];
  if (!opt || !opt.value) { alert("Bitte zuerst Banken laden und eine Bank auswählen."); return; }
  const payload = {
    aspsp_name: opt.value,
    aspsp_country: opt.dataset.country,
    account_id: parseInt(document.getElementById("eb-account").value),
  };
  const result = await api("/enablebanking/connections", { method: "POST", body: JSON.stringify(payload) });
  loadEnableBankingConnections();
  window.open(result.url, "_blank");
});

window.syncEbConnection = async id => {
  const result = await api(`/enablebanking/connections/${id}/sync`, { method: "POST" });
  if (result.error) {
    alert("Sync-Fehler: " + result.error);
  } else {
    alert(`Sync abgeschlossen: ${result.imported} neue Buchung(en), ${result.skipped} bereits vorhanden.`);
    loadTransactions();
    loadAccounts();
  }
  loadEnableBankingConnections();
};

window.deleteEbConnection = async id => {
  if (!confirm("Verbindung wirklich löschen? Bereits importierte Buchungen bleiben erhalten.")) return;
  await api(`/enablebanking/connections/${id}`, { method: "DELETE" });
  loadEnableBankingConnections();
};

function handleEnableBankingReturn() {
  const params = new URLSearchParams(location.search);
  const done = params.get("enablebanking_done");
  const err = params.get("enablebanking_error");
  if (!done && !err) return;
  history.replaceState({}, "", location.pathname);
  const settingsBtn = document.querySelector('.nav-btn[data-tab="settings"]');
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
  settingsBtn.classList.add("active");
  document.getElementById("tab-settings").classList.add("active");
  moveNavIndicator(settingsBtn);
  loadSettingsTab().then(() => {
    if (err) alert("Enable-Banking-Autorisierung fehlgeschlagen: " + err);
  });
}

// ---------- eBay ----------
async function loadEbaySettings() {
  const s = await api("/settings/ebay");
  document.getElementById("ebay-app-id").value = s.app_id || "";
  document.getElementById("ebay-ru-name").value = s.ru_name || "";
  document.getElementById("ebay-key-status").textContent = s.cert_id_set
    ? "Cert-ID ist hinterlegt (wird aus Sicherheitsgründen nicht wieder angezeigt)."
    : "Noch keine Cert-ID hinterlegt.";
  document.getElementById("ebay-redirect-hint").textContent = location.origin + "/api/ebay/callback";
}

document.getElementById("ebay-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const app_id = document.getElementById("ebay-app-id").value;
  const cert_id = document.getElementById("ebay-cert-id").value;
  const ru_name = document.getElementById("ebay-ru-name").value;
  if (!cert_id.trim()) {
    alert("Bitte die Cert-ID (Client-Secret) eingeben.");
    return;
  }
  await api("/settings/ebay", { method: "PUT", body: JSON.stringify({ app_id, cert_id, ru_name }) });
  document.getElementById("ebay-cert-id").value = "";
  loadEbaySettings();
  toast("eBay-Zugang gespeichert.");
});

function populateEbayAccountSelect() {
  const sel = document.getElementById("ebay-account");
  sel.innerHTML = "";
  accountsCache.forEach(a => {
    const opt = document.createElement("option");
    opt.value = a.id; opt.textContent = a.name;
    sel.appendChild(opt);
  });
}

const EBAY_STATUS_LABELS = { pending: "Autorisierung ausstehend", connected: "Verbunden", error: "Fehler" };

async function loadEbayConnections() {
  if (!accountsCache.length) await loadAccounts();
  populateEbayAccountSelect();
  const conns = await api("/ebay/connections");
  const tbody = document.getElementById("ebay-conn-list");
  tbody.innerHTML = "";
  if (conns.length === 0) {
    tbody.innerHTML = emptyRow(4, "shopping-cart", "Noch keine Verbindung angelegt.");
  }
  conns.forEach(c => {
    const account = accountsCache.find(a => a.id === c.account_id);
    const lastSync = c.last_sync_at ? new Date(c.last_sync_at).toLocaleString("de-DE") : "noch nie";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${account ? esc(account.name) : c.account_id}</td>
      <td>${EBAY_STATUS_LABELS[c.status] || c.status}${c.last_sync_status ? `<br><span class="page-sub">${esc(c.last_sync_status)}</span>` : ""}</td>
      <td>${lastSync}</td>
      <td>
        ${c.status === "connected" ? `<button class="link-btn" onclick="syncEbayConnection(${c.id})">Jetzt synchronisieren</button>` : ""}
        <button class="link-btn" onclick="deleteEbayConnection(${c.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });
}

document.getElementById("ebay-conn-form").addEventListener("submit", async e => {
  e.preventDefault();
  const payload = { account_id: parseInt(document.getElementById("ebay-account").value) };
  const result = await api("/ebay/connections", { method: "POST", body: JSON.stringify(payload) });
  loadEbayConnections();
  window.open(result.url, "_blank");
});

window.syncEbayConnection = async id => {
  const result = await api(`/ebay/connections/${id}/sync`, { method: "POST" });
  if (result.error) {
    alert("Sync-Fehler: " + result.error);
  } else {
    alert(`Sync abgeschlossen: ${result.imported} neue Buchung(en), ${result.skipped} bereits vorhanden.`);
    loadTransactions();
    loadAccounts();
  }
  loadEbayConnections();
};

window.deleteEbayConnection = async id => {
  if (!confirm("Verbindung wirklich löschen? Bereits importierte Buchungen bleiben erhalten.")) return;
  await api(`/ebay/connections/${id}`, { method: "DELETE" });
  loadEbayConnections();
};

function handleEbayReturn() {
  const params = new URLSearchParams(location.search);
  const done = params.get("ebay_done");
  const err = params.get("ebay_error");
  if (!done && !err) return;
  history.replaceState({}, "", location.pathname);
  const settingsBtn = document.querySelector('.nav-btn[data-tab="settings"]');
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
  settingsBtn.classList.add("active");
  document.getElementById("tab-settings").classList.add("active");
  moveNavIndicator(settingsBtn);
  loadSettingsTab().then(() => {
    if (err) alert("eBay-Autorisierung fehlgeschlagen: " + err);
  });
}

// ---------- Radicale-Einstellungen ----------
async function loadRadicaleSettings() {
  const s = await api("/settings/radicale");
  document.getElementById("radicale-url").value = s.url || "";
  document.getElementById("radicale-username").value = s.username || "";
  document.getElementById("radicale-calendar-url").value = s.calendar_url || "";
  document.getElementById("radicale-status").textContent = s.password_set
    ? "Zugangsdaten sind hinterlegt (Passwort wird aus Sicherheitsgründen nicht wieder angezeigt)."
    : "Noch keine Zugangsdaten hinterlegt.";
}

document.getElementById("radicale-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const url = document.getElementById("radicale-url").value.trim();
  const username = document.getElementById("radicale-username").value.trim();
  const password = document.getElementById("radicale-password").value;
  const calendar_url = document.getElementById("radicale-calendar-url").value.trim();
  if (!url || !password) {
    alert("Bitte Adresse und Passwort eingeben.");
    return;
  }
  await api("/settings/radicale", { method: "PUT", body: JSON.stringify({ url, username, password, calendar_url }) });
  document.getElementById("radicale-password").value = "";
  loadRadicaleSettings();
  toast("Radicale-Zugang gespeichert.");
});

document.getElementById("radicale-test").addEventListener("click", async () => {
  const statusEl = document.getElementById("radicale-status");
  statusEl.textContent = "Teste Verbindung …";
  const r = await api("/radicale/test", { method: "POST" });
  statusEl.textContent = r.ok
    ? `✓ Verbunden – ${r.todo_count} To-Do(s) auf dem Server gefunden.`
    : `✗ ${r.error}`;
});

// ---------- Fahrzeit-Einstellungen ----------
async function loadTravelSettings() {
  const s = await api("/settings/travel");
  document.getElementById("travel-home-address").value = s.home_address || "";
  document.getElementById("travel-api-key").placeholder = s.api_key_set
    ? "gespeichert – leer lassen behält den bisherigen"
    : "wird verschlüsselt gespeichert";
  const status = document.getElementById("travel-status");
  if (!s.home_address) {
    status.textContent = "";
  } else if (!s.home_geocoded) {
    status.textContent = "⚠️ Adresse konnte nicht gefunden werden - bitte prüfen (Straße Hausnummer, PLZ Ort).";
  } else {
    status.textContent = "✓ Adresse gefunden.";
  }
}

document.getElementById("travel-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const body = {
    home_address: document.getElementById("travel-home-address").value.trim(),
    api_key: document.getElementById("travel-api-key").value.trim() || null,
  };
  await api("/settings/travel", { method: "PUT", body: JSON.stringify(body) });
  document.getElementById("travel-api-key").value = "";
  await loadTravelSettings();
  toast("Fahrzeit-Einstellungen gespeichert.");
});

// ---------- To-Dos ----------
let todosCache = [];

async function loadTodos() {
  const list = document.getElementById("todo-list");
  try {
    todosCache = await api("/todos");
  } catch (e) {
    list.innerHTML = `<p class="page-sub">${esc(e.message)}</p>`;
    return;
  }
  renderTodos();
}

function renderTodos() {
  const list = document.getElementById("todo-list");
  if (!todosCache.length) {
    list.innerHTML = `<p class="page-sub">Noch keine To-Dos.</p>`;
    return;
  }
  list.innerHTML = todosCache.map(t => `
    <label class="todo-row ${t.done ? "is-done" : ""}">
      <input type="checkbox" data-todo-toggle="${t.id}" ${t.done ? "checked" : ""}>
      <span class="todo-title">${esc(t.title)}</span>
      ${t.due_date ? `<span class="todo-due">${fmtDate(t.due_date)}</span>` : ""}
      <button type="button" class="link-btn" data-notes-entity="todo" data-notes-id="${t.id}" data-notes-label="${esc(t.title)}">📝</button>
      <button type="button" class="link-btn" data-todo-delete="${t.id}">Löschen</button>
    </label>`).join("");
}

document.getElementById("todo-form").addEventListener("submit", async e => {
  e.preventDefault();
  const titleInput = document.getElementById("todo-title");
  const dueInput = document.getElementById("todo-due-date");
  const title = titleInput.value.trim();
  if (!title) return;
  await api("/todos", { method: "POST", body: JSON.stringify({ title, due_date: dueInput.value || null }) });
  titleInput.value = "";
  dueInput.value = "";
  await loadTodos();
});

document.getElementById("todo-list").addEventListener("click", async e => {
  const delId = e.target.closest("[data-todo-delete]")?.dataset.todoDelete;
  if (delId) {
    await api(`/todos/${delId}`, { method: "DELETE" });
    await loadTodos();
  }
});

document.getElementById("todo-list").addEventListener("change", async e => {
  const toggleId = e.target.closest("[data-todo-toggle]")?.dataset.todoToggle;
  if (toggleId) {
    await api(`/todos/${toggleId}`, { method: "PATCH", body: JSON.stringify({ done: e.target.checked }) });
    await loadTodos();
  }
});

// ================= KALENDER =================
let calendarEventsCache = [];
let calendarCollectionsCache = [];

function fmtDateTime(iso) {
  const d = new Date(iso);
  return d.toLocaleString("de-DE", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

async function loadCalendarTab() {
  calendarCollectionsCache = await api("/calendar/collections").catch(() => []);
  await loadCalendarEvents();
  await loadCalendarConflicts();
}

async function loadCalendarConflicts() {
  const warn = document.getElementById("calendar-conflict-warning");
  const conflicts = await api("/calendar/conflicts?days=30").catch(() => []);
  if (!conflicts.length) {
    warn.classList.add("hidden");
    return;
  }
  warn.innerHTML = `⚠️ ${conflicts.length} Terminüberschneidung${conflicts.length > 1 ? "en" : ""}: ` +
    conflicts.map(c => `„${esc(c.event_a_title)}“ ↔ „${esc(c.event_b_title)}“ (${fmtDateTime(c.event_a_start)})`).join(" · ");
  warn.classList.remove("hidden");
}

async function loadCalendarEvents() {
  const showPast = document.getElementById("calendar-show-past").checked;
  const start = new Date();
  start.setDate(start.getDate() - (showPast ? 30 : 0));
  start.setHours(0, 0, 0, 0);
  const end = new Date();
  end.setDate(end.getDate() + 60);
  end.setHours(23, 59, 59, 0);
  const list = document.getElementById("calendar-event-list");
  list.innerHTML = skelRows ? skelRows(3) : "";
  try {
    calendarEventsCache = await api(`/calendar-events?start=${start.toISOString()}&end=${end.toISOString()}`);
  } catch (e) {
    list.innerHTML = `<p class="page-sub">${esc(e.message)}</p>`;
    return;
  }
  renderCalendarEvents();
}

function renderCalendarEvents() {
  const list = document.getElementById("calendar-event-list");
  if (!calendarEventsCache.length) {
    list.innerHTML = `<div class="empty-state"><span class="empty-icon">${svgIcon("calendar")}</span><span>Keine Termine im gewählten Zeitraum.</span></div>`;
    return;
  }
  const now = new Date();
  const groups = new Map();
  calendarEventsCache.forEach(ev => {
    const key = new Date(ev.start).toLocaleDateString("de-DE", { weekday: "long", day: "2-digit", month: "2-digit", year: "numeric" });
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(ev);
  });
  list.innerHTML = [...groups.entries()].map(([day, events]) => `
    <div class="calendar-day-group">
      <h4 class="calendar-day-label">${esc(day)}</h4>
      ${events.map(ev => `
        <div class="todo-row" ${ev.is_recurring ? "" : `data-calendar-edit="${ev.id}" style="cursor:pointer"`}>
          <span class="todo-title">
            ${ev.is_recurring ? '<span title="Wiederkehrender Termin - Serie am Handy/Radicale bearbeiten">🔁</span> ' : ""}${esc(ev.title)}
            ${new Date(ev.start) < now ? '<span class="page-sub" style="display:inline">· vergangen</span>' : ""}
          </span>
          <span class="todo-due">${ev.all_day ? "ganztägig" : new Date(ev.start).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}${ev.location ? " · " + esc(ev.location) : ""}${ev.travel_minutes != null ? ` · 🚗 ~${ev.travel_minutes} Min` : ""}</span>
        </div>
      `).join("")}
    </div>
  `).join("");
}

document.getElementById("calendar-show-past").addEventListener("change", loadCalendarEvents);

document.getElementById("calendar-event-list").addEventListener("click", e => {
  const id = e.target.closest("[data-calendar-edit]")?.dataset.calendarEdit;
  if (id) openCalendarModal(calendarEventsCache.find(ev => ev.id === Number(id)));
});

function openCalendarModal(ev) {
  document.getElementById("calendar-collection").innerHTML = calendarCollectionsCache
    .map(c => `<option value="${esc(c.url)}">${esc(c.name)}</option>`).join("")
    || '<option value="">Kein Kalender verbunden – Termin bleibt nur lokal</option>';

  document.getElementById("calendar-modal-title").textContent = ev ? "Termin bearbeiten" : "Neuer Termin";
  document.getElementById("calendar-event-id").value = ev ? ev.id : "";
  document.getElementById("calendar-title").value = ev ? ev.title : "";
  document.getElementById("calendar-all-day").checked = ev ? ev.all_day : false;
  document.getElementById("calendar-location").value = ev?.location || "";
  document.getElementById("calendar-collection").value = ev?.calendar_url || "";

  const start = ev ? new Date(ev.start) : new Date();
  document.getElementById("calendar-start-date").value = start.toISOString().slice(0, 10);
  document.getElementById("calendar-start-time").value = ev ? start.toTimeString().slice(0, 5) : "09:00";
  if (ev?.end) {
    const end = new Date(ev.end);
    document.getElementById("calendar-end-date").value = end.toISOString().slice(0, 10);
    document.getElementById("calendar-end-time").value = end.toTimeString().slice(0, 5);
  } else {
    document.getElementById("calendar-end-date").value = "";
    document.getElementById("calendar-end-time").value = "";
  }

  document.getElementById("calendar-delete-btn").classList.toggle("hidden", !ev);
  syncCalendarFormVisibility();
  document.getElementById("calendar-modal").classList.remove("hidden");
}

function syncCalendarFormVisibility() {
  const allDay = document.getElementById("calendar-all-day").checked;
  document.getElementById("calendar-start-time-wrap").classList.toggle("hidden", allDay);
  document.getElementById("calendar-end-time-wrap").classList.toggle("hidden", allDay);
}
document.getElementById("calendar-all-day").addEventListener("change", syncCalendarFormVisibility);

function closeCalendarModal() {
  document.getElementById("calendar-modal").classList.add("hidden");
}
document.getElementById("calendar-new-btn").addEventListener("click", () => openCalendarModal(null));
document.getElementById("calendar-modal-close").addEventListener("click", closeCalendarModal);

document.getElementById("calendar-form").addEventListener("submit", async e => {
  e.preventDefault();
  const id = document.getElementById("calendar-event-id").value;
  const allDay = document.getElementById("calendar-all-day").checked;
  const startDate = document.getElementById("calendar-start-date").value;
  const startTime = document.getElementById("calendar-start-time").value || "00:00";
  const endDate = document.getElementById("calendar-end-date").value;
  const endTime = document.getElementById("calendar-end-time").value || "00:00";
  const start = allDay ? `${startDate}T00:00:00` : `${startDate}T${startTime}:00`;
  const end = endDate ? (allDay ? `${endDate}T00:00:00` : `${endDate}T${endTime}:00`) : null;

  const payload = {
    title: document.getElementById("calendar-title").value,
    start, end,
    location: document.getElementById("calendar-location").value || null,
    all_day: allDay,
  };
  if (!id) payload.calendar_url = document.getElementById("calendar-collection").value || null;

  if (id) {
    await api(`/calendar-events/${id}`, { method: "PUT", body: JSON.stringify(payload) });
  } else {
    await api("/calendar-events", { method: "POST", body: JSON.stringify(payload) });
  }
  closeCalendarModal();
  await loadCalendarEvents();
});

document.getElementById("calendar-delete-btn").addEventListener("click", async () => {
  const id = document.getElementById("calendar-event-id").value;
  if (!id || !confirm("Termin wirklich löschen?")) return;
  await api(`/calendar-events/${id}`, { method: "DELETE" });
  closeCalendarModal();
  await loadCalendarEvents();
});

const SETTINGS_VIEWS = ["allgemein", "banken", "ki", "benachrichtigungen", "verbindungen", "daten"];

document.getElementById("settings-subtabs").addEventListener("click", e => {
  const view = e.target.closest("[data-settings-view]")?.dataset.settingsView;
  if (!view) return;
  document.querySelectorAll("#settings-subtabs .range-tab").forEach(b =>
    b.classList.toggle("active", b.dataset.settingsView === view));
  SETTINGS_VIEWS.forEach(v =>
    document.getElementById(`settings-view-${v}`).classList.toggle("hidden", v !== view));
});

// Zeichen und Klasse je Zustand. Das Ausrufezeichen steht bewusst auch bei
// "partial": halb eingerichtet ist genauso wenig nutzbar wie gar nicht.
const INTEGRATION_MARKS = {
  ok: { mark: "✓", cls: "is-ok" },
  partial: { mark: "❗", cls: "is-partial" },
  missing: { mark: "❗", cls: "is-missing" },
  off: { mark: "⏸", cls: "is-off" },
};

async function loadIntegrationStatus() {
  const box = document.getElementById("integration-status");
  let data;
  try {
    data = await api("/integrations/status");
  } catch (e) {
    box.innerHTML = `<p class="page-sub">Status konnte nicht geladen werden: ${esc(e.message)}</p>`;
    return;
  }

  box.innerHTML = data.items.map(it => {
    const m = INTEGRATION_MARKS[it.status] || INTEGRATION_MARKS.missing;
    const fehlt = it.missing.length
      ? `<div class="integration-missing">Es fehlt: ${it.missing.map(m => esc(m)).join(", ")}</div>`
      : "";
    // Ollama ist die einzige Anbindung, ohne die sichtbare Funktionen ausfallen -
    // alles andere ist Zusatz und soll nicht wie ein Versäumnis wirken.
    const pflicht = (!it.optional && it.status !== "ok")
      ? `<div class="integration-required">Für die KI-Funktionen nötig</div>` : "";
    return `<div class="integration-card ${m.cls}">
      <div class="integration-mark">${m.mark}</div>
      <div class="integration-body">
        <div class="integration-name">${esc(it.name)}</div>
        <div class="integration-purpose">${esc(it.purpose)}</div>
        <div class="integration-purpose">${esc(it.detail)}</div>
        ${fehlt}${pflicht}
      </div>
    </div>`;
  }).join("");

  updateIntegrationBadge(data.incomplete);
  applySettingsPanelCollapse(data.items);
}

// Klappt die Einstellungen-Panels bereits vollständig eingerichteter
// Anbindungen standardmäßig zu - bewusst NUR die einzelnen Formulare unten,
// nicht die große Übersicht ("Einrichtungsstatus") oben, die soll unverändert
// alles auf einen Blick zeigen. Jedes Panel bleibt per Klick auf den Titel
// auf-/zuklappbar, auch die noch offenen.
function applySettingsPanelCollapse(items) {
  const byKey = Object.fromEntries(items.map(it => [it.key, it]));
  document.querySelectorAll(".panel[data-integration-key]").forEach(panel => {
    const key = panel.dataset.integrationKey;
    const it = byKey[key];
    if (!it) return;
    const titleEl = panel.querySelector(".panel-title");
    titleEl.querySelector(".panel-collapsed-hint")?.remove();
    if (it.status === "ok") {
      const hint = document.createElement("span");
      hint.className = "panel-collapsed-hint";
      hint.textContent = "✓ eingerichtet";
      titleEl.appendChild(hint);
      // Nur beim ersten Laden automatisch zuklappen - ein Klick des Nutzers
      // (data-user-toggled) soll nicht bei jedem Neuladen überschrieben werden.
      if (!panel.dataset.userToggled) panel.classList.add("is-collapsed");
    }
  });
}

document.addEventListener("click", e => {
  const titleEl = e.target.closest(".panel[data-integration-key] > .panel-title");
  if (!titleEl) return;
  const panel = titleEl.closest(".panel");
  panel.classList.toggle("is-collapsed");
  panel.dataset.userToggled = "1";
});

function updateIntegrationBadge(count) {
  const badge = document.getElementById("integration-nav-badge");
  if (!badge) return;
  badge.textContent = count > 0 ? count : "";
  badge.classList.toggle("hidden", !count);
}

// Beim Start einmal zählen, damit die Plakette stimmt, ohne dass man die
// Einstellungen geöffnet haben muss.
async function refreshIntegrationBadge() {
  try {
    const data = await api("/integrations/status");
    updateIntegrationBadge(data.incomplete);
  } catch (e) {
    // Für den Start unkritisch
  }
}

async function loadSettingsTab() {
  await loadCountrySettings();
  await loadIntegrationStatus();
  await loadBudgets();
  await loadOllamaSettings();
  await loadSyncSchedule();
  await loadAutoCategorizeSettings();
  await loadWebSearchSettings();
  await loadImmichSettings();
  await loadWebhookSettings();
  await loadNativeSyncSettings();
  await loadScalableSettings();
  await loadMailSettings();
  await loadCreditCardSettings();
  await loadNotificationSettings();
  await loadAlertRules();
  await loadCallSettings();
  await loadBackupSettings();
  await loadBackupsList();
  await loadTaxExportFilters();
  await loadFintsSettings();
  await loadBankConnections();
  await loadBitvavoConnections();
  await loadPaypalConnections();
  await loadEnableBankingSettings();
  await loadEnableBankingConnections();
  await loadEbaySettings();
  await loadEbayConnections();
  await loadRadicaleSettings();
  await loadTravelSettings();
}

// ================= DASHBOARD =================
// Springt programmatisch zu einem Tab - gleiche Schritte wie ein echter Klick
// auf den Nav-Button, nur ausgelöst von einer Hub-Kachel statt vom Nutzer
// direkt in der Navigation.
function goToTab(tabName) {
  document.querySelector(`.nav-btn[data-tab="${tabName}"]`)?.click();
}

// ---------- Skeleton-Loader-Bausteine ----------
function skelBento() {
  return `<div class="skel skel-hero"></div><div class="skel skel-tile"></div><div class="skel skel-tile"></div><div class="skel skel-tile"></div>`;
}
function skelRows(n) {
  return Array.from({ length: n }, () => `<div class="skel-row"><span class="skel"></span><span class="skel"></span></div>`).join("");
}
function skelTableRows(colspan, n) {
  return Array.from({ length: n }, () =>
    `<tr class="skel-table-row"><td colspan="${colspan}"><span class="skel" style="height:15px;width:${40 + Math.random() * 40}%"></span></td></tr>`
  ).join("");
}

// ---------- Hub (Startseite) ----------
// Uhrzeit eines Termins - bei ganztägigen Terminen gibt es keine sinnvolle
// Zeit, dann steht dort "ganztägig" statt "00:00".
function fmtTimeShort(iso) {
  return new Date(iso).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

const TODAY_DEADLINE_META = {
  kuendigung: { icon: "✂️", tab: "recurring" },
  ruecksendung: { icon: "📦", tab: "transactions" },
  zahlung: { icon: "💳", tab: "recurring" },
};

// Fokus-View: was heute ansteht. Kommt komplett aus /today (ein Aufruf), damit
// die Schwellwerte "was gilt als bald fällig" im Backend bleiben und nicht
// zwischen Hub, Telegram-Digest und hier auseinanderlaufen.
async function loadTodayPanel() {
  const body = document.getElementById("hub-today-body");
  const titleEl = document.getElementById("hub-today-title");
  body.innerHTML = skelRows(3);
  let data;
  try {
    data = await api("/today");
  } catch (e) {
    body.innerHTML = `<p class="page-sub">${esc(e.message)}</p>`;
    return;
  }
  titleEl.textContent = "Heute · " + new Date(data.date + "T00:00:00")
    .toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long" });

  const b = data.balance;
  const balanceLine = b.transaction_count
    ? `<div class="today-balance">
         <span><strong>${b.transaction_count}</strong> Buchung${b.transaction_count !== 1 ? "en" : ""} heute</span>
         <span class="row-amount-pos">${eur(b.income)}</span>
         <span class="row-amount-neg">${eur(b.expense)}</span>
         <span class="${b.balance >= 0 ? "row-amount-pos" : "row-amount-neg"}"><strong>${eur(b.balance)}</strong></span>
       </div>`
    : `<div class="today-balance"><span class="page-sub">Heute noch keine Buchung.</span></div>`;

  const sections = [];

  if (data.events.length) {
    sections.push(section("Termine", data.events.map(e => {
      const when = e.all_day ? "ganztägig" : fmtTimeShort(e.start);
      const extras = [];
      if (e.location) extras.push(esc(e.location));
      if (e.leave_at) extras.push(`🚗 ${e.travel_minutes} Min., losfahren ${fmtTimeShort(e.leave_at)}`);
      const sub = extras.length ? `<span class="page-sub" style="display:inline"> – ${extras.join(" · ")}</span>` : "";
      return `<button type="button" class="hub-list-row" data-hub-jump="goals">
        <span>${esc(e.title)}${sub}</span>
        <span class="page-sub">${when}</span>
      </button>`;
    })));
  }

  if (data.todos.length) {
    sections.push(section("Fällige To-Dos", data.todos.map(t => `
      <button type="button" class="hub-list-row" data-hub-jump="goals">
        <span>${t.overdue ? "⚠️ " : ""}${esc(t.title)}</span>
        <span class="page-sub ${t.overdue ? "neg" : ""}">${fmtDate(t.due_date)}</span>
      </button>`)));
  }

  if (data.deadlines.length) {
    sections.push(section("Fristen &amp; Fälligkeiten", data.deadlines.map(d => {
      const meta = TODAY_DEADLINE_META[d.kind] || { icon: "•", tab: "hub" };
      const when = d.days_left <= 0 ? "heute" : `in ${d.days_left} Tag${d.days_left !== 1 ? "en" : ""}`;
      const amount = d.amount != null
        ? `<span class="${d.amount >= 0 ? "row-amount-pos" : "row-amount-neg"}">${eur(d.amount)}</span>` : "";
      return `<button type="button" class="hub-list-row" data-hub-jump="${meta.tab}">
        <span>${meta.icon} ${esc(d.label)}${d.detail ? `<span class="page-sub" style="display:inline"> – ${esc(d.detail)}</span>` : ""}</span>
        <span style="display:flex;align-items:center;gap:10px">
          <span class="page-sub ${d.days_left <= 2 ? "neg" : ""}">${when}</span>${amount}
        </span>
      </button>`;
    })));
  }

  if (data.goals.length) {
    sections.push(section("Ziele in Reichweite", data.goals.map(g => {
      const pct = g.progress_percent != null ? `${g.progress_percent.toFixed(0)}%` : "";
      const when = g.days_left != null
        ? (g.days_left < 0 ? `${-g.days_left} Tage überfällig` : `noch ${g.days_left} Tage`) : "";
      return `<button type="button" class="hub-list-row" data-hub-jump="goals">
        <span>🎯 ${esc(g.title)}</span>
        <span style="display:flex;align-items:center;gap:10px">
          <span class="page-sub ${g.days_left != null && g.days_left < 0 ? "neg" : ""}">${when}</span>
          ${pct ? `<strong>${pct}</strong>` : ""}
        </span>
      </button>`;
    })));
  }

  body.innerHTML = balanceLine + (sections.length
    ? sections.join("")
    : `<p class="page-sub">Heute steht nichts an – keine Termine, Fristen oder fälligen To-Dos.</p>`);

  function section(title, rows) {
    return `<div class="today-section"><h4 class="today-section-title">${title}</h4>${rows.join("")}</div>`;
  }
}

async function loadHubTab() {
  document.getElementById("hub-date-kicker").textContent = new Date()
    .toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  loadTodayPanel();
  loadCategorySuggestions();
  const cardsEl = document.getElementById("hub-finance-cards");
  cardsEl.innerHTML = skelBento();
  document.getElementById("hub-todos-body").innerHTML = skelRows(3);
  document.getElementById("hub-transactions-body").innerHTML = skelRows(5);
  try {
    const [dash, nw, trend, nwHistory] = await Promise.all([
      api("/dashboard"), api("/net-worth"), api("/dashboard/trend?months=6"), api("/net-worth/history?days=180"),
    ]);
    const hasDebts = nw.debts_total > 0;
    const incomeSpark = sparklineSvg(trend.points.map(p => p.income));
    const expenseSpark = sparklineSvg(trend.points.map(p => Math.abs(p.expense)));
    const balanceSpark = sparklineSvg(trend.points.map(p => p.income + p.expense));
    // Erst ab 2 Snapshots gibt es ueberhaupt eine Linie zu zeichnen - der
    // taegliche Snapshot-Job (siehe Backend) wurde gerade erst eingefuehrt,
    // die Historie waechst also gemaechlich statt sofort voll da zu sein.
    const heroSpark = nwHistory.points.length >= 2
      ? `<span class="card-sparkline" title="Echte Vermögens-Historie">${sparklineSvg(nwHistory.points.map(p => p.total))}</span>`
      : "";
    cardsEl.innerHTML = `
      <button type="button" class="card hub-hero" data-hub-jump="investments">
        <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><path d="M3 17L9 11L13 15L21 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
        <div><h3>Nettovermögen</h3><p>${eur(nw.total)}</p></div>
        ${heroSpark}
      </button>
      <button type="button" class="card card-pos hub-tile" data-hub-jump="dashboard">
        <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><path d="M12 19V5M12 5L6 11M12 5L18 11" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
        <div><h3>Einnahmen (Jahr)</h3><p class="pos">${eur(dash.total_income)}</p></div>
        <span class="card-sparkline" title="Verlauf der letzten 6 Monate">${incomeSpark}</span>
      </button>
      <button type="button" class="card card-neg hub-tile" data-hub-jump="dashboard">
        <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><path d="M12 5V19M12 19L6 13M12 19L18 13" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
        <div><h3>Ausgaben (Jahr)</h3><p class="neg">${eur(dash.total_expense)}</p></div>
        <span class="card-sparkline" title="Verlauf der letzten 6 Monate">${expenseSpark}</span>
      </button>
      <button type="button" class="card card-bal hub-tile ${hasDebts ? "" : "hub-tile-wide"}" data-hub-jump="dashboard">
        <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2"/><path d="M8 12H16M12 8V16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></div>
        <div><h3>Saldo (Jahr)</h3><p>${eur(dash.balance)}</p></div>
        <span class="card-sparkline" title="Verlauf der letzten 6 Monate">${balanceSpark}</span>
      </button>`;
    if (hasDebts) {
      cardsEl.innerHTML += `
        <button type="button" class="card card-neg hub-tile" data-hub-jump="debts">
          <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><path d="M4 6.5h16M4 12h16M4 17.5h9" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></div>
          <div><h3>Restschulden</h3><p class="neg">${eur(nw.debts_total)}</p></div>
        </button>`;
    }

    // Notgroschen-Reichweite: liquide Mittel (Konten, keine Investments - die
    // sind im Notfall nicht sofort ohne Verlustrisiko verfuegbar) geteilt durch
    // den durchschnittlichen Monatsausgaben-Schnitt der letzten 6 Monate
    // (derselbe Zeitraum wie die Sparklines oben, fuer Konsistenz).
    const runwayPanel = document.getElementById("hub-runway-panel");
    const monthsWithExpense = trend.points.filter(p => p.expense !== 0);
    const avgMonthlyExpense = monthsWithExpense.length
      ? Math.abs(monthsWithExpense.reduce((sum, p) => sum + p.expense, 0)) / monthsWithExpense.length
      : 0;
    if (avgMonthlyExpense > 0) {
      const months = nw.accounts_total / avgMonthlyExpense;
      const cls = months >= 3 ? "pos" : months >= 1 ? "" : "neg";
      runwayPanel.classList.remove("hidden");
      document.getElementById("hub-runway-body").innerHTML = `
        <p style="font-size:32px;font-weight:800;margin:0 0 6px" class="${cls}">${months.toFixed(1).replace(".", ",")} Monate</p>
        <p class="page-sub">Dein Kontostand (${eur(nw.accounts_total)}) deckt bei durchschnittlich ${eur(avgMonthlyExpense)}/Monat
          Ausgaben rechnerisch ${months.toFixed(1).replace(".", ",")} Monate – ohne Investments, die sind im Notfall nicht
          verlustfrei sofort verfügbar.</p>`;
    } else {
      runwayPanel.classList.add("hidden");
    }
  } catch (e) {
    cardsEl.innerHTML = `<p class="page-sub">${esc(e.message)}</p>`;
  }

  // Nächstes offenes Ziel - frühestes Zieldatum zuerst, sonst (kein Ziel hat
  // ein Datum) das am weitesten fortgeschrittene automatisch messbare Ziel.
  const goalPanel = document.getElementById("hub-goal-panel");
  const goalBody = document.getElementById("hub-goal-body");
  try {
    const goalsList = await api("/goals");
    const open = goalsList.filter(g => g.status === "open");
    const withDate = open.filter(g => g.target_date).sort((a, b) => a.target_date.localeCompare(b.target_date));
    const withProgress = open.filter(g => g.progress_percent != null).sort((a, b) => b.progress_percent - a.progress_percent);
    const next = withDate[0] || withProgress[0];
    if (next) {
      goalPanel.classList.remove("hidden");
      const pct = next.progress_percent != null ? Math.min(100, next.progress_percent) : null;
      const dateInfo = next.target_date ? `Zieldatum ${fmtDate(next.target_date)}` : "";
      goalBody.innerHTML = `<button type="button" class="hub-goal-row" data-hub-jump="goals">
        <div class="hub-goal-row-head">
          <strong>${esc(next.title)}</strong>
          <span class="page-sub">${dateInfo}</span>
        </div>
        ${pct != null ? `<div class="budget-track"><div class="budget-fill ${pct >= 50 ? "ok" : "warn"}" style="width:${pct}%"></div></div>
          <span class="page-sub">${pct.toFixed(0)}% erreicht</span>` : ""}
      </button>`;
    } else {
      goalPanel.classList.add("hidden");
    }
  } catch {
    goalPanel.classList.add("hidden");
  }

  // Überfällige Projekte/Lebensbereiche/Wunschliste - dasselbe "seit wie
  // lange nicht bestätigt"-Kriterium wie die jeweiligen Telegram-Erinnerungen
  // (main._scheduled_*_reminder), hier zusätzlich sofort sichtbar statt nur
  // abzuwarten, bis die tägliche Erinnerung kommt.
  const attentionPanel = document.getElementById("hub-attention-panel");
  try {
    const [projects, areas, wishlist] = await Promise.all([
      api("/business-projects").catch(() => []),
      api("/life-areas").catch(() => []),
      api("/wishlist").catch(() => []),
    ]);
    const rows = [];
    projects.filter(projectIsOverdue).forEach(p => rows.push({ icon: "📋", label: p.name, jump: "projects" }));
    areas.filter(lifeAreaIsOverdue).forEach(a => rows.push({ icon: "🎯", label: a.name, jump: "life" }));
    wishlist.filter(wishlistItemIsOverdue).forEach(w => rows.push({ icon: "🛒", label: w.name, jump: "wishlist" }));
    if (rows.length) {
      attentionPanel.classList.remove("hidden");
      document.getElementById("hub-attention-body").innerHTML = rows.map(r => `
        <button type="button" class="hub-list-row" data-hub-jump="${r.jump}">
          <span>${r.icon} ${esc(r.label)}</span>
          <span class="page-sub">ansehen →</span>
        </button>`).join("");
    } else {
      attentionPanel.classList.add("hidden");
    }
  } catch {
    attentionPanel.classList.add("hidden");
  }

  // Nächste fällige Zahlungen - dieselbe (jetzt Kreditraten einschließende)
  // Cashflow-Prognose wie im Abos-Tab, hier nur die ersten paar Termine.
  const upcomingPanel = document.getElementById("hub-upcoming-panel");
  try {
    const forecast = await api("/forecast/cashflow?days=30");
    let events = [...forecast.upcoming_events];
    try {
      const bill = await api("/creditcard-bills/next");
      if (bill && bill.due_date && bill.amount != null) {
        events.push({
          description: `💳 ${bill.account_name}`,
          date: bill.due_date,
          amount: -Math.abs(bill.amount),
        });
      }
    } catch { /* keine Kreditkarten-Rechnung eingerichtet/erkannt - kein Problem */ }
    events.sort((a, b) => a.date.localeCompare(b.date));
    events = events.slice(0, 5);
    if (events.length) {
      upcomingPanel.classList.remove("hidden");
      document.getElementById("hub-upcoming-body").innerHTML = events.map(e => `
        <div class="hub-list-row" style="cursor:default">
          <span>${esc(e.description || "–")}</span>
          <span style="display:flex;align-items:center;gap:10px">
            <span class="page-sub">${fmtDate(e.date)}</span>
            <span class="${e.amount >= 0 ? "row-amount-pos" : "row-amount-neg"}">${eur(e.amount)}</span>
          </span>
        </div>`).join("");
    } else {
      upcomingPanel.classList.add("hidden");
    }
  } catch {
    upcomingPanel.classList.add("hidden");
  }

  const body = document.getElementById("hub-services-body");
  const parts = [];
  try {
    const goalsList = await api("/goals");
    const openGoals = goalsList.filter(g => g.status === "open").length;
    parts.push(`<button type="button" class="integrations-widget-item" data-hub-jump="goals">
      <span class="integrations-widget-icon">🎯</span>
      <div><strong>Ziele &amp; To-Dos</strong><br><span class="page-sub">${openGoals} offene Ziel(e)</span></div>
    </button>`);
  } catch { /* Ziele nicht ladbar - Kachel einfach weglassen */ }

  try {
    const stats = await api("/immich/stats");
    if (stats.available) {
      const gb = (stats.usage_bytes / 1024 / 1024 / 1024).toFixed(1);
      parts.push(`<button type="button" class="integrations-widget-item" data-hub-jump="photos">
        <span class="integrations-widget-icon">📸</span>
        <div><strong>Immich</strong><br><span class="page-sub">${stats.photos.toLocaleString("de-DE")} Fotos, ${gb} GB</span></div>
      </button>`);
    }
  } catch { /* Immich nicht eingerichtet - Kachel einfach weglassen */ }

  try {
    const conns = await api("/ebay/connections");
    const connected = conns.filter(c => c.status === "connected");
    if (connected.length) {
      parts.push(`<button type="button" class="integrations-widget-item" data-hub-jump="settings">
        <span class="integrations-widget-icon">🛒</span>
        <div><strong>eBay</strong><br><span class="page-sub">${connected.length} Verbindung${connected.length !== 1 ? "en" : ""} aktiv</span></div>
      </button>`);
    }
  } catch { /* eBay nicht eingerichtet - Kachel einfach weglassen */ }

  body.innerHTML = parts.length ? parts.join("") : `<p class="page-sub">Noch keine Zusatzdienste eingerichtet - siehe Einstellungen.</p>`;

  // Nächste offene To-Dos - überfällige zuerst, danach nach Fälligkeit,
  // To-Dos ohne Datum zuletzt.
  const todosBody = document.getElementById("hub-todos-body");
  try {
    const todos = (await api("/todos?include_done=false"))
      .sort((a, b) => (a.due_date || "9999") < (b.due_date || "9999") ? -1 : 1)
      .slice(0, 5);
    todosBody.innerHTML = todos.length
      ? todos.map(t => `<button type="button" class="hub-list-row" data-hub-jump="goals">
          <span>${esc(t.title)}</span>
          ${t.due_date ? `<span class="page-sub">${fmtDate(t.due_date)}</span>` : ""}
        </button>`).join("")
      : `<p class="page-sub">Keine offenen To-Dos.</p>`;
  } catch (e) {
    todosBody.innerHTML = `<p class="page-sub">${esc(e.message)}</p>`;
  }

  // Letzte Buchungen - neueste zuerst.
  const txBody = document.getElementById("hub-transactions-body");
  try {
    const tx = (await api("/transactions?hide_transfers=true"))
      .sort((a, b) => b.date.localeCompare(a.date))
      .slice(0, 5);
    txBody.innerHTML = tx.length
      ? tx.map(t => `<button type="button" class="hub-list-row" data-hub-jump="transactions">
          <span>${esc(t.description || "(ohne Beschreibung)")}</span>
          <span class="${t.amount >= 0 ? "row-amount-pos" : "row-amount-neg"}">${eur(t.amount)}</span>
        </button>`).join("")
      : `<p class="page-sub">Noch keine Buchungen.</p>`;
  } catch (e) {
    txBody.innerHTML = `<p class="page-sub">${esc(e.message)}</p>`;
  }
}

document.getElementById("tab-hub").addEventListener("click", e => {
  const jump = e.target.closest("[data-hub-jump]")?.dataset.hubJump;
  if (jump) goToTab(jump);
});

async function loadDashboard() {
  const year = document.getElementById("db-year").value;
  const month = document.getElementById("db-month").value;
  const params = new URLSearchParams({ year });
  if (month) params.set("month", month);

  const data = await api("/dashboard?" + params.toString());
  animateValue(document.getElementById("sum-income"), 0, data.total_income, eur);
  animateValue(document.getElementById("sum-expense"), 0, data.total_expense, eur);
  const balEl = document.getElementById("sum-balance");
  animateValue(balEl, 0, data.balance, eur);
  applySign(balEl, data.balance, balEl.closest(".card"));

  const tbody = document.querySelector("#account-balances tbody");
  tbody.innerHTML = "";
  if (data.account_balances.length === 0) {
    tbody.innerHTML = emptyRow(2, "landmark", "Keine Konten.");
  }
  data.account_balances.forEach(a => {
    const tr = document.createElement("tr");
    const icon = ACCOUNT_TYPE_ICONS[a.type] || "folder";
    tr.innerHTML = `<td><span class="row-name"><span class="row-icon">${svgIcon(icon)}</span>${a.name}</span></td><td class="${a.current_balance >= 0 ? "row-amount-pos" : "row-amount-neg"}">${eur(a.current_balance)}</td>`;
    tbody.appendChild(tr);
  });

  const nwHistory = await api("/net-worth/history?days=365");
  const historyPanel = document.getElementById("balance-history-panel");
  historyPanel.classList.toggle("hidden", nwHistory.points.length < 2);
  if (nwHistory.points.length >= 2) {
    if (balanceHistoryChart) balanceHistoryChart.destroy();
    balanceHistoryChart = new Chart(document.getElementById("chart-balance-history"), {
      type: "line",
      data: {
        labels: nwHistory.points.map(p => fmtDate(p.date)),
        datasets: [{
          data: nwHistory.points.map(p => p.accounts_total),
          borderColor: cssVar("--accent"),
          backgroundColor: cssVar("--accent"),
          tension: 0.3,
          pointRadius: 0,
          fill: false,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: cssVar("--surface-2"),
            borderColor: cssVar("--border-strong"),
            borderWidth: 1,
            titleColor: cssVar("--text"),
            bodyColor: cssVar("--text-secondary"),
            padding: 10,
            cornerRadius: 8,
            displayColors: false,
            callbacks: { label: ctx => eur(ctx.parsed.y) },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            border: { display: false },
            ticks: { color: cssVar("--muted"), font: { size: 11 }, maxTicksLimit: 8 },
          },
          y: {
            grid: { color: cssVar("--border"), drawTicks: false },
            border: { display: false },
            ticks: { color: cssVar("--muted"), font: { size: 11 }, callback: v => eur(v) },
          },
        },
      },
    });
  }

  const recipients = await api("/dashboard/top-recipients?" + params.toString());
  const recipientsPanel = document.getElementById("top-recipients-panel");
  recipientsPanel.classList.toggle("hidden", recipients.length === 0);
  document.getElementById("top-recipients-list").innerHTML = recipients.map(r => `
    <tr>
      <td>${esc(r.description)}</td>
      <td>${r.count}</td>
      <td class="row-amount-neg">${eur(r.total)}</td>
    </tr>`).join("");

  const budgetListEl = document.getElementById("budget-progress-list");
  const budgetPanel = document.getElementById("budget-panel");
  budgetListEl.innerHTML = "";
  if (!data.budgets || data.budgets.length === 0) {
    budgetPanel.style.display = "none";
  } else {
    budgetPanel.style.display = "block";
    data.budgets.forEach(b => {
      const pct = Math.min(100, b.percent);
      const cls = b.percent >= 100 ? "over" : b.percent >= 80 ? "warn" : "ok";
      // Nur beim laufenden Monat vorhanden - zeigt frühzeitig (nicht erst am
      // Monatsende), ob das aktuelle Tempo übers Limit tragen würde.
      const projectionHint = (b.projected_total != null && b.projected_total > b.limit)
        ? `<span class="budget-projection">bei diesem Tempo: ~${eur(b.projected_total)} am Monatsende</span>`
        : "";
      const row = document.createElement("div");
      row.className = "budget-row";
      row.innerHTML = `
        <div class="budget-row-head">
          <span class="budget-name"><span class="row-icon"><svg class="panel-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none"/></svg></span>${b.category_name}</span>
          <span class="budget-amounts">${eur(b.spent)} von ${eur(b.limit)} (${b.percent.toFixed(0)}%)</span>
        </div>
        <div class="budget-track"><div class="budget-fill ${cls}" style="width:${pct}%"></div></div>
        ${projectionHint}`;
      budgetListEl.appendChild(row);
    });
  }

  const anomalies = await api("/transactions/spending-anomalies");
  const anomalyPanel = document.getElementById("spending-anomaly-panel");
  const anomalyListEl = document.getElementById("spending-anomaly-list");
  anomalyPanel.classList.toggle("hidden", anomalies.length === 0);
  anomalyListEl.innerHTML = anomalies.map(a => `
    <div class="budget-row">
      <div class="budget-row-head">
        <span class="budget-name"><span class="row-icon"><svg class="panel-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="13" width="4" height="7" rx="1"/><rect x="10" y="8" width="4" height="12" rx="1"/><rect x="16" y="4" width="4" height="16" rx="1"/></svg></span>${esc(a.category_name)}</span>
        <span class="budget-amounts">${eur(a.current_spent)} bisher – Ø sonst ${eur(a.avg_prior_months)}/Monat</span>
      </div>
      <span class="budget-projection">bei diesem Tempo: ~${eur(a.projected_spent)} am Monatsende (+${a.deviation_pct.toFixed(0)}%)</span>
    </div>`).join("");

  chartInstance = renderCategoryPieChart(
    "chart-categories", chartInstance,
    data.by_category.map(c => c.category_name), data.by_category.map(c => Math.abs(c.total)),
  );

  loadIntegrationsWidget();
}

// Bewusst kein neuer eigener "Hub" mit dienstübergreifenden Kacheln - dafür
// gibt es noch keine abgestimmte Entscheidung. Stattdessen ein kleines,
// zurückhaltendes Widget auf dem bestehenden Dashboard, das nur zeigt, was
// tatsächlich verbunden ist, und sich komplett versteckt, wenn nichts davon
// eingerichtet ist.
async function loadIntegrationsWidget() {
  const widget = document.getElementById("integrations-widget");
  const body = document.getElementById("integrations-widget-body");
  const parts = [];

  try {
    const stats = await api("/immich/stats");
    if (stats.available) {
      const gb = (stats.usage_bytes / 1024 / 1024 / 1024).toFixed(1);
      parts.push(`<div class="integrations-widget-item">
        <span class="integrations-widget-icon">📸</span>
        <div><strong>Immich</strong><br>
        <span class="page-sub">${stats.photos.toLocaleString("de-DE")} Fotos, ${stats.videos.toLocaleString("de-DE")} Videos, ${gb} GB</span></div>
      </div>`);
    }
  } catch { /* Immich nicht eingerichtet oder nicht erreichbar - Widget lässt es einfach weg. */ }

  try {
    const conns = await api("/ebay/connections");
    const connected = conns.filter(c => c.status === "connected");
    if (connected.length) {
      const lastSync = connected
        .map(c => c.last_sync_at)
        .filter(Boolean)
        .sort()
        .pop();
      parts.push(`<div class="integrations-widget-item">
        <span class="integrations-widget-icon">🛒</span>
        <div><strong>eBay</strong><br>
        <span class="page-sub">${connected.length} Verbindung${connected.length !== 1 ? "en" : ""} aktiv${lastSync ? `, zuletzt synchronisiert ${new Date(lastSync).toLocaleString("de-DE")}` : ""}</span></div>
      </div>`);
    }
  } catch { /* eBay nicht eingerichtet - Widget lässt es einfach weg. */ }

  if (!parts.length) {
    widget.classList.add("hidden");
    return;
  }
  body.innerHTML = parts.join("");
  widget.classList.remove("hidden");
}

document.getElementById("db-refresh").addEventListener("click", loadDashboard);
document.getElementById("cat-filter-btn").addEventListener("click", loadCategories);

// ================= GESCHÄFTLICH (Filter auf is_business-Konten) =================
let bizChartInstance = null;

async function loadBusinessTab() {
  if (!accountsCache.length) await loadAccounts();
  const hasBusinessAccount = accountsCache.some(a => a.is_business);
  document.getElementById("biz-empty-hint").classList.toggle("hidden", hasBusinessAccount);
  document.getElementById("biz-content").classList.toggle("hidden", !hasBusinessAccount);
  if (!hasBusinessAccount) return;

  const yearEl = document.getElementById("biz-year");
  if (!yearEl.value) yearEl.value = new Date().getFullYear();
  const year = yearEl.value;
  const month = document.getElementById("biz-month").value;
  const params = new URLSearchParams({ year });
  if (month) params.set("month", month);

  const data = await api("/business/summary?" + params.toString());
  animateValue(document.getElementById("biz-sum-income"), 0, data.total_income, eur);
  animateValue(document.getElementById("biz-sum-expense"), 0, data.total_expense, eur);
  const balEl = document.getElementById("biz-sum-balance");
  animateValue(balEl, 0, data.balance, eur);
  applySign(balEl, data.balance, balEl.closest(".card"));

  const tbody = document.querySelector("#biz-account-balances tbody");
  tbody.innerHTML = "";
  data.account_balances.forEach(a => {
    const tr = document.createElement("tr");
    const icon = ACCOUNT_TYPE_ICONS[a.type] || "folder";
    tr.innerHTML = `<td><span class="row-name"><span class="row-icon">${svgIcon(icon)}</span>${a.name}</span></td><td class="${a.current_balance >= 0 ? "row-amount-pos" : "row-amount-neg"}">${eur(a.current_balance)}</td>`;
    tbody.appendChild(tr);
  });

  const ctx = document.getElementById("chart-biz-categories");
  const labels = data.by_category.map(c => c.category_name);
  const values = data.by_category.map(c => Math.abs(c.total));
  const catColors = getCatColors();
  const colors = labels.map((_, i) => catColors[i % catColors.length]);
  if (bizChartInstance) bizChartInstance.destroy();
  bizChartInstance = new Chart(ctx, {
    type: "bar",
    data: { labels, datasets: [{ data: values, backgroundColor: colors, borderRadius: 4, borderSkipped: false, maxBarThickness: 22 }] },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: cssVar("--surface-2"), borderColor: cssVar("--border-strong"), borderWidth: 1,
          titleColor: cssVar("--text"), bodyColor: cssVar("--text-secondary"), padding: 10, cornerRadius: 8,
          displayColors: false, callbacks: { label: ctx => eur(ctx.parsed.x) },
        },
      },
      scales: {
        x: { grid: { color: cssVar("--border"), drawTicks: false }, border: { display: false }, ticks: { color: cssVar("--muted"), font: { size: 11 }, callback: v => eur(v) } },
        y: { grid: { display: false }, border: { display: false }, ticks: { color: cssVar("--text-secondary"), font: { size: 12 } } },
      },
    },
  });
}

document.getElementById("biz-refresh").addEventListener("click", loadBusinessTab);

// ================= SCHULDEN =================
let debtsCache = [];
let debtBalanceChart = null;
let currentDebtId = null;
let editingPaymentId = null;

// Leeres Zahlenfeld heißt "nicht gesetzt" - parseFloat("") wäre NaN und würde
// vom Backend als Validierungsfehler zurückkommen.
function numOrNull(id) {
  const v = document.getElementById(id).value;
  return v === "" ? null : parseFloat(v);
}

const DEBT_KIND_LABELS = {
  annuitaeten: "Annuitätendarlehen",
  raten: "Ratenkredit",
  endfaellig: "Endfällig",
  dispo: "Dispo / Kreditlinie",
  privat: "Privatdarlehen",
};

async function loadDebtsTab() {
  loadGlobalTopbar();
  debtsCache = await api("/debts");
  const summary = await api("/debts/summary");
  if (!accountsCache.length) await loadAccounts();

  document.getElementById("debt-summary-cards").innerHTML = `
    <div class="card card-neg">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><path d="M4 7H20M4 12H20M4 17H14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></div>
      <div><h3>Offene Restschuld</h3><p class="neg">${eur(summary.total_balance)}</p></div>
    </div>
    <div class="card">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><rect x="3" y="5" width="18" height="16" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M3 10H21M8 3V7M16 3V7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></div>
      <div><h3>Monatliche Belastung</h3><p>${eur(summary.monthly_burden)}</p></div>
    </div>
    <div class="card">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.8"/><path d="M12 7v5l3 2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></div>
      <div><h3>Gezahlte Zinsen</h3><p>${eur(summary.total_interest_paid)}</p></div>
    </div>`;

  const active = debtsCache.filter(d => d.status === "active");
  const done = debtsCache.filter(d => d.status !== "active");

  const activeGrid = document.getElementById("debt-active-grid");
  activeGrid.innerHTML = active.length
    ? ""
    : `<div class="empty-state"><span class="empty-icon">${svgIcon("landmark")}</span><span>Keine laufenden Kredite. Gut so.</span></div>`;
  active.forEach(d => activeGrid.appendChild(renderDebtCard(d)));

  const doneGrid = document.getElementById("debt-done-grid");
  doneGrid.innerHTML = done.length
    ? ""
    : `<div class="empty-state"><span class="empty-icon">${svgIcon("check-circle")}</span><span>Noch nichts abbezahlt.</span></div>`;
  done.forEach(d => doneGrid.appendChild(renderDebtCard(d)));
  document.getElementById("debt-done-count").textContent = done.length;
}

function renderDebtCard(d) {
  const card = document.createElement("div");
  card.className = "goal-card" + (d.status !== "active" ? " completed" : "");
  const meta = [DEBT_KIND_LABELS[d.kind] || d.kind];
  if (d.lender) meta.push(esc(d.lender));
  if (d.monthly_payment) meta.push(`${eur(d.monthly_payment)}/Monat`);
  if (d.interest_rate_percent) meta.push(`${d.interest_rate_percent} % p.a.`);

  card.innerHTML = `
    <div class="goal-card-head">
      <h4>${esc(d.name)}</h4>
      <span class="goal-chip">${d.paid_off_percent.toFixed(0)} % getilgt</span>
    </div>
    <p class="debt-balance">${eur(d.current_balance)}<span class="debt-balance-sub"> von ${eur(d.original_amount)}</span></p>
    <div class="budget-track"><div class="goal-fill${d.status !== "active" ? " done" : ""}" style="width:${Math.min(100, d.paid_off_percent)}%"></div></div>
    <p class="goal-meta">${meta.join(" · ")}</p>
    <button class="link-btn" onclick="openDebtModal(${d.id})">Details &amp; Zahlungen</button>`;
  return card;
}

document.getElementById("debt-done-toggle").addEventListener("click", () => {
  const grid = document.getElementById("debt-done-grid");
  grid.classList.toggle("hidden");
  document.querySelector("#debt-done-toggle .goal-section-caret").textContent =
    grid.classList.contains("hidden") ? "▶" : "▼";
});

window.openDebtModal = async (debtId = null) => {
  if (!accountsCache.length) await loadAccounts();
  currentDebtId = debtId;
  editingPaymentId = null;

  document.getElementById("debt-account").innerHTML = '<option value="">–</option>'
    + accountsCache.map(a => `<option value="${a.id}">${esc(a.name)}</option>`).join("");

  const d = debtId ? await api(`/debts/${debtId}`) : null;
  document.getElementById("debt-modal-title").textContent = d ? esc(d.name) : "Neuer Kredit";
  document.getElementById("debt-id").value = d ? d.id : "";
  document.getElementById("debt-name").value = d?.name || "";
  document.getElementById("debt-kind").value = d?.kind || "annuitaeten";
  document.getElementById("debt-lender").value = d?.lender || "";
  document.getElementById("debt-original").value = d?.original_amount ?? "";
  document.getElementById("debt-rate").value = d?.interest_rate_percent ?? 0;
  document.getElementById("debt-payment").value = d?.monthly_payment ?? "";
  document.getElementById("debt-start").value = d?.start_date || "";
  document.getElementById("debt-end").value = d?.planned_end_date || "";
  document.getElementById("debt-account").value = d?.account_id || "";
  document.getElementById("debt-notes").value = d?.notes || "";
  document.getElementById("debt-fixed-until").value = d?.interest_fixed_until || "";
  document.getElementById("debt-followup-rate").value = d?.follow_up_interest_rate_percent ?? "";
  document.getElementById("debt-monthly-fee").value = d?.monthly_fee ?? "";
  document.getElementById("debt-insurance").value = d?.monthly_insurance ?? "";
  document.getElementById("debt-upfront").value = d?.upfront_fees ?? "";
  document.getElementById("debt-undisbursed").value = d?.undisbursed_amount ?? "";
  document.getElementById("debt-commitment-rate").value = d?.commitment_rate_percent ?? "";
  document.getElementById("debt-commitment-free").value = d?.commitment_free_months ?? "";
  document.getElementById("debt-delete").classList.toggle("hidden", !d);
  document.getElementById("debt-detail").classList.toggle("hidden", !d);
  document.getElementById("dp-date").value = new Date().toISOString().slice(0, 10);

  if (d) await loadDebtDetail(d);
  document.getElementById("debt-modal").classList.remove("hidden");
};

async function loadDebtDetail(d) {
  const [payments, schedule] = await Promise.all([
    api(`/debts/${d.id}/payments`),
    api(`/debts/${d.id}/schedule`),
  ]);

  const cards = [
    `<div class="card"><div><h3>Restschuld</h3><p class="neg">${eur(d.current_balance)}</p></div></div>`,
    `<div class="card"><div><h3>Monatliche Belastung</h3><p>${eur(d.monthly_total_burden)}</p></div></div>`,
    `<div class="card"><div><h3>Zinsen künftig</h3><p>${d.projected_remaining_interest != null ? eur(d.projected_remaining_interest) : "–"}</p></div></div>`,
    `<div class="card"><div><h3>Voraussichtlich frei</h3><p>${d.projected_end_date ? fmtDate(d.projected_end_date) : "–"}</p></div></div>`,
  ];
  const sideCosts = (d.monthly_fee || 0) + (d.monthly_insurance || 0) + (d.upfront_fees || 0);
  if (sideCosts > 0 || d.projected_remaining_fees) {
    cards.push(`<div class="card"><div><h3>Neben&shy;kosten künftig</h3><p>${eur(d.projected_remaining_fees || 0)}</p></div></div>`);
  }
  if (d.monthly_commitment_interest > 0) {
    cards.push(`<div class="card card-neg"><div><h3>Bereitstellungszins</h3><p class="neg">${eur(d.monthly_commitment_interest)}/Monat</p></div></div>`);
  }
  document.getElementById("debt-detail-cards").innerHTML = cards.join("");

  // Die Restschuld bei Ablauf der Zinsbindung ist die Zahl, die für die
  // Anschlussfinanzierung zählt - die gehört prominent hin, nicht in die Tabelle.
  const notes = [];
  if (d.balance_at_fixed_interest_end != null) {
    notes.push(`🔒 Zinsbindung bis ${fmtDate(d.interest_fixed_until)} – Restschuld dann voraussichtlich `
      + `<strong>${eur(d.balance_at_fixed_interest_end)}</strong>. Ab da rechnet die Prognose mit `
      + `${d.follow_up_interest_rate_percent != null ? d.follow_up_interest_rate_percent + " %" : "unverändertem Zinssatz"} (Annahme).`);
  }
  if (schedule.note) notes.push("⚠️ " + esc(schedule.note));
  const noteEl = document.getElementById("debt-projection-note");
  noteEl.innerHTML = notes.join("<br>");
  noteEl.classList.toggle("hidden", !notes.length);

  // Zahlungs-Ledger
  const tbody = document.getElementById("debt-payment-list");
  tbody.innerHTML = payments.length ? "" : emptyRow(7, "coins", "Noch keine Zahlungen erfasst.");
  payments.forEach(p => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${fmtDate(p.date)}${p.is_extra_repayment ? ' <span class="goal-chip">Sonder</span>' : ""}</td>
      <td>${eur(p.total_amount)}</td>
      <td>${eur(p.interest_amount)}${p.interest_is_manual ? " ✏️" : ""}</td>
      <td>${p.fee_amount ? eur(p.fee_amount) : "–"}</td>
      <td>${eur(p.principal_amount)}</td>
      <td>${eur(p.balance_after)}</td>
      <td>${esc(p.notes || "")}</td>
      <td>
        <button class="link-btn" onclick="editDebtPayment(${p.id}, '${p.date}', ${p.total_amount}, ${p.interest_is_manual ? p.interest_amount : "null"}, ${p.fee_amount || 0}, ${p.is_extra_repayment}, ${JSON.stringify(p.notes || "")})">Bearbeiten</button>
        <button class="link-btn" onclick="deleteDebtPayment(${p.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });

  // Tilgungsplan
  const schedBody = document.getElementById("debt-schedule-list");
  schedBody.innerHTML = schedule.rows.length ? "" : emptyRow(7, "calendar", schedule.note || "Kein Tilgungsplan berechenbar.");
  let markedSwitch = false;
  schedule.rows.forEach(r => {
    const tr = document.createElement("tr");
    // Erste Zeile nach Ablauf der Zinsbindung markieren - dort springt der Zins.
    if (r.after_fixed_interest && !markedSwitch) {
      tr.className = "debt-rate-switch";
      markedSwitch = true;
    }
    tr.innerHTML = `<td>${r.month_index}</td><td>${fmtDate(r.date)}</td><td>${eur(r.payment)}</td>
      <td>${eur(r.interest)}</td><td>${r.fee ? eur(r.fee) : "–"}</td><td>${eur(r.principal)}</td><td>${eur(r.balance_after)}</td>`;
    schedBody.appendChild(tr);
  });

  renderDebtBalanceChart(d, payments, schedule.rows);
}

function renderDebtBalanceChart(d, payments, scheduleRows) {
  if (debtBalanceChart) debtBalanceChart.destroy();
  const ctx = document.getElementById("chart-debt-balance");
  if (!payments.length && !scheduleRows.length) {
    ctx.getContext("2d").clearRect(0, 0, ctx.width, ctx.height);
    return;
  }
  // Ist und Prognose in einem Chart: die Ist-Reihe endet dort, wo die Prognose
  // beginnt, damit der Knick durch Sondertilgungen sichtbar wird.
  const istLabels = payments.map(p => fmtDate(p.date));
  const planLabels = scheduleRows.map(r => fmtDate(r.date));
  const labels = [...istLabels, ...planLabels];
  debtBalanceChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Bisher gezahlt",
          data: [...payments.map(p => p.balance_after), ...scheduleRows.map(() => null)],
          borderColor: cssVar("--accent-strong"), borderWidth: 2, tension: 0.2, pointRadius: 2, fill: false,
        },
        {
          label: "Prognose",
          data: [...payments.map(() => null), ...scheduleRows.map(r => r.balance_after)],
          borderColor: cssVar("--muted"), borderDash: [5, 5], borderWidth: 2, tension: 0.2, pointRadius: 0, fill: false,
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, spanGaps: false,
      plugins: {
        legend: { labels: { color: cssVar("--text-secondary"), boxWidth: 12 } },
        tooltip: { callbacks: { label: c => `${c.dataset.label}: ${eur(c.parsed.y)}` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: cssVar("--muted"), font: { size: 10 }, maxTicksLimit: 10 } },
        y: { grid: { color: cssVar("--border") }, ticks: { color: cssVar("--text-secondary"), font: { size: 11 }, callback: v => eur(v) } },
      },
    },
  });
}

window.editDebtPayment = (id, date, amount, interest, fee, isExtra, notes) => {
  editingPaymentId = id;
  document.getElementById("debt-payment-id").value = id;
  document.getElementById("dp-date").value = date;
  document.getElementById("dp-amount").value = amount;
  document.getElementById("dp-interest").value = interest ?? "";
  document.getElementById("dp-fee").value = fee || "";
  document.getElementById("dp-extra").checked = isExtra;
  document.getElementById("dp-notes").value = notes || "";
  document.getElementById("dp-submit").textContent = "Speichern";
  document.getElementById("dp-cancel").style.display = "";
};

function resetPaymentForm() {
  editingPaymentId = null;
  document.getElementById("debt-payment-form").reset();
  document.getElementById("dp-date").value = new Date().toISOString().slice(0, 10);
  document.getElementById("dp-submit").textContent = "Hinzufügen";
  document.getElementById("dp-cancel").style.display = "none";
}
document.getElementById("dp-cancel").addEventListener("click", resetPaymentForm);

window.deleteDebtPayment = async id => {
  if (!confirm("Zahlung wirklich löschen?")) return;
  await api(`/debts/${currentDebtId}/payments/${id}`, { method: "DELETE" });
  await refreshDebtModal();
};

document.getElementById("debt-payment-form").addEventListener("submit", async e => {
  e.preventDefault();
  const interestRaw = document.getElementById("dp-interest").value;
  const payload = {
    date: document.getElementById("dp-date").value,
    total_amount: parseFloat(document.getElementById("dp-amount").value),
    interest_amount: interestRaw === "" ? null : parseFloat(interestRaw),
    fee_amount: numOrNull("dp-fee"),
    is_extra_repayment: document.getElementById("dp-extra").checked,
    notes: document.getElementById("dp-notes").value || null,
  };
  await api(
    editingPaymentId ? `/debts/${currentDebtId}/payments/${editingPaymentId}` : `/debts/${currentDebtId}/payments`,
    { method: editingPaymentId ? "PUT" : "POST", body: JSON.stringify(payload) }
  );
  resetPaymentForm();
  await refreshDebtModal();
});

async function refreshDebtModal() {
  const d = await api(`/debts/${currentDebtId}`);
  await loadDebtDetail(d);
  loadDebtsTab();
}

function closeDebtModal() {
  document.getElementById("debt-modal").classList.add("hidden");
  currentDebtId = null;
  resetPaymentForm();
}
document.getElementById("debt-new-btn").addEventListener("click", () => openDebtModal(null));
document.getElementById("debt-modal-close").addEventListener("click", closeDebtModal);
document.getElementById("debt-cancel").addEventListener("click", closeDebtModal);

document.getElementById("debt-form").addEventListener("submit", async e => {
  e.preventDefault();
  const id = document.getElementById("debt-id").value;
  const payload = {
    name: document.getElementById("debt-name").value,
    kind: document.getElementById("debt-kind").value,
    lender: document.getElementById("debt-lender").value || null,
    original_amount: parseFloat(document.getElementById("debt-original").value),
    interest_rate_percent: parseFloat(document.getElementById("debt-rate").value) || 0,
    monthly_payment: parseFloat(document.getElementById("debt-payment").value) || null,
    start_date: document.getElementById("debt-start").value || null,
    planned_end_date: document.getElementById("debt-end").value || null,
    account_id: parseInt(document.getElementById("debt-account").value) || null,
    notes: document.getElementById("debt-notes").value || null,
    interest_fixed_until: document.getElementById("debt-fixed-until").value || null,
    follow_up_interest_rate_percent: numOrNull("debt-followup-rate"),
    monthly_fee: numOrNull("debt-monthly-fee"),
    monthly_insurance: numOrNull("debt-insurance"),
    upfront_fees: numOrNull("debt-upfront"),
    undisbursed_amount: numOrNull("debt-undisbursed"),
    commitment_rate_percent: numOrNull("debt-commitment-rate"),
    commitment_free_months: numOrNull("debt-commitment-free"),
  };
  const saved = await api(id ? `/debts/${id}` : "/debts", {
    method: id ? "PUT" : "POST",
    body: JSON.stringify(payload),
  });
  loadDebtsTab();
  // Nach dem Anlegen direkt in die Detailansicht, damit Zahlungen erfassbar sind.
  await openDebtModal(saved.id);
});

document.getElementById("debt-delete").addEventListener("click", async () => {
  const id = document.getElementById("debt-id").value;
  if (!id || !confirm("Kredit inklusive aller erfassten Zahlungen wirklich löschen?")) return;
  await api(`/debts/${id}`, { method: "DELETE" });
  closeDebtModal();
  loadDebtsTab();
});

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

// ================= ZIELE =================
let goalsCache = [];
let goalHistoryChart = null;

const GOAL_METRIC_LABELS = {
  net_worth: "Gesamtvermögen",
  account_balance: "Kontostand",
  investment_value: "Depotwert",
  savings_rate: "Sparrate pro Monat",
  custom_category_sum: "Summe einer Kategorie",
  debt_balance: "Restschuld eines Kredits",
};
const GOAL_METRIC_HINTS = {
  net_worth: "Konten + Investments zusammen.",
  account_balance: "Saldo eines einzelnen Kontos.",
  investment_value: "Aktueller Wert der Positionen, optional nur einer Anlageklasse.",
  savings_rate: "Zählt abgeschlossene Monate in Folge, in denen Einnahmen minus Ausgaben den Zielwert erfüllen. Der laufende Monat zählt noch nicht mit.",
  custom_category_sum: "Summe aller Buchungen einer Kategorie, optional nur der letzten Monate.",
  debt_balance: "Offene Restschuld eines Kredits aus dem Schulden-Tab. Mit „höchstens“ nutzen, Zielwert 0 = komplett abbezahlt.",
};

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function goalValueText(g) {
  if (g.current_value == null) return "";
  if (g.value_unit === "months") {
    return `${g.current_value} von ${g.target_value} Monaten`;
  }
  return `${eur(g.current_value)} von ${eur(g.target_value)}`;
}

// Ziele mit dieser Kategorie gehören in den eigenen Schweiz-Tab statt in die
// normale Ziele-Liste - reine Kategorie-Filterung auf demselben /goals-Datenbestand,
// keine eigene Tabelle (analog zum Geschäftlich-Tab, der auch nur eine gefilterte
// Sicht auf dieselben Konten ist).
const SCHWEIZ_GOAL_CATEGORY = "Schweiz";
function isSchweizGoal(g) {
  // Exaktes "Schweiz" ODER "Schweiz: <Unterthema>" (siehe scripts/seed_schweiz_goals.py,
  // das feinere Kategorien wie "Schweiz: Gewerbe" für die Roadmap-Farbcodierung braucht).
  const cat = (g.category || "").trim().toLowerCase();
  const prefix = SCHWEIZ_GOAL_CATEGORY.toLowerCase();
  return cat === prefix || cat.startsWith(prefix + ":");
}

async function loadGoalsTab() {
  goalsCache = await api("/goals");
  if (!accountsCache.length) await loadAccounts();

  const relevant = goalsCache.filter(g => !isSchweizGoal(g));
  const open = relevant.filter(g => g.status === "open");
  const done = relevant.filter(g => g.status !== "open");
  const newlyReached = goalsCache.filter(g => !g.completion_seen).length;
  const nextDue = open
    .filter(g => g.target_date)
    .sort((a, b) => a.target_date.localeCompare(b.target_date))[0];

  document.getElementById("goal-summary-cards").innerHTML = `
    <div class="card">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="8.5" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.8"/></svg></div>
      <div><h3>Offene Ziele</h3><p>${open.length}</p></div>
    </div>
    <div class="card card-pos">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><path d="M5 12.5L10 17.5L19 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
      <div><h3>Erreicht</h3><p class="pos">${relevant.filter(g => g.status === "completed").length}</p></div>
    </div>
    <div class="card">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><rect x="3" y="5" width="18" height="16" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M3 10H21M8 3V7M16 3V7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></div>
      <div><h3>Nächste Frist</h3><p>${nextDue ? fmtDate(nextDue.target_date) : "–"}</p></div>
    </div>`;

  const openGrid = document.getElementById("goal-open-grid");
  openGrid.innerHTML = open.length
    ? ""
    : `<div class="empty-state"><span class="empty-icon">${svgIcon("target")}</span><span>Noch keine offenen Ziele. Leg oben rechts eins an.</span></div>`;
  open.forEach(g => openGrid.appendChild(renderGoalCard(g)));

  const doneGrid = document.getElementById("goal-done-grid");
  doneGrid.innerHTML = done.length
    ? ""
    : `<div class="empty-state"><span class="empty-icon">${svgIcon("check-circle")}</span><span>Noch nichts abgeschlossen.</span></div>`;
  done.forEach(g => doneGrid.appendChild(renderGoalCard(g)));
  document.getElementById("goal-done-count").textContent = done.length;
  renderGoalsRoadmap(relevant, "goal-roadmap-list", "goal-roadmap-legend");

  // Die Karten zeigen die "Neu erreicht"-Markierung noch in diesem Durchgang,
  // der Zähler in der Navigation ist mit dem Ansehen aber erledigt.
  if (newlyReached) {
    await api("/goals/mark-seen", { method: "POST" });
    goalsCache.forEach(g => { g.completion_seen = true; });
  }
  updateGoalsBadge(0);
  loadTodos();
  loadCalendarTab();
}

async function loadSchweizGoalsTab() {
  if (!goalsCache.length) goalsCache = await api("/goals");
  if (!accountsCache.length) await loadAccounts();

  const schweizGoals = goalsCache.filter(isSchweizGoal);
  const open = schweizGoals.filter(g => g.status === "open");
  const done = schweizGoals.filter(g => g.status !== "open");
  const nextDue = open
    .filter(g => g.target_date)
    .sort((a, b) => a.target_date.localeCompare(b.target_date))[0];

  document.getElementById("schweiz-summary-cards").innerHTML = `
    <div class="card">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="8.5" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.8"/></svg></div>
      <div><h3>Offene Ziele</h3><p>${open.length}</p></div>
    </div>
    <div class="card card-pos">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><path d="M5 12.5L10 17.5L19 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
      <div><h3>Erreicht</h3><p class="pos">${schweizGoals.filter(g => g.status === "completed").length}</p></div>
    </div>
    <div class="card">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><rect x="3" y="5" width="18" height="16" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M3 10H21M8 3V7M16 3V7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></div>
      <div><h3>Nächste Frist</h3><p>${nextDue ? fmtDate(nextDue.target_date) : "–"}</p></div>
    </div>`;

  const openGrid = document.getElementById("schweiz-open-grid");
  openGrid.innerHTML = open.length
    ? ""
    : `<div class="empty-state"><span class="empty-icon">${svgIcon("target")}</span><span>Noch keine offenen Schweiz-Ziele. Leg oben rechts eins an.</span></div>`;
  open.forEach(g => openGrid.appendChild(renderGoalCard(g)));

  const doneGrid = document.getElementById("schweiz-done-grid");
  doneGrid.innerHTML = done.length
    ? ""
    : `<div class="empty-state"><span class="empty-icon">${svgIcon("check-circle")}</span><span>Noch nichts abgeschlossen.</span></div>`;
  done.forEach(g => doneGrid.appendChild(renderGoalCard(g)));
  document.getElementById("schweiz-done-count").textContent = done.length;
  renderGoalsRoadmap(schweizGoals, "schweiz-roadmap-list", "schweiz-roadmap-legend");

  await loadCostOfLivingComparison();
  loadSavingsGap(open.filter(g => g.target_date));
}

// ---------- Lebenshaltungskosten-Vergleich (Schweiz-Tab) ----------
// Reine Was-waere-wenn-Rechnung auf Basis der echten Ausgaben der letzten 6
// Monate (wiederverwendet dieselben Trend-Daten wie der Kategorien-Tab) - kein
// echter Laender-Vergleichsindex, nur ein vom Nutzer selbst einstellbarer
// Aufschlag pro Kategorie. Bewusst lokal gespeichert (kein Backend-Feld):
// das ist eine persoenliche Annahme zum Herumspielen, keine echte Buchung.
function getColMarkups() {
  try { return JSON.parse(localStorage.getItem("colMarkups") || "{}"); } catch (e) { return {}; }
}
function setColMarkup(categoryName, percent) {
  const m = getColMarkups();
  m[categoryName] = percent;
  localStorage.setItem("colMarkups", JSON.stringify(m));
}

let colAverages = [];

async function loadCostOfLivingComparison() {
  const trend = await api("/categories/trend?months=6");
  colAverages = trend.series.map(s => ({
    category_name: s.category_name,
    avg_monthly: s.points.reduce((a, b) => a + b, 0) / (trend.months.length || 1),
  })).filter(c => c.avg_monthly > 0.5); // Rauschen (Cent-Buchungen) nicht mit anzeigen

  renderCostOfLivingComparison();
}

// Von der Spardistanz-Rechnung (loadSavingsGap) mitgenutzt, damit beide
// Panels bei einer Aufschlag-Änderung dieselbe Zahl zugrunde legen.
function schweizMonthlyEstimate() {
  const markups = getColMarkups();
  const defaultMarkup = parseFloat(document.getElementById("col-default-markup")?.value) || 0;
  let totalCurrent = 0, totalSchweiz = 0;
  colAverages.forEach(c => {
    const markup = markups[c.category_name] ?? defaultMarkup;
    totalCurrent += c.avg_monthly;
    totalSchweiz += c.avg_monthly * (1 + markup / 100);
  });
  return { totalCurrent, totalSchweiz };
}

function renderCostOfLivingComparison() {
  const markups = getColMarkups();
  const defaultMarkup = parseFloat(document.getElementById("col-default-markup").value) || 0;

  let totalCurrent = 0, totalSchweiz = 0;
  const rows = colAverages.map(c => {
    const markup = markups[c.category_name] ?? defaultMarkup;
    const schweiz = c.avg_monthly * (1 + markup / 100);
    totalCurrent += c.avg_monthly;
    totalSchweiz += schweiz;
    return { ...c, markup, schweiz };
  });

  document.getElementById("col-summary-cards").innerHTML = `
    <div class="card">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><rect x="3" y="5" width="18" height="16" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M3 10H21M8 3V7M16 3V7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></div>
      <div><h3>Aktuell (Ø/Monat)</h3><p>${eur(totalCurrent)}</p></div>
    </div>
    <div class="card card-neg">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.8"/><path d="M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18M3 12h18" stroke="currentColor" stroke-width="1.8"/></svg></div>
      <div><h3>Geschätzt Schweiz (Ø/Monat)</h3><p class="neg">${eur(totalSchweiz)}</p></div>
    </div>
    <div class="card">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><path d="M12 19V5M12 5L6 11M12 5L18 11" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
      <div><h3>Differenz/Monat</h3><p>${eur(totalSchweiz - totalCurrent)} (${totalCurrent ? ((totalSchweiz / totalCurrent - 1) * 100).toFixed(0) : 0}%)</p></div>
    </div>`;

  const tbody = document.getElementById("col-list");
  tbody.innerHTML = rows.length
    ? rows.map(r => `
      <tr>
        <td>${esc(r.category_name)}</td>
        <td>${eur(r.avg_monthly)}</td>
        <td><input type="number" class="col-markup-input" data-cat="${esc(r.category_name)}" value="${r.markup}" style="width:70px"></td>
        <td class="row-amount-neg">${eur(r.schweiz)}</td>
      </tr>`).join("")
    : emptyRow(4, "trending-up", "Noch nicht genug Ausgaben der letzten 6 Monate für eine Hochrechnung.");

  tbody.querySelectorAll(".col-markup-input").forEach(input => {
    input.addEventListener("change", () => {
      setColMarkup(input.dataset.cat, parseFloat(input.value) || 0);
      renderCostOfLivingComparison();
      renderSavingsGap();
    });
  });
}

document.getElementById("col-default-markup").addEventListener("change", () => {
  renderCostOfLivingComparison();
  renderSavingsGap();
});
document.getElementById("col-apply-default").addEventListener("click", () => {
  const defaultMarkup = parseFloat(document.getElementById("col-default-markup").value) || 0;
  colAverages.forEach(c => setColMarkup(c.category_name, defaultMarkup));
  renderCostOfLivingComparison();
  renderSavingsGap();
});

// ---------- Spardistanz zum Umzug (Schweiz-Tab) ----------
// Verbindet zwei bereits vorhandene Bausteine: den Zeitstrahl (Meilenstein +
// Zieldatum) und die Lebenshaltungskosten-Schätzung (monatlicher Bedarf in
// der Schweiz). Zielbetrag = geschätzter Schweiz-Monatsbedarf * Puffer-Monate,
// verglichen mit dem aktuellen liquiden Kontostand (ohne Investments - die
// sind im Ernstfall nicht sofort ohne Verlustrisiko verfuegbar, gleiche
// Logik wie die Notgroschen-Reichweite auf dem Hub).
let sdMilestones = [];

function loadSavingsGap(milestoneGoals) {
  sdMilestones = milestoneGoals;
  const select = document.getElementById("sd-milestone");
  if (milestoneGoals.length === 0) {
    select.innerHTML = '<option value="">Kein datiertes offenes Ziel vorhanden</option>';
    document.getElementById("sd-summary-cards").innerHTML = "";
    document.getElementById("sd-explainer").textContent = "";
    return;
  }
  const sorted = [...milestoneGoals].sort((a, b) => a.target_date.localeCompare(b.target_date));
  const defaultGoal = sorted.find(g => /umzug/i.test(g.title)) || sorted[0];
  select.innerHTML = sorted.map(g =>
    `<option value="${g.id}" ${g.id === defaultGoal.id ? "selected" : ""}>${esc(g.title)} (${fmtDate(g.target_date)})</option>`
  ).join("");
  renderSavingsGap();
}

async function renderSavingsGap() {
  if (!sdMilestones.length) return;
  const selectedId = parseInt(document.getElementById("sd-milestone").value);
  const goal = sdMilestones.find(g => g.id === selectedId) || sdMilestones[0];
  const bufferMonths = parseFloat(document.getElementById("sd-buffer-months").value) || 0;

  const today = new Date();
  const target = new Date(goal.target_date + "T00:00:00");
  const monthsUntil = Math.max(1 / 30, (target - today) / (1000 * 60 * 60 * 24 * 30.44));

  const { totalSchweiz } = schweizMonthlyEstimate();
  const nw = await api("/net-worth");
  const targetAmount = totalSchweiz * bufferMonths;
  const gap = Math.max(0, targetAmount - nw.accounts_total);
  const requiredMonthly = gap / monthsUntil;

  document.getElementById("sd-summary-cards").innerHTML = `
    <div class="card">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><rect x="3" y="5" width="18" height="16" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M3 10H21M8 3V7M16 3V7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></div>
      <div><h3>Verbleibende Zeit</h3><p>${monthsUntil.toFixed(1).replace(".", ",")} Monate</p></div>
    </div>
    <div class="card">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><path d="M3 17L9 11L13 15L21 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
      <div><h3>Zielpuffer</h3><p>${eur(targetAmount)}</p></div>
    </div>
    <div class="card ${gap > 0 ? "card-neg" : "card-pos"}">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.8"/><path d="M8 12h8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></div>
      <div><h3>Noch fehlend</h3><p class="${gap > 0 ? "neg" : "pos"}">${eur(gap)}</p></div>
    </div>
    <div class="card">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><path d="M12 19V5M12 5L6 11M12 5L18 11" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
      <div><h3>Nötig pro Monat</h3><p>${eur(requiredMonthly)}</p></div>
    </div>`;

  document.getElementById("sd-explainer").textContent = gap > 0
    ? `Bis „${goal.title}" am ${fmtDate(goal.target_date)} bleiben ${monthsUntil.toFixed(1).replace(".", ",")} Monate. Für einen Puffer von ${bufferMonths} Monaten geschätzter Schweizer Lebenshaltungskosten (${eur(totalSchweiz)}/Monat) fehlen noch ${eur(gap)} - das sind ${eur(requiredMonthly)}/Monat ab jetzt.`
    : `Der Zielpuffer von ${eur(targetAmount)} ist mit deinem aktuellen Kontostand (${eur(nw.accounts_total)}) bereits gedeckt.`;

  // "Wie lange bis zur Spardistanz bei aktueller vs. erhöhter Rate?" - eigenes
  // Feld statt Wiederverwendung von cashflow_scenario: hier ist die Frage
  // "wie viele Monate bis GAP gedeckt ist" bei einer FESTEN Sparrate, nicht
  // "wie sieht der Kontostand nach N Tagen aus" wie beim Cashflow-Szenario.
  renderSavingsGapScenario(gap);
}

function monthsToClose(gap, monthlyRate) {
  if (gap <= 0) return 0;
  if (monthlyRate <= 0) return Infinity;
  return gap / monthlyRate;
}

function renderSavingsGapScenario(gap) {
  const currentRate = parseFloat(document.getElementById("sd-current-rate").value) || 0;
  const scenarioWrap = document.getElementById("sd-scenario-wrap");
  if (!currentRate) {
    scenarioWrap.classList.add("hidden");
    return;
  }
  scenarioWrap.classList.remove("hidden");
  const scenarioRate = parseFloat(document.getElementById("sd-scenario-rate").value) || 0;
  const resultEl = document.getElementById("sd-scenario-result");

  const currentMonths = monthsToClose(gap, currentRate);
  const currentText = currentMonths === Infinity
    ? "wird bei dieser Rate nie erreicht"
    : currentMonths === 0 ? "schon gedeckt" : `${currentMonths.toFixed(1).replace(".", ",")} Monate`;

  if (!scenarioRate || scenarioRate <= currentRate) {
    resultEl.textContent = `Bei ${eur(currentRate)}/Monat: ${currentText}. Trag oben eine höhere Sparrate ein, um zu vergleichen.`;
    return;
  }
  const scenarioMonths = monthsToClose(gap, scenarioRate);
  const scenarioText = scenarioMonths === 0 ? "schon gedeckt" : `${scenarioMonths.toFixed(1).replace(".", ",")} Monate`;
  const saved = currentMonths === Infinity ? null : currentMonths - scenarioMonths;
  resultEl.innerHTML = `Bei ${eur(currentRate)}/Monat: <strong>${currentText}</strong> · ` +
    `bei ${eur(scenarioRate)}/Monat: <strong>${scenarioText}</strong>` +
    (saved != null && saved > 0.05 ? ` – das spart ${saved.toFixed(1).replace(".", ",")} Monate.` : "");
}

document.getElementById("sd-milestone").addEventListener("change", renderSavingsGap);
document.getElementById("sd-buffer-months").addEventListener("change", renderSavingsGap);
document.getElementById("sd-current-rate").addEventListener("input", renderSavingsGap);
document.getElementById("sd-scenario-rate").addEventListener("input", renderSavingsGap);

function updateGoalsBadge(count) {
  const badge = document.getElementById("goals-nav-badge");
  badge.textContent = count;
  badge.classList.toggle("hidden", !count);
}

async function refreshGoalsBadge() {
  // Beim App-Start nur zählen, nicht als gesehen markieren - das passiert erst,
  // wenn der Ziele-Tab tatsächlich geöffnet wurde.
  try {
    const gs = await api("/goals");
    updateGoalsBadge(gs.filter(g => !g.completion_seen).length);
  } catch (e) {
    // Ziele sind für den Start unkritisch
  }
}

function renderGoalCard(g) {
  const card = document.createElement("div");
  const overdue = g.status === "open" && g.target_date && g.target_date < new Date().toISOString().slice(0, 10);
  card.className = "goal-card" + (g.status !== "open" ? " completed" : "") + (g.completion_seen ? "" : " newly-reached");

  const meta = [];
  if (g.target_date) meta.push(`${overdue ? "⚠️ fällig war" : "bis"} ${fmtDate(g.target_date)}`);
  if (g.space_id === null) meta.push("bereichsübergreifend");
  if (g.predecessor_title) meta.push(`nach „${esc(g.predecessor_title)}“`);

  let body = "";
  if (g.goal_type === "auto_financial") {
    if (g.evaluation_error) {
      body = `<p class="goal-error">⚠️ ${esc(g.evaluation_error)}</p>`;
    } else {
      const pct = g.progress_percent ?? 0;
      body = `
        <p class="goal-metric">${esc(g.metric_label || "")}</p>
        <div class="budget-track"><div class="goal-fill${pct >= 100 ? " done" : ""}" style="width:${Math.min(100, pct)}%"></div></div>
        <p class="goal-values"><strong>${pct.toFixed(0)}%</strong> · ${goalValueText(g)}</p>`;
    }
  } else {
    body = `
      <label class="goal-check">
        <input type="checkbox" ${g.status === "completed" ? "checked" : ""} onchange="toggleGoalDone(${g.id}, this.checked)">
        <span>${g.status === "completed" ? "Erledigt" : "Als erledigt markieren"}</span>
      </label>`;
  }

  card.innerHTML = `
    ${g.completion_seen ? "" : '<span class="goal-new-badge">🎉 Neu erreicht</span>'}
    <div class="goal-card-head">
      <h4>${esc(g.title)}</h4>
      ${g.category ? `<span class="goal-chip">${esc(g.category)}</span>` : ""}
    </div>
    ${g.description ? `<p class="goal-desc">${esc(g.description)}</p>` : ""}
    ${body}
    ${meta.length ? `<p class="goal-meta">${meta.join(" · ")}</p>` : ""}
    <div class="filter-row" style="margin-top:4px">
      <button class="link-btn" onclick="openGoalModal(${g.id})">Bearbeiten</button>
      <button type="button" class="link-btn" data-notes-entity="goal" data-notes-id="${g.id}" data-notes-label="${esc(g.title)}">📝 Notizen</button>
    </div>`;
  return card;
}

// ---------- Ziele-Roadmap (Zeitstrahl statt Kartenraster) ----------
// Kategorie -> Farbe konsistent zugewiesen (gleiche Palette wie die
// Kategorie-Charts, siehe getCatColors) - nicht global fix, sondern je
// Aufruf aus den tatsächlich vorkommenden Kategorien der übergebenen Ziele
// abgeleitet, damit auch Freitext-Kategorien außerhalb der Buchungs-
// Kategorien eine Farbe bekommen.
function displayGoalCategory(category) {
  if (!category) return null;
  return category.replace(/^schweiz:\s*/i, "");
}

const ROADMAP_MONTH_SHORT = ["JAN", "FEB", "MÄR", "APR", "MAI", "JUN", "JUL", "AUG", "SEP", "OKT", "NOV", "DEZ"];

function renderGoalsRoadmap(goals, listElId, legendElId) {
  const listEl = document.getElementById(listElId);
  const legendEl = document.getElementById(legendElId);

  const catColors = getCatColors();
  const distinctCats = [...new Set(goals.map(g => displayGoalCategory(g.category) || "Ohne Kategorie"))];
  const colorFor = cat => catColors[distinctCats.indexOf(cat) % catColors.length];

  legendEl.innerHTML = distinctCats.map(cat => `
    <span class="roadmap-legend-item">
      <span class="roadmap-legend-dot" style="background:${colorFor(cat)}"></span>${esc(cat)}
    </span>`).join("");

  const today = new Date().toISOString().slice(0, 10);
  const withDate = goals.filter(g => g.target_date).sort((a, b) => a.target_date.localeCompare(b.target_date));
  const withoutDate = goals.filter(g => !g.target_date);

  // Ein "Heute"-Marker wird an der chronologisch richtigen Stelle in die
  // datierten Ziele eingefügt, damit die Zeitachse zeigt, wo man gerade steht.
  const todayIndex = withDate.findIndex(g => g.target_date >= today);
  const insertTodayAt = withDate.length === 0 ? -1 : (todayIndex === -1 ? withDate.length : todayIndex);

  function renderRow(g, { first, last }) {
    const cat = displayGoalCategory(g.category) || "Ohne Kategorie";
    const isDone = g.status !== "open";
    const overdue = !isDone && g.target_date && g.target_date < today;
    const color = colorFor(cat);
    const checkbox = g.goal_type === "manual"
      ? `<input type="checkbox" class="roadmap-check" ${isDone ? "checked" : ""} onchange="toggleGoalDone(${g.id}, this.checked)" title="Als erledigt markieren">`
      : `<span title="${isDone ? "Erreicht" : "Automatisch gemessenes Ziel"}">${isDone ? "✅" : "📈"}</span>`;
    const notes = g.description
      ? `<details class="roadmap-notes"><summary>Notiz</summary><p>${esc(g.description)}</p></details>`
      : "";
    const d = g.target_date ? new Date(g.target_date + "T00:00:00") : null;
    return `
      <div class="roadmap-row${isDone ? " is-done" : ""}" style="--roadmap-accent:${color}">
        <div class="roadmap-when">${d ? `<span class="month">${ROADMAP_MONTH_SHORT[d.getMonth()]}</span><span class="day">${d.getDate()}.${d.getFullYear()}</span>` : ""}</div>
        <div class="roadmap-spine">
          <div class="roadmap-spine-line${first ? " is-top" : ""}"></div>
          <div class="roadmap-dot" style="box-shadow:0 0 0 2px ${color}">${isDone ? '<span class="roadmap-dot-check" style="background:' + color + '"></span>' : ""}</div>
          <div class="roadmap-spine-line${last ? " is-top" : ""}"></div>
        </div>
        <div class="roadmap-card">
          <div class="roadmap-item-head">
            ${checkbox}
            <span class="roadmap-title">${esc(g.title)}</span>
            <span class="goal-chip">${esc(cat)}</span>
            <span class="roadmap-date-inline">${overdue ? "⚠️ " : ""}${g.target_date ? fmtDate(g.target_date) : ""}</span>
          </div>
          ${notes}
        </div>
      </div>`;
  }

  const todayMarker = `
    <div class="roadmap-today">
      <span class="roadmap-today-line"></span>
      <span class="roadmap-today-label">Heute</span>
      <span class="roadmap-today-line"></span>
    </div>`;

  let html = "";
  let lastYear = null;
  withDate.forEach((g, i) => {
    if (insertTodayAt === i) html += todayMarker;
    const year = g.target_date.slice(0, 4);
    if (year !== lastYear) {
      html += `<div class="roadmap-year"><span class="roadmap-year-num">${year}</span><span class="roadmap-year-line"></span></div>`;
      lastYear = year;
    }
    html += renderRow(g, { first: i === 0 || year !== withDate[i - 1]?.target_date.slice(0, 4), last: i === withDate.length - 1 });
  });
  if (insertTodayAt === withDate.length && withDate.length) html += todayMarker;

  if (withoutDate.length) {
    html += `<div class="roadmap-section-label">Ohne festes Datum</div>`;
    html += withoutDate.map((g, i) => renderRow(g, { first: true, last: i === withoutDate.length - 1 })).join("");
  }

  listEl.innerHTML = html || `<div class="empty-state"><span class="empty-icon">${svgIcon("target")}</span><span>Keine Ziele für die Roadmap.</span></div>`;
}

document.querySelectorAll("#goal-view-tabs [data-goal-view]").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#goal-view-tabs [data-goal-view]").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const isRoadmap = btn.dataset.goalView === "roadmap";
    document.getElementById("goal-cards-view").classList.toggle("hidden", isRoadmap);
    document.getElementById("goal-roadmap-view").classList.toggle("hidden", !isRoadmap);
  });
});
document.querySelectorAll("#schweiz-view-tabs [data-schweiz-view]").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#schweiz-view-tabs [data-schweiz-view]").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const isRoadmap = btn.dataset.schweizView === "roadmap";
    document.getElementById("schweiz-cards-view").classList.toggle("hidden", isRoadmap);
    document.getElementById("schweiz-roadmap-view").classList.toggle("hidden", !isRoadmap);
  });
});

// Isoliert per CSS (siehe @media print .print-target) nur das eine Panel für
// den Druck - alles andere (Sidebar, Topbar, andere Panels) bleibt zwar im
// DOM, wird aber unsichtbar/nicht mitgedruckt.
document.querySelectorAll(".roadmap-print-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const target = document.getElementById(btn.dataset.printTarget);
    target.classList.add("print-target");
    document.body.classList.add("printing-roadmap");
    window.print();
  });
});
window.addEventListener("afterprint", () => {
  document.body.classList.remove("printing-roadmap");
  document.querySelectorAll(".print-target").forEach(el => el.classList.remove("print-target"));
});

window.toggleGoalDone = async (id, completed) => {
  await api(`/goals/${id}/complete?completed=${completed}`, { method: "POST" });
  await loadGoalsTab();
  loadSchweizGoalsTab();
};

document.getElementById("goal-done-toggle").addEventListener("click", e => {
  const grid = document.getElementById("goal-done-grid");
  grid.classList.toggle("hidden");
  e.currentTarget.querySelector(".goal-section-caret").textContent = grid.classList.contains("hidden") ? "▶" : "▼";
});
document.getElementById("schweiz-done-toggle").addEventListener("click", e => {
  const grid = document.getElementById("schweiz-done-grid");
  grid.classList.toggle("hidden");
  e.currentTarget.querySelector(".goal-section-caret").textContent = grid.classList.contains("hidden") ? "▶" : "▼";
});

function syncGoalFormVisibility() {
  const isAuto = document.getElementById("goal-type").value === "auto_financial";
  document.getElementById("goal-trigger-fields").classList.toggle("hidden", !isAuto);
  const metric = document.getElementById("goal-metric").value;
  document.getElementById("goal-scope-account-wrap").classList.toggle("hidden", metric !== "account_balance");
  document.getElementById("goal-scope-asset-wrap").classList.toggle("hidden", metric !== "investment_value");
  document.getElementById("goal-scope-category-wrap").classList.toggle("hidden", metric !== "custom_category_sum");
  document.getElementById("goal-scope-debt-wrap").classList.toggle("hidden", metric !== "debt_balance");
  document.getElementById("goal-window-wrap").classList.toggle(
    "hidden", metric !== "savings_rate" && metric !== "custom_category_sum"
  );
  document.getElementById("goal-metric-hint").textContent = GOAL_METRIC_HINTS[metric] || "";
  document.getElementById("goal-threshold").required = isAuto;
}

document.getElementById("goal-type").addEventListener("change", syncGoalFormVisibility);
document.getElementById("goal-metric").addEventListener("change", syncGoalFormVisibility);

window.openGoalModal = async (goalId = null, defaultCategory = null) => {
  if (!accountsCache.length) await loadAccounts();
  if (!categoriesCache.length) await loadCategories();
  if (!goalsCache.length) goalsCache = await api("/goals");
  if (!debtsCache.length) debtsCache = await api("/debts");

  const g = goalId ? goalsCache.find(x => x.id === goalId) : null;

  document.getElementById("goal-scope-debt").innerHTML =
    debtsCache.map(d => `<option value="${d.id}">${esc(d.name)}</option>`).join("")
    || '<option value="">Noch kein Kredit angelegt</option>';

  const accSel = document.getElementById("goal-scope-account");
  accSel.innerHTML = accountsCache.map(a => `<option value="${a.id}">${esc(a.name)}</option>`).join("");
  const catSel = document.getElementById("goal-scope-category");
  catSel.innerHTML = categoriesCache.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
  const predSel = document.getElementById("goal-predecessor");
  predSel.innerHTML = '<option value="">–</option>'
    + goalsCache.filter(x => x.id !== goalId).map(x => `<option value="${x.id}">${esc(x.title)}</option>`).join("");
  document.getElementById("goal-category-list").innerHTML =
    [...new Set(goalsCache.map(x => x.category).filter(Boolean))].map(c => `<option value="${esc(c)}">`).join("");

  document.getElementById("goal-modal-title").textContent = g ? "Ziel bearbeiten" : "Neues Ziel";
  document.getElementById("goal-id").value = g ? g.id : "";
  document.getElementById("goal-title").value = g ? g.title : "";
  document.getElementById("goal-description").value = g?.description || "";
  document.getElementById("goal-category").value = g?.category || defaultCategory || "";
  document.getElementById("goal-target-date").value = g?.target_date || "";
  document.getElementById("goal-type").value = g ? g.goal_type : "manual";
  document.getElementById("goal-predecessor").value = g?.predecessor_goal_id || "";
  document.getElementById("goal-all-spaces").checked = g ? g.space_id === null : false;

  const t = g?.trigger;
  document.getElementById("goal-metric").value = t?.metric_type || "net_worth";
  document.getElementById("goal-comparison").value = t?.comparison || "gte";
  document.getElementById("goal-threshold").value = t?.threshold_value ?? "";
  document.getElementById("goal-scope-account").value = t?.scope_account_id || (accountsCache[0]?.id ?? "");
  document.getElementById("goal-scope-asset").value = t?.scope_asset_type || "";
  document.getElementById("goal-scope-category").value = t?.scope_category_id || (categoriesCache[0]?.id ?? "");
  document.getElementById("goal-scope-debt").value = t?.scope_debt_id || (debtsCache[0]?.id ?? "");
  document.getElementById("goal-window").value = t?.evaluation_window_months || 6;

  document.getElementById("goal-delete").classList.toggle("hidden", !g);
  syncGoalFormVisibility();
  await loadGoalHistory(g);
  document.getElementById("goal-modal").classList.remove("hidden");
};

async function loadGoalHistory(g) {
  const wrap = document.getElementById("goal-history-wrap");
  if (!g || g.goal_type !== "auto_financial") {
    wrap.classList.add("hidden");
    return;
  }
  const points = await api(`/goals/${g.id}/progress`);
  if (points.length < 2) {
    wrap.classList.add("hidden");
    return;
  }
  wrap.classList.remove("hidden");
  if (goalHistoryChart) goalHistoryChart.destroy();
  goalHistoryChart = new Chart(document.getElementById("chart-goal-history"), {
    type: "line",
    data: {
      labels: points.map(p => new Date(p.timestamp).toLocaleDateString("de-DE")),
      datasets: [
        {
          label: "Stand", data: points.map(p => p.current_value),
          borderColor: cssVar("--accent-strong"), borderWidth: 2, tension: 0.3,
          pointRadius: 0, fill: false,
        },
        {
          label: "Ziel", data: points.map(() => g.target_value),
          borderColor: cssVar("--muted"), borderWidth: 1.5, borderDash: [5, 5],
          pointRadius: 0, fill: false,
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: cssVar("--text-secondary"), boxWidth: 12 } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: cssVar("--muted"), font: { size: 11 } } },
        y: {
          grid: { color: cssVar("--border") },
          ticks: { color: cssVar("--text-secondary"), font: { size: 11 }, callback: v => g.value_unit === "eur" ? eur(v) : v },
        },
      },
    },
  });
}

function closeGoalModal() {
  document.getElementById("goal-modal").classList.add("hidden");
}
document.getElementById("goal-new-btn").addEventListener("click", () => openGoalModal(null));
document.getElementById("schweiz-goal-new-btn").addEventListener("click", () => openGoalModal(null, SCHWEIZ_GOAL_CATEGORY));
document.getElementById("goal-modal-close").addEventListener("click", closeGoalModal);
document.getElementById("goal-cancel").addEventListener("click", closeGoalModal);

document.getElementById("goal-form").addEventListener("submit", async e => {
  e.preventDefault();
  const id = document.getElementById("goal-id").value;
  const goalType = document.getElementById("goal-type").value;
  const payload = {
    title: document.getElementById("goal-title").value,
    description: document.getElementById("goal-description").value || null,
    category: document.getElementById("goal-category").value || null,
    goal_type: goalType,
    target_date: document.getElementById("goal-target-date").value || null,
    predecessor_goal_id: parseInt(document.getElementById("goal-predecessor").value) || null,
    all_spaces: document.getElementById("goal-all-spaces").checked,
    trigger: null,
  };
  if (goalType === "auto_financial") {
    const metric = document.getElementById("goal-metric").value;
    payload.trigger = {
      metric_type: metric,
      comparison: document.getElementById("goal-comparison").value,
      threshold_value: parseFloat(document.getElementById("goal-threshold").value),
      scope_account_id: metric === "account_balance" ? parseInt(document.getElementById("goal-scope-account").value) : null,
      scope_asset_type: metric === "investment_value" ? (document.getElementById("goal-scope-asset").value || null) : null,
      scope_category_id: metric === "custom_category_sum" ? parseInt(document.getElementById("goal-scope-category").value) : null,
      scope_debt_id: metric === "debt_balance" ? parseInt(document.getElementById("goal-scope-debt").value) : null,
      evaluation_window_months: ["savings_rate", "custom_category_sum"].includes(metric)
        ? parseInt(document.getElementById("goal-window").value) || null : null,
    };
  }
  await api(id ? `/goals/${id}` : "/goals", {
    method: id ? "PUT" : "POST",
    body: JSON.stringify(payload),
  });
  closeGoalModal();
  await loadGoalsTab();
  loadSchweizGoalsTab();
});

document.getElementById("goal-delete").addEventListener("click", async () => {
  const id = document.getElementById("goal-id").value;
  if (!id || !confirm("Ziel wirklich löschen?")) return;
  await api(`/goals/${id}`, { method: "DELETE" });
  closeGoalModal();
  await loadGoalsTab();
  loadSchweizGoalsTab();
});

// ================= INIT =================
async function initCurrency() {
  try {
    const s = await api("/settings/currency");
    displayCurrency = s.currency;
    if (displayCurrency === "CHF") {
      const fx = await api("/fx/rate?to=CHF");
      displayRate = fx.rate;
    } else {
      displayRate = 1;
    }
  } catch (e) {
    displayCurrency = "EUR";
    displayRate = 1;
  }
  updateCurrencyToggleUI();
}

function updateCurrencyToggleUI() {
  document.querySelectorAll(".currency-toggle-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.currency === displayCurrency);
  });
}

// Wohnsitzland - unabhaengig von der Anzeige-Waehrung (EUR/CHF oben), blendet
// nur landesspezifische Anbindungs-Panels in den Einstellungen ein/aus (siehe
// [data-country-only] in index.html, z.B. FinTS ist deutschlandspezifisch).
function applyCountryVisibility(country) {
  document.querySelectorAll("[data-country-only]").forEach(panel => {
    panel.classList.toggle("hidden", panel.dataset.countryOnly !== country);
  });
  document.querySelectorAll("#country-switch [data-country-option]").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.countryOption === country);
  });
}

async function loadCountrySettings() {
  try {
    const s = await api("/settings/country");
    applyCountryVisibility(s.country);
  } catch (e) {
    applyCountryVisibility("DE");
  }
}

document.querySelectorAll("#country-switch [data-country-option]").forEach(btn => {
  btn.addEventListener("click", async () => {
    const country = btn.dataset.countryOption;
    await api("/settings/country", { method: "PUT", body: JSON.stringify({ country }) });
    applyCountryVisibility(country);
  });
});

document.querySelectorAll(".currency-toggle-btn").forEach(btn => {
  btn.addEventListener("click", async () => {
    if (btn.dataset.currency === displayCurrency) return;
    await api("/settings/currency", { method: "PUT", body: JSON.stringify({ currency: btn.dataset.currency }) });
    // Neu laden statt live umzurechnen - so ist garantiert, dass wirklich jede
    // Zahl (inkl. aller Chart-Daten) mit dem neuen Kurs konsistent ist, statt
    // an einer vergessenen Stelle den alten Wert stehen zu lassen.
    location.reload();
  });
});

async function init() {
  document.getElementById("tx-date").value = new Date().toISOString().slice(0, 10);
  document.getElementById("db-year").value = new Date().getFullYear();
  initThemeSwitchUI();
  moveNavIndicator(document.querySelector(".nav-btn.active"));
  await initCurrency();
  await loadAccounts();
  await loadCategories();
  // Hub ist jetzt die Startseite, nicht mehr das Dashboard - das lädt wie
  // jeder andere Tab erst bei Klick (siehe Zeile 112 und den nav-btn-Handler).
  await loadHubTab();
  await loadGlobalTopbar();
  refreshGoalsBadge();
  refreshProjectsBadge();
  refreshIntegrationBadge();
  // Ohne das bleibt immichSkipConfirm auf dem Standardwert false, bis der
  // Nutzer einmal den Einstellungen-Tab geöffnet hat - die Bestätigung beim
  // Papierkorb-Löschen im Fotos-Tab erschien dadurch trotz aktivierter
  // Einstellung immer wieder, weil der Wert nie aus dem Backend geladen wurde.
  loadImmichSettings().catch(() => {});
  loadVersionWatermark();
  handleEnableBankingReturn();
  handleEbayReturn();
}
startApp();

async function loadVersionWatermark() {
  const el = document.getElementById("version-watermark-hub");
  if (!el) return;
  let v;
  try {
    v = await api("/version");
  } catch (e) {
    el.textContent = "";
    return;
  }
  let text = v.git_sha === "dev" ? "lokaler Build" : v.git_sha_short;
  if (v.build_date) text += " · " + relativeTimeDe(new Date(v.build_date));
  let title = `Version ${v.git_sha}` + (v.build_date ? `, gebaut ${new Date(v.build_date).toLocaleString("de-DE")}` : "");

  el.innerHTML = `<span>${esc(text)}</span>`;
  el.title = title;
  el.classList.remove("is-outdated");

  // Veraltet-Hinweis: nur anzeigen, wenn sich der neueste veroeffentlichte
  // Stand wirklich ermitteln liess (setzt ein oeffentliches GHCR-Paket
  // voraus) UND er vom laufenden Stand abweicht. Laesst er sich nicht
  // ermitteln, bleibt die Zeile wie bisher - lieber nichts zeigen als etwas
  // Falsches behaupten.
  if (v.git_sha === "dev") return;
  try {
    const latest = await api("/version/latest");
    if (latest.available && latest.git_sha !== v.git_sha) {
      el.classList.add("is-outdated");
      el.innerHTML += ` <span title="Neuere Version veröffentlicht (${esc(latest.git_sha_short)}) – wartet auf Watchtower oder manuellen Neustart">⚠️ veraltet</span>`;
    }
  } catch (e) {
    // Stumm bleiben - der Vergleich ist ein Nice-to-have, kein Kernfeature.
  }
}

// Cursor-folgender Glanz auf Cards/Panels (siehe .card::before in style.css) -
// ein einzelner delegierter Listener statt einem pro Karte, da Karten/Panels
// staendig neu gerendert werden (jedes innerHTML= wuerde direkte Listener
// wieder verlieren).
document.addEventListener("mousemove", e => {
  const el = e.target.closest(".card, .panel, .integration-card");
  if (!el) return;
  const rect = el.getBoundingClientRect();
  el.style.setProperty("--mx", `${e.clientX - rect.left}px`);
  el.style.setProperty("--my", `${e.clientY - rect.top}px`);
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  });
}

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

// ================= JAHRESRÜCKBLICK ("Wrapped"-artige Story) =================
const MONTH_NAMES_DE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];
const YEAR_REVIEW_GRADIENTS = [
  "radial-gradient(circle at 50% 15%, #3987e5, #16223a 70%)",
  "radial-gradient(circle at 50% 15%, #d95926, #2a1608 70%)",
  "radial-gradient(circle at 50% 15%, #199e70, #0c2018 70%)",
  "radial-gradient(circle at 50% 15%, #9085e9, #1a1830 70%)",
  "radial-gradient(circle at 50% 15%, #d55181, #2a1220 70%)",
  "radial-gradient(circle at 50% 15%, #c98500, #2a1a08 70%)",
];

let yearReviewSlides = [];
let yearReviewIndex = 0;
let yearReviewTimer = null;

function buildYearReviewSlides(d) {
  const slides = [];
  slides.push({
    icon: "sparkles",
    eyebrow: `Jahresrückblick ${d.year}`,
    value: `${d.year}`,
    label: "Dein Jahr in Zahlen - so lief's finanziell.",
  });
  slides.push({
    icon: "trending-up",
    eyebrow: "Einnahmen & Ausgaben",
    value: eur(d.total_income),
    label: `Einnahmen im Jahr ${d.year}`,
    sub: `Ausgaben: ${eur(Math.abs(d.total_expense))}`,
  });
  if (d.savings_rate !== null) {
    slides.push({
      icon: "wallet",
      eyebrow: "Gespart",
      value: eur(d.saved),
      label: d.saved >= 0
        ? `Du hast ${d.savings_rate.toFixed(0)}% deiner Einnahmen zurückgelegt.`
        : `Du hast mehr ausgegeben als eingenommen.`,
    });
  }
  if (d.biggest_expense) {
    slides.push({
      icon: "flame",
      eyebrow: "Größte einzelne Ausgabe",
      value: eur(d.biggest_expense.amount),
      label: d.biggest_expense.name,
      sub: [d.biggest_expense.category_name, fmtDate(d.biggest_expense.date)].filter(Boolean).join(" · "),
    });
  }
  if (d.top_category) {
    slides.push({
      icon: "tag",
      eyebrow: "Teuerste Kategorie",
      value: eur(d.top_category.total),
      label: d.top_category.name,
      sub: `${d.top_category.count} Buchung(en)`,
    });
  }
  if (d.most_frequent_category && d.most_frequent_category.name !== (d.top_category && d.top_category.name)) {
    slides.push({
      icon: "repeat",
      eyebrow: "Am häufigsten gebucht",
      value: `${d.most_frequent_category.count}×`,
      label: d.most_frequent_category.name,
      sub: eur(d.most_frequent_category.total),
    });
  }
  if (d.busiest_month) {
    slides.push({
      icon: "calendar",
      eyebrow: "Aktivster Monat",
      value: MONTH_NAMES_DE[d.busiest_month.month - 1],
      label: `${d.busiest_month.count} Buchungen - dein geschäftigster Monat ${d.year}.`,
    });
  }
  if (d.income_change_pct !== null || d.expense_change_pct !== null) {
    const parts = [];
    if (d.income_change_pct !== null) parts.push(`Einnahmen ${d.income_change_pct >= 0 ? "+" : ""}${d.income_change_pct.toFixed(0)}%`);
    if (d.expense_change_pct !== null) parts.push(`Ausgaben ${d.expense_change_pct >= 0 ? "+" : ""}${d.expense_change_pct.toFixed(0)}%`);
    slides.push({
      icon: "trending-up",
      eyebrow: `Im Vergleich zu ${d.year - 1}`,
      value: parts.join(" · "),
      label: "Veränderung zum Vorjahr",
    });
  }
  if (d.investment_return_pct !== null) {
    slides.push({
      icon: "trending-up",
      eyebrow: "Investment-Rendite",
      value: `${d.investment_return_pct >= 0 ? "+" : ""}${d.investment_return_pct.toFixed(1)}%`,
      label: "Dein Portfolio der letzten 12 Monate.",
    });
  }
  slides.push({
    icon: "landmark",
    eyebrow: "Nettovermögen heute",
    value: eur(d.net_worth_now),
    label: "Dein aktueller Stand - weiter so!",
  });
  slides.push({
    icon: "check-circle",
    eyebrow: `${d.year}`,
    value: "Das war's!",
    label: "Bis zum nächsten Jahresrückblick.",
    isOutro: true,
  });
  return slides;
}

function renderYearReviewDots() {
  const dotsEl = document.getElementById("year-review-dots");
  dotsEl.innerHTML = yearReviewSlides.map((_, i) =>
    `<div class="year-review-dot ${i < yearReviewIndex ? "is-done" : i === yearReviewIndex ? "is-active" : ""}"></div>`
  ).join("");
}

function renderYearReviewSlide() {
  const slide = yearReviewSlides[yearReviewIndex];
  const el = document.getElementById("year-review-slide");
  el.style.setProperty("--yr-bg", YEAR_REVIEW_GRADIENTS[yearReviewIndex % YEAR_REVIEW_GRADIENTS.length]);
  el.innerHTML = `
    ${svgIcon(slide.icon, "year-review-icon")}
    <p class="year-review-eyebrow">${esc(slide.eyebrow)}</p>
    <p class="year-review-value">${esc(slide.value)}</p>
    <p class="year-review-label">${esc(slide.label)}</p>
    ${slide.sub ? `<p class="year-review-sub">${esc(slide.sub)}</p>` : ""}
    ${slide.isOutro ? `<button type="button" class="btn-primary" id="year-review-done">Schließen</button>` : ""}
  `;
  renderYearReviewDots();
  document.getElementById("year-review-done")?.addEventListener("click", closeYearReview);
  clearTimeout(yearReviewTimer);
  yearReviewTimer = setTimeout(yearReviewNext, 5000);
}

function yearReviewNext() {
  if (yearReviewIndex >= yearReviewSlides.length - 1) { closeYearReview(); return; }
  yearReviewIndex++;
  renderYearReviewSlide();
}
function yearReviewPrev() {
  yearReviewIndex = Math.max(0, yearReviewIndex - 1);
  renderYearReviewSlide();
}

async function openYearReview() {
  let data;
  try {
    data = await api(`/year-review?year=${new Date().getFullYear()}`);
  } catch (e) {
    return;
  }
  yearReviewSlides = buildYearReviewSlides(data);
  yearReviewIndex = 0;
  document.getElementById("year-review-overlay").classList.remove("hidden");
  renderYearReviewSlide();
}

function closeYearReview() {
  clearTimeout(yearReviewTimer);
  document.getElementById("year-review-overlay").classList.add("hidden");
}

document.getElementById("sync-all-btn").addEventListener("click", async () => {
  const btn = document.getElementById("sync-all-btn");
  const resultEl = document.getElementById("sync-all-result");
  btn.disabled = true;
  const originalHtml = btn.innerHTML;
  btn.textContent = "Synchronisiere …";
  resultEl.classList.add("hidden");
  try {
    const result = await api("/sync-all", { method: "POST" });
    if (result.connections.length === 0) {
      resultEl.textContent = "Keine Bank-/Broker-Verbindungen eingerichtet (siehe Einstellungen).";
    } else {
      resultEl.textContent = result.connections.map(c => `${c.name} (${c.kind}): ${c.status || "–"}`).join(" · ");
    }
    resultEl.classList.remove("hidden");
    loadHubTab();
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
  }
});
document.getElementById("year-review-open").addEventListener("click", openYearReview);
document.getElementById("year-review-close").addEventListener("click", closeYearReview);
document.getElementById("year-review-next").addEventListener("click", yearReviewNext);
document.getElementById("year-review-prev").addEventListener("click", yearReviewPrev);
document.addEventListener("keydown", e => {
  if (document.getElementById("year-review-overlay").classList.contains("hidden")) return;
  if (e.key === "ArrowRight") yearReviewNext();
  else if (e.key === "ArrowLeft") yearReviewPrev();
  else if (e.key === "Escape") closeYearReview();
});

// ================= NOTIZEN (kontextbezogen) =================
// Ein generisches Modal statt eines eigenen Notizfelds pro Objekt - siehe
// models.Note. entity_type "search" ist ein virtueller Modus: kein neues
// Objekt, sondern die globale Volltextsuche über alle Notizen.
const NOTE_ENTITY_LABELS = {
  goal: "Ziel", todo: "To-Do", business_project: "Projekt",
  life_area: "Lebensbereich", schweiz: "Schweiz-Tab",
};
const NOTE_ENTITY_JUMP = { goal: "goals", todo: "goals", business_project: "projects", life_area: "life", schweiz: "schweiz" };
let notesModalState = { entityType: null, entityId: null };

async function openNotesModal(entityType, entityId, label) {
  notesModalState = { entityType, entityId };
  document.getElementById("notes-modal-title").textContent = `Notizen – ${label}`;
  document.getElementById("notes-add-form").classList.remove("hidden");
  document.getElementById("notes-add-text").value = "";
  document.getElementById("notes-modal").classList.remove("hidden");
  await renderNotesList();
}

async function renderNotesList() {
  const list = document.getElementById("notes-modal-list");
  list.innerHTML = `<p class="page-sub">Lade …</p>`;
  const { entityType, entityId } = notesModalState;
  const notes = await api(`/notes?entity_type=${encodeURIComponent(entityType)}&entity_id=${entityId}`);
  if (!notes.length) {
    list.innerHTML = `<p class="page-sub">Noch keine Notizen.</p>`;
    return;
  }
  list.innerHTML = notes.map(n => `
    <div class="todo-row">
      <span class="todo-title" style="white-space:pre-wrap">${esc(n.text)}<br><span class="page-sub">${fmtDateTime(n.created_at)}</span></span>
      <button type="button" class="link-btn" data-note-delete="${n.id}">Löschen</button>
    </div>`).join("");
}

document.getElementById("notes-modal-close").addEventListener("click", () => {
  document.getElementById("notes-modal").classList.add("hidden");
});
document.getElementById("notes-add-form").addEventListener("submit", async e => {
  e.preventDefault();
  const textEl = document.getElementById("notes-add-text");
  const text = textEl.value.trim();
  if (!text) return;
  await api("/notes", {
    method: "POST",
    body: JSON.stringify({ entity_type: notesModalState.entityType, entity_id: notesModalState.entityId, text }),
  });
  textEl.value = "";
  await renderNotesList();
});
document.getElementById("notes-modal-list").addEventListener("click", async e => {
  const id = e.target.closest("[data-note-delete]")?.dataset.noteDelete;
  if (!id) return;
  await api(`/notes/${id}`, { method: "DELETE" });
  await renderNotesList();
});

// Delegierter, globaler Klick-Handler statt einer Bindung je Tab - Notiz-
// Buttons tauchen an vielen verschiedenen Stellen auf (Ziele, To-Dos,
// Projekte, Lebensbereiche, Schweiz-Tab), die alle unabhängig neu gerendert
// werden.
document.addEventListener("click", e => {
  const btn = e.target.closest("[data-notes-entity]");
  if (!btn) return;
  openNotesModal(btn.dataset.notesEntity, parseInt(btn.dataset.notesId, 10), btn.dataset.notesLabel);
});

// Globale Notizsuche über die Command-Palette - eigener Suchmodus statt eines
// zusätzlichen Suchfelds irgendwo im UI, passend zur bestehenden ⌘K-Konvention.
async function openNotesSearchModal() {
  document.getElementById("notes-modal-title").textContent = "Notizen durchsuchen";
  document.getElementById("notes-add-form").classList.add("hidden");
  const list = document.getElementById("notes-modal-list");
  list.innerHTML = `
    <input type="text" id="notes-search-input" placeholder="Suchbegriff (mind. 2 Zeichen) …" style="width:100%;margin-bottom:10px">
    <div id="notes-search-results"></div>`;
  document.getElementById("notes-modal").classList.remove("hidden");
  const input = document.getElementById("notes-search-input");
  input.focus();
  const runSearch = async () => {
    const q = input.value.trim();
    const results = document.getElementById("notes-search-results");
    if (q.length < 2) {
      results.innerHTML = `<p class="page-sub">Mindestens 2 Zeichen eingeben.</p>`;
      return;
    }
    results.innerHTML = `<p class="page-sub">Suche …</p>`;
    const hits = await api(`/notes/search?q=${encodeURIComponent(q)}`);
    results.innerHTML = hits.length
      ? hits.map(n => `
        <button type="button" class="hub-list-row" data-note-jump="${n.entity_type}" style="display:block;text-align:left">
          <strong>${esc(NOTE_ENTITY_LABELS[n.entity_type] || n.entity_type)}${n.entity_label ? `: ${esc(n.entity_label)}` : ""}</strong>
          <div class="page-sub" style="white-space:pre-wrap">${esc(n.text)}</div>
        </button>`).join("")
      : `<p class="page-sub">Keine Notizen gefunden.</p>`;
  };
  input.addEventListener("input", runSearch);
  document.getElementById("notes-search-results").addEventListener("click", e => {
    const type = e.target.closest("[data-note-jump]")?.dataset.noteJump;
    if (!type) return;
    document.getElementById("notes-modal").classList.add("hidden");
    goToTab(NOTE_ENTITY_JUMP[type] || "hub");
  });
}
CMDK_ACTIONS.push({ label: "Notizen durchsuchen", icon: "file-text", run: openNotesSearchModal });
CMDK_ACTIONS.push({ label: "KI-Vorschläge prüfen", icon: "sparkles", run: () => goToTab("ai") });

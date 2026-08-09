const API = "/api";
let accountsCache = [];
let categoriesCache = [];
let editingTxId = null;
let editingAccId = null;
let editingCatId = null;
let chartInstance = null;
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

function emptyRow(colspan, icon, text) {
  return `<tr class="empty-row"><td colspan="${colspan}"><div class="empty-state"><span class="empty-icon">${icon}</span><span>${text}</span></div></td></tr>`;
}

const ACCOUNT_TYPE_ICONS = { girokonto: "🏦", bargeld: "💵", sparkonto: "🐷", depot: "📈", sonstiges: "📁" };
const CATEGORY_TYPE_ICONS = { einnahme: "💰", ausgabe: "🧾" };
async function api(path, options = {}) {
  const res = await fetch(API + path, {
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    alert("Fehler: " + (err.detail || res.statusText));
    throw new Error(err.detail);
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

const THEME_BG = { dark: "#0d0d0d", light: "#f4f5f8", yellow: "#fdf6e0", alpen: "#16223a" };

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
    if (btn.dataset.tab === "dashboard") loadDashboard();
    if (btn.dataset.tab === "business") loadBusinessTab();
    if (btn.dataset.tab === "transactions") loadTransactions();
    if (btn.dataset.tab === "accounts") loadAccounts();
    if (btn.dataset.tab === "recurring") loadRecurringTab();
    if (btn.dataset.tab === "categories") loadCategories();
    if (btn.dataset.tab === "investments") loadInvestmentsTab();
    if (btn.dataset.tab === "debts") loadDebtsTab();
    if (btn.dataset.tab === "goals") loadGoalsTab();
    if (btn.dataset.tab === "ai") loadAiTab();
    if (btn.dataset.tab === "trips") loadTrips();
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
    tbody.innerHTML = emptyRow(5, "🏦", "Noch keine Konten angelegt. Leg dein erstes Konto an!");
  }
  accountsCache.forEach(a => {
    const tr = document.createElement("tr");
    const icon = ACCOUNT_TYPE_ICONS[a.type] || "📁";
    tr.innerHTML = `<td><span class="row-name"><span class="row-icon">${icon}</span>${a.name}${a.is_business ? ' <span class="goal-chip">💼 Geschäftlich</span>' : ""}</span></td><td>${a.type}</td><td>${eur(a.initial_balance)}</td>
      <td class="${a.current_balance >= 0 ? "row-amount-pos" : "row-amount-neg"}">${eur(a.current_balance)}</td>
      <td>
        <button class="link-btn" onclick="editAccount(${a.id})">Bearbeiten</button>
        <button class="link-btn" onclick="deleteAccount(${a.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });
  populateAccountSelects();
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
    initial_balance: parseFloat(document.getElementById("acc-balance").value || 0),
    is_business: document.getElementById("acc-business").checked,
  };
  if (editingAccId) {
    await api(`/accounts/${editingAccId}`, { method: "PUT", body: JSON.stringify(payload) });
  } else {
    await api("/accounts", { method: "POST", body: JSON.stringify(payload) });
  }
  resetAccForm();
  loadAccounts();
  loadGlobalTopbar();
});

window.editAccount = async id => {
  const a = accountsCache.find(x => x.id === id);
  editingAccId = id;
  document.getElementById("acc-name").value = a.name;
  document.getElementById("acc-type").value = a.type;
  document.getElementById("acc-balance").value = a.initial_balance;
  document.getElementById("acc-business").checked = a.is_business;
  document.getElementById("acc-cancel").style.display = "inline-block";
};
document.getElementById("acc-cancel").addEventListener("click", resetAccForm);
function resetAccForm() {
  editingAccId = null;
  document.getElementById("acc-form").reset();
  document.getElementById("acc-cancel").style.display = "none";
}
window.deleteAccount = async id => {
  if (!confirm("Konto wirklich löschen? Zugehörige Buchungen werden mitgelöscht.")) return;
  await api(`/accounts/${id}`, { method: "DELETE" });
  loadAccounts();
};

// ================= CATEGORIES =================
async function loadCategories() {
  categoriesCache = await api("/categories");
  const tbody = document.getElementById("cat-list");
  tbody.innerHTML = "";
  if (categoriesCache.length === 0) {
    tbody.innerHTML = emptyRow(4, "🏷️", "Noch keine Kategorien angelegt.");
  }
  categoriesCache.forEach(c => {
    const parent = categoriesCache.find(p => p.id === c.parent_id);
    const tr = document.createElement("tr");
    const icon = CATEGORY_TYPE_ICONS[c.type] || "🏷️";
    tr.innerHTML = `<td><span class="row-name"><span class="row-icon">${icon}</span>${c.name}</span></td><td>${c.type}</td><td>${parent ? parent.name : "–"}</td>
      <td>
        <button class="link-btn" onclick="editCategory(${c.id})">Bearbeiten</button>
        <button class="link-btn" onclick="deleteCategory(${c.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });
  populateCategorySelects();
}

function populateCategorySelects() {
  const txSel = document.getElementById("tx-category");
  const filterSel = document.getElementById("tx-filter-category");
  const parentSel = document.getElementById("cat-parent");
  txSel.innerHTML = '<option value="">–</option>';
  filterSel.innerHTML = '<option value="">Alle Kategorien</option>';
  parentSel.innerHTML = '<option value="">–</option>';
  categoriesCache.forEach(c => {
    [txSel, filterSel, parentSel].forEach(sel => {
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
  loadCategories();
});

window.editCategory = id => {
  const c = categoriesCache.find(x => x.id === id);
  editingCatId = id;
  document.getElementById("cat-name").value = c.name;
  document.getElementById("cat-type").value = c.type;
  document.getElementById("cat-parent").value = c.parent_id || "";
  document.getElementById("cat-cancel").style.display = "inline-block";
};
document.getElementById("cat-cancel").addEventListener("click", resetCatForm);
function resetCatForm() {
  editingCatId = null;
  document.getElementById("cat-form").reset();
  document.getElementById("cat-cancel").style.display = "none";
}
window.deleteCategory = async id => {
  if (!confirm("Kategorie wirklich löschen?")) return;
  await api(`/categories/${id}`, { method: "DELETE" });
  loadCategories();
};

// ================= INVESTMENTS =================
const ASSET_TYPE_LABELS = { aktie: "Aktie", etf: "ETF", anleihe: "Anleihe", krypto: "Krypto", sonstiges: "Sonstiges" };

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
    tbody.innerHTML = emptyRow(9, "📈", "Noch keine Positionen angelegt.");
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
      <td>${h.name}<br><span class="page-sub">${h.symbol}${h.sector ? " · " + h.sector : ""}</span></td>
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
  await api("/holdings", { method: "POST", body: JSON.stringify(payload) });
  document.getElementById("holding-form").reset();
  loadInvestmentsTab();
});

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
  let data;
  try {
    data = await api(`/portfolio/history?range=${portfolioRange}`);
  } catch (e) {
    noteEl.textContent = "Portfolio-Verlauf konnte nicht geladen werden.";
    return;
  }
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
    grid.innerHTML = '<div class="empty-state"><span class="empty-icon">🔥</span><span>Noch keine Positionen für die Heatmap.</span></div>';
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
  const data = await api("/portfolio/dividends");

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
    tbody.innerHTML = emptyRow(5, "💰", "Keine Dividenden-Positionen gefunden (Aktien/ETFs mit Ausschüttung).");
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
    vorabTbody.innerHTML = emptyRow(7, "📄", "Keine ETF-Positionen mit Basiszins für dieses Jahr.");
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
    realizedTbody.innerHTML = emptyRow(6, "💹", "Keine Verkäufe in diesem Jahr.");
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
  try {
    const history = await api(`/holdings/${id}/history?range=${range}`);
    noteEl.textContent = "";
    renderHoldingHistoryChart(history.points, history.lots);
  } catch (e) {
    noteEl.textContent = "Kurshistorie konnte nicht geladen werden (Symbol prüfen, ggf. über 'Position bearbeiten' korrigieren).";
    if (holdingHistoryChart) { holdingHistoryChart.destroy(); holdingHistoryChart = null; }
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
    tbody.innerHTML = emptyRow(7, "🧾", "Noch keine Transaktionen erfasst.");
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
  try {
    const result = await api("/ai/portfolio-insight", { method: "POST" });
    resultEl.textContent = result.error ? `Fehler: ${result.error}` : result.text;
  } catch (e) {
    resultEl.textContent = "Analyse fehlgeschlagen.";
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
    tbody.innerHTML = emptyRow(4, "🧾", "Keine fehlenden Belege gefunden.");
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
}

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
  statusEl.textContent = "KI liest/denkt nach …";
  sendBtn.disabled = true;

  const fd = new FormData();
  fd.append("message", message);
  fd.append("history", JSON.stringify(belegChatHistory));
  if (file) fd.append("file", file);

  try {
    const result = await api("/ai/beleg-chat", { method: "POST", body: fd });
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
    grid.innerHTML = '<div class="empty-state"><span class="empty-icon">✈️</span><span>Noch keine Urlaube angelegt.</span></div>';
  }
  tripsCache.forEach(t => {
    const card = document.createElement("div");
    card.className = "trip-card";
    const hasDates = t.start_date || t.end_date;
    card.innerHTML = `
      <h4><span class="row-icon">🧳</span>${t.name}</h4>
      ${hasDates ? `<p class="trip-dates">${fmtDate(t.start_date)} – ${fmtDate(t.end_date)}</p>` : ""}
      <div class="trip-total">${eur(t.total_spent)}</div>
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
  await api("/trips", { method: "POST", body: JSON.stringify({ name, start_date, end_date }) });
  document.getElementById("trip-form").reset();
  loadTrips();
});

window.deleteTrip = async id => {
  if (!confirm("Urlaub wirklich löschen? Zugehörige Buchungen bleiben erhalten, verlieren aber die Zuordnung.")) return;
  await api(`/trips/${id}`, { method: "DELETE" });
  loadTrips();
};

// ================= TRANSACTIONS =================
async function loadTransactions() {
  loadGlobalTopbar();
  if (!accountsCache.length) await loadAccounts();
  if (!categoriesCache.length) await loadCategories();
  if (!tripsCache.length) await loadTrips();

  const params = new URLSearchParams();
  const search = document.getElementById("tx-search").value;
  const accId = document.getElementById("tx-filter-account").value;
  const catId = document.getElementById("tx-filter-category").value;
  const tripId = document.getElementById("tx-filter-trip").value;
  if (search) params.set("search", search);
  if (accId) params.set("account_id", accId);
  if (catId) params.set("category_id", catId);
  if (tripId) params.set("trip_id", tripId);

  const txs = await api("/transactions?" + params.toString());
  const tbody = document.getElementById("tx-list");
  tbody.innerHTML = "";
  if (txs.length === 0) {
    tbody.innerHTML = emptyRow(7, "🧾", "Keine Buchungen gefunden.");
  }
  txs.forEach(t => {
    const acc = accountsCache.find(a => a.id === t.account_id);
    const cat = categoriesCache.find(c => c.id === t.category_id);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${t.date}</td>
      <td>${t.description || ""}</td>
      <td>${acc ? acc.name : ""}</td>
      <td>${t.is_transfer ? '<span class="goal-chip">🔁 Umbuchung</span>' : (cat ? cat.name : "–")}</td>
      <td class="${t.is_transfer ? "" : (t.amount >= 0 ? "row-amount-pos" : "row-amount-neg")}">${eur(t.amount)}</td>
      <td>${t.receipt_filename ? `<a href="/api/receipts/${t.receipt_filename}" target="_blank">Beleg</a>` : "–"}</td>
      <td>
        <button class="link-btn" onclick="editTransaction(${t.id})">Bearbeiten</button>
        <button class="link-btn" onclick="deleteTransaction(${t.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });
}

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

async function loadRecurringTab() {
  await loadCashflowForecast();
  const items = await api("/transactions/recurring");
  const tbody = document.getElementById("recurring-list");
  tbody.innerHTML = "";
  if (items.length === 0) {
    tbody.innerHTML = emptyRow(7, "🔁", "Noch keine wiederkehrenden Zahlungen erkannt (mindestens 3 ähnliche Buchungen mit regelmäßigem Abstand nötig).");
  }
  let monthlyTotal = 0;
  items.forEach(it => {
    monthlyTotal += Math.abs(it.avg_amount) * (RECURRING_MONTHLY_FACTOR[it.frequency] || 0);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${it.description || "–"}</td>
      <td>${it.account_name || "–"}</td>
      <td>${it.category_name || "–"}</td>
      <td>${RECURRING_FREQ_LABELS[it.frequency] || it.frequency}</td>
      <td class="${it.avg_amount >= 0 ? "row-amount-pos" : "row-amount-neg"}">${eur(it.avg_amount)}</td>
      <td>${fmtDate(it.next_expected_date)}</td>
      <td>${eur(it.total_amount)}</td>`;
    tbody.appendChild(tr);
  });

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

document.getElementById("tx-filter-btn").addEventListener("click", loadTransactions);
document.getElementById("tx-search").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); loadTransactions(); } });

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
  loadTransactions();
  loadAccounts();
});

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
  document.getElementById("tx-cancel").style.display = "inline-block";
  document.getElementById("tx-submit").textContent = "Änderungen speichern";
  window.scrollTo(0, 0);
};
document.getElementById("tx-cancel").addEventListener("click", resetTxForm);
function resetTxForm() {
  editingTxId = null;
  document.getElementById("tx-form").reset();
  document.getElementById("tx-date").value = new Date().toISOString().slice(0, 10);
  document.getElementById("tx-cancel").style.display = "none";
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
// Merkt sich je Duplikatgruppe, welches Bild behalten werden soll.
// Vorbelegt mit Immichs eigenem Vorschlag.
const photoKeepChoice = new Map();
let photoGroupsCache = [];

function formatBytes(n) {
  if (!n) return "";
  const mb = n / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.round(n / 1024)} KB`;
}

async function loadPhotosTab() {
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

  wrap.innerHTML = `<p class="page-sub">Suche doppelte Aufnahmen …</p>`;
  let data;
  try {
    data = await api("/immich/duplicates");
  } catch (e) {
    summary.classList.add("hidden");
    wrap.innerHTML = `<div class="panel"><p class="page-sub">${esc(e.message)}</p></div>`;
    return;
  }

  photoGroupsCache = data.groups;
  photoKeepChoice.clear();
  data.groups.forEach(g => {
    // Immichs Vorschlag übernehmen; falls keiner kommt, das erste Bild.
    const suggested = g.suggested_keep_ids.find(id => g.assets.some(a => a.id === id));
    photoKeepChoice.set(g.duplicate_id, suggested || g.assets[0]?.id);
  });

  summary.classList.remove("hidden");
  if (data.total_groups === 0) {
    summary.innerHTML = `<strong>Keine Duplikate gefunden.</strong> Deine Bibliothek ist sauber.`;
    wrap.innerHTML = "";
    return;
  }
  summary.innerHTML = `<strong>${data.total_groups} Gruppe${data.total_groups === 1 ? "" : "n"}</strong>
    mit insgesamt ${data.total_assets} Aufnahmen. Wähle je Gruppe das Bild, das bleiben soll –
    die übrigen wandern in Immichs Papierkorb und sind dort wiederherstellbar.`;

  renderPhotoGroups();
}

function renderPhotoGroups() {
  const wrap = document.getElementById("photos-groups");
  wrap.innerHTML = photoGroupsCache.map(g => {
    const keepId = photoKeepChoice.get(g.duplicate_id);
    const cards = g.assets.map(a => {
      const keep = a.id === keepId;
      const dims = a.width && a.height ? `${a.width}×${a.height}` : "";
      const meta = [dims, formatBytes(a.size_bytes)].filter(Boolean).join(" · ");
      return `<button type="button" class="photo-card ${keep ? "is-keep" : "is-trash"}"
                data-group="${esc(g.duplicate_id)}" data-asset="${esc(a.id)}">
        <img loading="lazy" src="/api/immich/thumbnail/${esc(a.id)}" alt="">
        <span class="photo-badge">${keep ? "behalten" : "Papierkorb"}</span>
        <span class="photo-meta">
          <span class="photo-name">${esc(a.file_name || "")}</span>
          ${meta ? `<span>${esc(meta)}</span>` : ""}
          ${a.created_at ? `<span>${fmtDate(a.created_at.slice(0, 10))}</span>` : ""}
        </span>
      </button>`;
    }).join("");

    const trashCount = g.assets.length - 1;
    return `<div class="panel photo-group" data-group="${esc(g.duplicate_id)}">
      <div class="photo-group-head">
        <h3 class="panel-title">${g.assets.length} ähnliche Aufnahmen</h3>
        <div class="photo-group-actions">
          <button type="button" class="btn-ghost" data-dismiss="${esc(g.duplicate_id)}">Sind keine Duplikate</button>
          <button type="button" class="btn-primary" data-apply="${esc(g.duplicate_id)}">
            ${trashCount} in den Papierkorb
          </button>
        </div>
      </div>
      <div class="photo-strip">${cards}</div>
    </div>`;
  }).join("");
}

// Klick auf ein Bild wählt es als das zu behaltende aus.
document.getElementById("photos-groups").addEventListener("click", async e => {
  const card = e.target.closest(".photo-card");
  if (card) {
    photoKeepChoice.set(card.dataset.group, card.dataset.asset);
    renderPhotoGroups();
    return;
  }

  const applyId = e.target.closest("[data-apply]")?.dataset.apply;
  if (applyId) {
    const group = photoGroupsCache.find(g => g.duplicate_id === applyId);
    const keepId = photoKeepChoice.get(applyId);
    const trashIds = group.assets.filter(a => a.id !== keepId).map(a => a.id);
    if (!confirm(`${trashIds.length} Aufnahme(n) in den Papierkorb verschieben?\n\nSie bleiben in Immich wiederherstellbar.`)) return;
    try {
      const res = await api("/immich/duplicates/resolve", {
        method: "POST",
        body: JSON.stringify({ groups: [{ duplicate_id: applyId, keep_ids: [keepId], trash_ids: trashIds }] }),
      });
      toast(`${res.trashed_assets} Aufnahme(n) in den Papierkorb verschoben.`);
      await loadPhotosTab();
    } catch (err) {
      toast("Fehler: " + err.message);
    }
    return;
  }

  const dismissId = e.target.closest("[data-dismiss]")?.dataset.dismiss;
  if (dismissId) {
    try {
      await api(`/immich/duplicates/${dismissId}`, { method: "DELETE" });
      toast("Gruppe ausgeblendet, es wurde nichts gelöscht.");
      await loadPhotosTab();
    } catch (err) {
      toast("Fehler: " + err.message);
    }
  }
});

document.getElementById("photos-reload").addEventListener("click", () => loadPhotosTab());
document.getElementById("photos-goto-settings").addEventListener("click", () => {
  document.querySelector('.nav-btn[data-tab="settings"]').click();
});

// ---------- Immich-Einstellungen ----------
async function loadImmichSettings() {
  const s = await api("/settings/immich");
  document.getElementById("immich-url").value = s.url || "";
  document.getElementById("immich-remove").classList.toggle("hidden", !s.url && !s.api_key_set);
  document.getElementById("immich-api-key").placeholder = s.api_key_set
    ? "gespeichert – leer lassen behält den bisherigen"
    : "wird verschlüsselt gespeichert";
}

document.getElementById("immich-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const url = document.getElementById("immich-url").value.trim();
  if (!url) return;
  const keyInput = document.getElementById("immich-api-key");
  const body = { url };
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
    tbody.innerHTML = emptyRow(3, "🎯", "Noch keine Budgets festgelegt.");
  }
  budgets.forEach(b => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${b.category_name}</td><td>${eur(b.monthly_limit)}</td>
      <td><button class="link-btn" onclick="deleteBudget(${b.category_id})">Löschen</button></td>`;
    tbody.appendChild(tr);
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
    tbody.innerHTML = emptyRow(3, "🗄️", "Noch kein automatisches Backup erstellt.");
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
    let msg = `${r.transfers_marked} Buchung(en) als Umbuchung markiert, ${r.categorized} kategorisiert, ${r.skipped} übersprungen.`;
    if (r.error) msg += ` Hinweis: ${r.error}`;
    statusEl.textContent = msg;
    await loadTransactions();
    await loadGlobalTopbar();
  } catch (e) {
    // api() zeigt den Fehler bereits per alert() an
  }
  btn.disabled = false;
});

async function loadWebSearchSettings() {
  const s = await api("/settings/websearch");
  document.getElementById("websearch-remove").classList.toggle("hidden", !s.api_key_set);
  document.getElementById("websearch-api-key").placeholder = s.api_key_set
    ? "gespeichert – zum Ändern neuen Key eingeben" : "wird verschlüsselt gespeichert";
}

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
    tbody.innerHTML = emptyRow(5, "🏦", "Noch keine Bank-Verbindung angelegt.");
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
    tbody.innerHTML = emptyRow(4, "🪙", "Noch keine Bitvavo-Verbindung angelegt.");
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
    tbody.innerHTML = emptyRow(4, "💳", "Noch keine PayPal-Verbindung angelegt.");
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
  document.getElementById("eb-key-status").textContent = s.private_key_set
    ? "Privater Schlüssel ist hinterlegt (wird aus Sicherheitsgründen nicht wieder angezeigt)."
    : "Noch kein privater Schlüssel hinterlegt.";
  document.getElementById("eb-redirect-hint").textContent = location.origin + "/api/enablebanking/callback";
}

document.getElementById("eb-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const app_id = document.getElementById("eb-app-id").value;
  const private_key = document.getElementById("eb-private-key").value;
  if (!private_key.trim()) {
    alert("Bitte den privaten Schlüssel (PEM) einfügen.");
    return;
  }
  await api("/settings/enablebanking", { method: "PUT", body: JSON.stringify({ app_id, private_key }) });
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
    tbody.innerHTML = emptyRow(4, "🏦", "Noch keine Verbindung angelegt.");
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
}

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
  await loadIntegrationStatus();
  await loadBudgets();
  await loadOllamaSettings();
  await loadSyncSchedule();
  await loadAutoCategorizeSettings();
  await loadWebSearchSettings();
  await loadImmichSettings();
  await loadNotificationSettings();
  await loadCallSettings();
  await loadBackupSettings();
  await loadBackupsList();
  await loadFintsSettings();
  await loadBankConnections();
  await loadBitvavoConnections();
  await loadPaypalConnections();
  await loadEnableBankingSettings();
  await loadEnableBankingConnections();
}

// ================= DASHBOARD =================
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
    tbody.innerHTML = emptyRow(2, "🏦", "Keine Konten.");
  }
  data.account_balances.forEach(a => {
    const tr = document.createElement("tr");
    const icon = ACCOUNT_TYPE_ICONS[a.type] || "📁";
    tr.innerHTML = `<td><span class="row-name"><span class="row-icon">${icon}</span>${a.name}</span></td><td class="${a.current_balance >= 0 ? "row-amount-pos" : "row-amount-neg"}">${eur(a.current_balance)}</td>`;
    tbody.appendChild(tr);
  });

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
      const row = document.createElement("div");
      row.className = "budget-row";
      row.innerHTML = `
        <div class="budget-row-head">
          <span class="budget-name"><span class="row-icon">🎯</span>${b.category_name}</span>
          <span class="budget-amounts">${eur(b.spent)} von ${eur(b.limit)} (${b.percent.toFixed(0)}%)</span>
        </div>
        <div class="budget-track"><div class="budget-fill ${cls}" style="width:${pct}%"></div></div>`;
      budgetListEl.appendChild(row);
    });
  }

  const ctx = document.getElementById("chart-categories");
  const labels = data.by_category.map(c => c.category_name);
  const values = data.by_category.map(c => Math.abs(c.total));
  const catColors = getCatColors();
  const colors = labels.map((_, i) => catColors[i % catColors.length]);
  if (chartInstance) chartInstance.destroy();
  chartInstance = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: colors,
        borderRadius: 4,
        borderSkipped: false,
        maxBarThickness: 22,
      }],
    },
    options: {
      indexAxis: "y",
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
          callbacks: { label: ctx => eur(ctx.parsed.x) },
        },
      },
      scales: {
        x: {
          grid: { color: cssVar("--border"), drawTicks: false },
          border: { display: false },
          ticks: { color: cssVar("--muted"), font: { size: 11 }, callback: v => eur(v) },
        },
        y: {
          grid: { display: false },
          border: { display: false },
          ticks: { color: cssVar("--text-secondary"), font: { size: 12 } },
        },
      },
    },
  });
}

document.getElementById("db-refresh").addEventListener("click", loadDashboard);

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
    const icon = ACCOUNT_TYPE_ICONS[a.type] || "📁";
    tr.innerHTML = `<td><span class="row-name"><span class="row-icon">${icon}</span>${a.name}</span></td><td class="${a.current_balance >= 0 ? "row-amount-pos" : "row-amount-neg"}">${eur(a.current_balance)}</td>`;
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
    : '<div class="empty-state"><span class="empty-icon">🏦</span><span>Keine laufenden Kredite. Gut so.</span></div>';
  active.forEach(d => activeGrid.appendChild(renderDebtCard(d)));

  const doneGrid = document.getElementById("debt-done-grid");
  doneGrid.innerHTML = done.length
    ? ""
    : '<div class="empty-state"><span class="empty-icon">✅</span><span>Noch nichts abbezahlt.</span></div>';
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
  tbody.innerHTML = payments.length ? "" : emptyRow(7, "💸", "Noch keine Zahlungen erfasst.");
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
  schedBody.innerHTML = schedule.rows.length ? "" : emptyRow(7, "📅", schedule.note || "Kein Tilgungsplan berechenbar.");
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
  statusEl.textContent = "KI denkt nach …";
  sendBtn.disabled = true;
  input.value = "";

  const fd = new FormData();
  fd.append("message", message);
  fd.append("history", JSON.stringify(globalAiHistory));

  try {
    const result = await api("/ai/assistant-chat", { method: "POST", body: fd });
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

async function loadGoalsTab() {
  goalsCache = await api("/goals");
  if (!accountsCache.length) await loadAccounts();

  const open = goalsCache.filter(g => g.status === "open");
  const done = goalsCache.filter(g => g.status !== "open");
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
      <div><h3>Erreicht</h3><p class="pos">${goalsCache.filter(g => g.status === "completed").length}</p></div>
    </div>
    <div class="card">
      <div class="card-icon"><svg viewBox="0 0 24 24" fill="none"><rect x="3" y="5" width="18" height="16" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M3 10H21M8 3V7M16 3V7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></div>
      <div><h3>Nächste Frist</h3><p>${nextDue ? fmtDate(nextDue.target_date) : "–"}</p></div>
    </div>`;

  const openGrid = document.getElementById("goal-open-grid");
  openGrid.innerHTML = open.length
    ? ""
    : '<div class="empty-state"><span class="empty-icon">🎯</span><span>Noch keine offenen Ziele. Leg oben rechts eins an.</span></div>';
  open.forEach(g => openGrid.appendChild(renderGoalCard(g)));

  const doneGrid = document.getElementById("goal-done-grid");
  doneGrid.innerHTML = done.length
    ? ""
    : '<div class="empty-state"><span class="empty-icon">✅</span><span>Noch nichts abgeschlossen.</span></div>';
  done.forEach(g => doneGrid.appendChild(renderGoalCard(g)));
  document.getElementById("goal-done-count").textContent = done.length;

  // Die Karten zeigen die "Neu erreicht"-Markierung noch in diesem Durchgang,
  // der Zähler in der Navigation ist mit dem Ansehen aber erledigt.
  if (newlyReached) {
    await api("/goals/mark-seen", { method: "POST" });
    goalsCache.forEach(g => { g.completion_seen = true; });
  }
  updateGoalsBadge(0);
}

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
    <button class="link-btn" onclick="openGoalModal(${g.id})">Bearbeiten</button>`;
  return card;
}

window.toggleGoalDone = async (id, completed) => {
  await api(`/goals/${id}/complete?completed=${completed}`, { method: "POST" });
  loadGoalsTab();
};

document.getElementById("goal-done-toggle").addEventListener("click", () => {
  const grid = document.getElementById("goal-done-grid");
  grid.classList.toggle("hidden");
  document.querySelector(".goal-section-caret").textContent = grid.classList.contains("hidden") ? "▶" : "▼";
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

window.openGoalModal = async (goalId = null) => {
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
  document.getElementById("goal-category").value = g?.category || "";
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
  loadGoalsTab();
});

document.getElementById("goal-delete").addEventListener("click", async () => {
  const id = document.getElementById("goal-id").value;
  if (!id || !confirm("Ziel wirklich löschen?")) return;
  await api(`/goals/${id}`, { method: "DELETE" });
  closeGoalModal();
  loadGoalsTab();
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
  await loadDashboard();
  await loadGlobalTopbar();
  refreshGoalsBadge();
  refreshIntegrationBadge();
  loadVersionWatermark();
  handleEnableBankingReturn();
}
startApp();

async function loadVersionWatermark() {
  const el = document.getElementById("version-watermark");
  if (!el) return;
  try {
    const v = await api("/version");
    let text = v.git_sha === "dev" ? "lokaler Build" : v.git_sha_short;
    if (v.build_date) text += " · " + relativeTimeDe(new Date(v.build_date));
    el.textContent = text;
    el.title = `Version ${v.git_sha}` + (v.build_date ? `, gebaut ${new Date(v.build_date).toLocaleString("de-DE")}` : "");
  } catch (e) {
    el.textContent = "";
  }
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  });
}

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

// Sehr schlankes Markdown-Lite fürs Rendern von Ollama-Fließtext-Antworten
// (Portfolio-Insight, Beleg-Fehlbetrag-Hinweis, ...) - die kamen bisher als
// reiner textContent-Block rein, dadurch blieben "* "-Aufzählungen als
// literale Sternchen statt echter Listen stehen (live als "unübersichtlich"
// gemeldet). Bewusst kein echter Markdown-Parser (kein Bedarf für Tabellen/
// Links/verschachtelte Listen bei kurzen KI-Antworten) - nur Absätze,
// "- "/"* "-Aufzählungen und **fett**, alles über esc() escaped, bevor es
// als HTML eingesetzt wird.
function renderAiText(el, text) {
  if (!text) {
    el.innerHTML = "";
    return;
  }
  const blocks = text.trim().split(/\n{2,}/).map(block => {
    const lines = block.split("\n").map(l => l.trim()).filter(Boolean);
    const isList = lines.length > 0 && lines.every(l => /^[-*]\s+/.test(l));
    const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    if (isList) {
      return `<ul>${lines.map(l => `<li>${inline(l.replace(/^[-*]\s+/, ""))}</li>`).join("")}</ul>`;
    }
    return `<p>${lines.map(inline).join("<br>")}</p>`;
  });
  el.innerHTML = blocks.join("");
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

// CSRF-Double-Submit (siehe backend/app/auth.py:require_auth): das Backend
// setzt beim Login ein zusätzliches, per JS lesbares csrf_token-Cookie (nicht
// httpOnly, anders als das Session-Cookie) - bei jeder zustandsändernden
// Anfrage wird derselbe Wert hier ausgelesen und als Header gespiegelt.
// Ein Angreifer von einer fremden Seite kann den Cookie-Wert nicht auslesen
// (Same-Origin-Policy), kann den Header also nicht korrekt setzen.
function getCsrfToken() {
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

// Spezifikationspunkt J (2026-08-28): fetch() selbst schlägt bei einem
// echten Netzwerkausfall (offline, DNS-Fehler, Server nicht erreichbar) mit
// einer geworfenen Exception fehl, VOR jeder res.ok/res.status-Prüfung
// unten - das lief bisher still durch (viele Aufrufer fangen es lautlos ab,
// z.B. ".catch(() => [])", siehe dashboard.js), der Nutzer sah nur ein
// leeres Panel ohne Erklärung. Throttle verhindert eine Toast-Flut, wenn
// während eines Ausfalls mehrere api()-Aufrufe gleichzeitig/kurz
// hintereinander fehlschlagen (z.B. beim Laden eines ganzen Tabs).
let lastOfflineToastAt = 0;
function notifyOffline() {
  const now = Date.now();
  if (now - lastOfflineToastAt < 8000) return;
  lastOfflineToastAt = now;
  toast("Keine Verbindung zum Server - bitte Internet/Tailscale prüfen.", "error");
}

async function api(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = options.body instanceof FormData ? {} : { "Content-Type": "application/json" };
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = getCsrfToken();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  let res;
  try {
    res = await fetch(API + path, { headers, ...options });
  } catch (e) {
    notifyOffline();
    throw e;
  }
  if (res.status === 401) {
    // Sitzung fehlt/abgelaufen - zurück zum Login statt der generischen
    // Fehler-Alert-Box (siehe auth-login.js:handleUnauthorized). Kein
    // generischer Alert hier, der Login-Screen erklärt selbst, was los ist.
    if (typeof handleUnauthorized === "function") handleUnauthorized();
    throw new Error("Nicht angemeldet.");
  }
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
    // Buttons ohne data-tab sind keine Tab-Umschalter, sondern eigene
    // Aktionen (z.B. #nav-logout-btn, siehe index.html) - eigener
    // Click-Handler dafür, hier nichts weiter tun.
    if (!btn.dataset.tab) return;
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
    if (btn.dataset.tab === "steuern") loadSteuernTab();
    if (btn.dataset.tab === "ai") loadAiTab();
    if (btn.dataset.tab === "trips") loadTrips();
    if (btn.dataset.tab === "projects") loadProjectsTab();
    if (btn.dataset.tab === "life") loadLifeTab();
    if (btn.dataset.tab === "wishlist") loadWishlistTab();
    if (btn.dataset.tab === "vehicle") loadVehicleTab();
    if (btn.dataset.tab === "smarthome") loadSmartHomeTab();
    if (btn.dataset.tab === "meals") loadMealsTab();
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


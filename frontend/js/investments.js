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
    ? "Hinweis: für mindestens eine Position ist keine Kurshistorie verfügbar - sie ist nur im heutigen Stand enthalten, nicht im Verlauf davor (daher der Sprung am aktuellen Rand)."
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
  await loadSavingsPlans();
  await loadDiversification();
  await loadHeatmap();
  if (dividendsLoaded) await loadDividendsTab();
  if (taxLoaded) await loadTaxTab();
}

const SAVINGS_PLAN_FREQUENCY_LABELS = { MONTHLY: "Monatlich", WEEKLY: "Wöchentlich", QUARTERLY: "Vierteljährlich" };

// ---------- Sparpläne (aktuell nur Scalable Capital, siehe scalable_sync.py) ----------
async function loadSavingsPlans() {
  const panel = document.getElementById("savings-plans-panel");
  let data;
  try {
    data = await api("/investments/savings-plans");
  } catch (e) {
    panel.classList.add("hidden");
    return;
  }
  // Kein eigener Anbindungs-Hinweis noetig - ohne Scalable-Anbindung liefert
  // der Endpunkt einfach eine leere Liste, das Panel blendet sich dann
  // komplett aus statt eine leere Tabelle anzuzeigen.
  panel.classList.toggle("hidden", data.plans.length === 0);
  if (data.plans.length === 0) return;

  document.getElementById("savings-plans-sub").textContent =
    `Wiederkehrende automatische Käufe, aktuell nur Scalable Capital · zusammen ${eur(data.total_monthly_amount)}/Monat.`;
  document.getElementById("savings-plans-list").innerHTML = data.plans.map(p => `
    <tr>
      <td>${esc(p.name)}</td>
      <td>${eur(p.amount)}</td>
      <td>${SAVINGS_PLAN_FREQUENCY_LABELS[p.frequency] || esc(p.frequency)}</td>
      <td>${p.next_execution_date ? fmtDate(p.next_execution_date) : "–"}</td>
    </tr>`).join("");
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


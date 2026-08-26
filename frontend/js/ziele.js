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


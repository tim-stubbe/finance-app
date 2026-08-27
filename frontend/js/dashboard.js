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

  // Reise-Modus (siehe ROADMAP.md): läuft heute ein Trip, kommt er als
  // active_trip aus /today mit (dieselbe Zusammenfassung wie im Reisen-Tab,
  // keine eigene Auswertung hier nötig). Budget-Balken per .budget-track/
  // .budget-fill - dasselbe Muster wie im Reisen-Tab selbst (siehe
  // trips.js:loadTrips), nur ohne Budget bleibt es bei den Ist-Ausgaben.
  // Eigene .hub-trip-banner-Klasse statt der normalen .hub-list-row-Zeile:
  // die ist eine flex-row mit genau zwei Kindern (Label links, Wert rechts)
  // - .budget-track hat kein eigenes width und bräuchte als drittes Flex-
  // Kind darin sonst auf fast null zusammen (siehe style.css), deshalb hier
  // explizit als Spalte statt als Zeile.
  const tripBanner = data.active_trip ? (() => {
    const t = data.active_trip;
    let progress = "";
    if (t.budget) {
      const pct = Math.min(100, (t.total_spent / t.budget) * 100);
      const cls = t.total_spent > t.budget ? "over" : pct >= 80 ? "warn" : "ok";
      progress = `
        <div class="budget-track"><div class="budget-fill ${cls}" style="width:${pct}%"></div></div>
        <span class="page-sub">${eur(t.total_spent)} von ${eur(t.budget)} Budget</span>`;
    } else {
      progress = `<span class="page-sub">${eur(t.total_spent)} ausgegeben, ${t.transaction_count} Buchung${t.transaction_count !== 1 ? "en" : ""}</span>`;
    }
    const belegHinweis = t.missing_receipts_count
      ? `<span class="page-sub">📎 ${t.missing_receipts_count} Ausgabe${t.missing_receipts_count !== 1 ? "n" : ""} ohne Beleg</span>`
      : "";
    return `<button type="button" class="hub-list-row hub-trip-banner" data-hub-jump="trips">
      <span>✈️ Reise aktiv: <strong>${esc(t.name)}</strong></span>
      ${progress}
      ${belegHinweis}
    </button>`;
  })() : "";

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

  body.innerHTML = tripBanner + balanceLine + (sections.length
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


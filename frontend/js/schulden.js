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


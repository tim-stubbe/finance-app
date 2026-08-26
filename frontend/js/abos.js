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


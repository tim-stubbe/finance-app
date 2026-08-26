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


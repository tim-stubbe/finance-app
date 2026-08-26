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


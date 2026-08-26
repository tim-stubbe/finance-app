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


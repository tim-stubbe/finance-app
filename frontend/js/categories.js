// ================= CATEGORIES =================
async function loadCategories() {
  const yearInput = document.getElementById("cat-filter-year");
  const monthSelect = document.getElementById("cat-filter-month");
  if (!yearInput.value) yearInput.value = new Date().getFullYear();
  const year = parseInt(yearInput.value);
  const month = monthSelect.value ? parseInt(monthSelect.value) : null;
  const periodParam = month ? `year=${year}&month=${month}` : `year=${year}`;
  const periodLabel = month ? `${MONTH_NAMES_DE[month - 1]} ${year}` : `${year}`;

  const [categories, yearTotals, periodTotals, mismatches] = await Promise.all([
    api("/categories"), api(`/categories/totals?year=${year}`), api(`/categories/totals?${periodParam}`),
    api("/categories/sign-mismatches"),
  ]);
  categoriesCache = categories;

  const mismatchWarning = document.getElementById("cat-mismatch-warning");
  mismatchWarning.classList.toggle("hidden", mismatches.length === 0);
  if (mismatches.length > 0) {
    const parts = mismatches.map(m => `${esc(m.category_name)} (${m.count})`).join(", ");
    mismatchWarning.innerHTML = `⚠️ ${mismatches.reduce((s, m) => s + m.count, 0)} Buchungen mit unpassendem Vorzeichen für ihre Kategorie
      (z.B. eine Ausgabe-Kategorie mit positivem Betrag) - oft ein Zeichen für falsch zugeordnete Kategorien:
      ${parts}. Im Buchungen-Tab nach Kategorie filtern und prüfen.`;
  }
  document.getElementById("cat-list-year-header").textContent = year === new Date().getFullYear() ? "Dieses Jahr" : String(year);
  const tbody = document.getElementById("cat-list");
  tbody.innerHTML = "";
  if (categoriesCache.length === 0) {
    tbody.innerHTML = emptyRow(5, "tag", "Noch keine Kategorien angelegt.");
  }
  categoriesCache.forEach(c => {
    const parent = categoriesCache.find(p => p.id === c.parent_id);
    const tr = document.createElement("tr");
    const icon = CATEGORY_TYPE_ICONS[c.type] || "tag";
    const total = yearTotals[c.id];
    const totalCls = total == null ? "" : total >= 0 ? "row-amount-pos" : "row-amount-neg";
    tr.innerHTML = `<td><span class="row-name"><span class="row-icon">${svgIcon(icon)}</span>${c.name}</span></td><td>${c.type}</td><td>${parent ? parent.name : "–"}</td>
      <td class="${totalCls}">${total == null ? "–" : eur(total)}</td>
      <td>
        <button class="link-btn" onclick="editCategory(${c.id})">Bearbeiten</button>
        <button class="link-btn" onclick="deleteCategory(${c.id})">Löschen</button>
      </td>`;
    tbody.appendChild(tr);
  });
  populateCategorySelects();

  document.getElementById("cat-income-chart-title").textContent = `Einnahmen nach Kategorie (${periodLabel})`;
  document.getElementById("cat-expense-chart-title").textContent = `Ausgaben nach Kategorie (${periodLabel})`;

  const totals = periodTotals;
  const incomeCats = categoriesCache.filter(c => c.type === "einnahme" && totals[c.id] > 0);
  const expenseCats = categoriesCache.filter(c => c.type === "ausgabe" && totals[c.id] < 0);
  document.getElementById("cat-charts-grid").classList.toggle("hidden", incomeCats.length === 0 && expenseCats.length === 0);
  catIncomeChartInstance = renderCategoryPieChart(
    "chart-cat-income", catIncomeChartInstance,
    incomeCats.map(c => c.name), incomeCats.map(c => totals[c.id]),
  );
  catExpenseChartInstance = renderCategoryPieChart(
    "chart-cat-expense", catExpenseChartInstance,
    expenseCats.map(c => c.name), expenseCats.map(c => Math.abs(totals[c.id])),
  );

  const trend = await api("/categories/trend?months=12");
  const trendPanel = document.getElementById("cat-trend-panel");
  trendPanel.classList.toggle("hidden", trend.series.length === 0);
  if (trend.series.length > 0) {
    if (catTrendChartInstance) catTrendChartInstance.destroy();
    const catColors = getCatColors();
    // Zu viele Linien machen das Chart unlesbar - die 8 ausgabenstärksten
    // Kategorien reichen für einen Trend-Überblick (Backend sortiert bereits
    // absteigend nach Gesamtsumme).
    const topSeries = trend.series.slice(0, 8);
    catTrendChartInstance = new Chart(document.getElementById("chart-cat-trend"), {
      type: "line",
      data: {
        labels: trend.months.map(m => {
          const [y, mo] = m.split("-");
          return new Date(`${y}-${mo}-01T00:00:00`).toLocaleDateString("de-DE", { month: "short", year: "2-digit" });
        }),
        datasets: topSeries.map((s, i) => ({
          label: s.category_name,
          data: s.points,
          borderColor: catColors[i % catColors.length],
          backgroundColor: catColors[i % catColors.length],
          tension: 0.3,
          pointRadius: 3,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        onClick: (evt, elements) => {
          const points = catTrendChartInstance.getElementsAtEventForMode(evt, "index", { intersect: false }, true);
          const idx = points[0]?.index;
          if (idx == null) return;
          const [y, mo] = trend.months[idx].split("-");
          document.getElementById("cat-filter-year").value = y;
          document.getElementById("cat-filter-month").value = String(parseInt(mo));
          loadCategories();
        },
        onHover: (evt, elements, chart) => {
          chart.canvas.style.cursor = elements.length ? "pointer" : "default";
        },
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
            callbacks: { label: ctx => `${ctx.dataset.label}: ${eur(ctx.parsed.y)}` },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            border: { display: false },
            ticks: { color: cssVar("--muted"), font: { size: 11 } },
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
}

function populateCategorySelects() {
  const txSel = document.getElementById("tx-category");
  const filterSel = document.getElementById("tx-filter-category");
  const parentSel = document.getElementById("cat-parent");
  const bulkSel = document.getElementById("tx-bulk-category");
  txSel.innerHTML = '<option value="">–</option>';
  filterSel.innerHTML = '<option value="">Alle Kategorien</option>';
  parentSel.innerHTML = '<option value="">–</option>';
  bulkSel.innerHTML = '<option value="">– Kategorie wählen –</option>';
  categoriesCache.forEach(c => {
    [txSel, filterSel, parentSel, bulkSel].forEach(sel => {
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
  closeCatModal();
  loadCategories();
});

function openCatModal() {
  document.getElementById("cat-modal").classList.remove("hidden");
}
function closeCatModal() {
  document.getElementById("cat-modal").classList.add("hidden");
}

window.editCategory = id => {
  const c = categoriesCache.find(x => x.id === id);
  editingCatId = id;
  document.getElementById("cat-name").value = c.name;
  document.getElementById("cat-type").value = c.type;
  document.getElementById("cat-parent").value = c.parent_id || "";
  document.getElementById("cat-cancel").classList.remove("hidden");
  document.getElementById("cat-submit").textContent = "Änderungen speichern";
  document.getElementById("cat-modal-title").textContent = "Kategorie bearbeiten";
  openCatModal();
};
document.getElementById("cat-new-btn").addEventListener("click", () => {
  resetCatForm();
  document.getElementById("cat-modal-title").textContent = "Neue Kategorie";
  openCatModal();
});
document.getElementById("cat-modal-close").addEventListener("click", closeCatModal);
document.getElementById("cat-cancel").addEventListener("click", () => {
  resetCatForm();
  closeCatModal();
});
function resetCatForm() {
  editingCatId = null;
  document.getElementById("cat-form").reset();
  document.getElementById("cat-cancel").classList.add("hidden");
  document.getElementById("cat-submit").textContent = "Speichern";
}
window.deleteCategory = async id => {
  if (!confirm("Kategorie wirklich löschen?")) return;
  await api(`/categories/${id}`, { method: "DELETE" });
  loadCategories();
};


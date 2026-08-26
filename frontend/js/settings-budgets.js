// ================= SETTINGS: BUDGETS =================
function populateBudgetCategorySelect() {
  const sel = document.getElementById("budget-category");
  sel.innerHTML = "";
  categoriesCache.filter(c => c.type === "ausgabe").forEach(c => {
    const opt = document.createElement("option");
    opt.value = c.id; opt.textContent = c.name;
    sel.appendChild(opt);
  });
}

async function loadBudgets() {
  if (!categoriesCache.length) await loadCategories();
  populateBudgetCategorySelect();
  const budgets = await api("/budgets");
  const tbody = document.getElementById("budget-list");
  tbody.innerHTML = "";
  if (budgets.length === 0) {
    tbody.innerHTML = emptyRow(3, "target", "Noch keine Budgets festgelegt.");
  }
  budgets.forEach(b => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${b.category_name}</td><td>${eur(b.monthly_limit)}</td>
      <td><button class="link-btn" onclick="deleteBudget(${b.category_id})">Löschen</button></td>`;
    tbody.appendChild(tr);
  });
  loadBudgetSuggestions();
}

async function loadBudgetSuggestions() {
  const wrap = document.getElementById("budget-suggestions-wrap");
  let suggestions = [];
  try {
    suggestions = await api("/budgets/suggestions");
  } catch (e) {
    wrap.classList.add("hidden");
    return;
  }
  wrap.classList.toggle("hidden", suggestions.length === 0);
  if (!suggestions.length) return;
  document.getElementById("budget-suggestions-list").innerHTML = suggestions.map(s => `
    <tr>
      <td>${esc(s.category_name)}</td>
      <td>${eur(s.avg_monthly_spend)}</td>
      <td>${eur(s.suggested_limit)}</td>
      <td><button type="button" class="link-btn" data-apply-budget="${s.category_id}" data-apply-limit="${s.suggested_limit}">Übernehmen</button></td>
    </tr>`).join("");
  document.querySelectorAll("[data-apply-budget]").forEach(btn => {
    btn.addEventListener("click", async () => {
      await api("/budgets", {
        method: "POST",
        body: JSON.stringify({
          category_id: parseInt(btn.dataset.applyBudget, 10),
          monthly_limit: parseFloat(btn.dataset.applyLimit),
        }),
      });
      toast("Budget übernommen.");
      loadBudgets();
    });
  });
}

document.getElementById("budget-form").addEventListener("submit", async e => {
  e.preventDefault();
  const category_id = parseInt(document.getElementById("budget-category").value);
  const monthly_limit = parseFloat(document.getElementById("budget-limit").value);
  await api("/budgets", { method: "POST", body: JSON.stringify({ category_id, monthly_limit }) });
  document.getElementById("budget-form").reset();
  loadBudgets();
});

window.deleteBudget = async categoryId => {
  if (!confirm("Budget wirklich löschen?")) return;
  await api(`/budgets/${categoryId}`, { method: "DELETE" });
  loadBudgets();
};


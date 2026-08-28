// ================= ESSEN: Wochenplan, Rezepte, Einkaufsliste =================
// Backend: backend/app/routers/meals.py.
let mealsRecipes = [];
let mealsPlan = [];

function mealsWeekRange() {
  const now = new Date();
  const dow = (now.getDay() + 6) % 7; // Mo = 0
  const mon = new Date(now); mon.setDate(now.getDate() - dow); mon.setHours(0, 0, 0, 0);
  const days = [...Array(7)].map((_, i) => {
    const d = new Date(mon); d.setDate(mon.getDate() + i);
    return d;
  });
  const iso = d => d.toISOString().slice(0, 10);
  return { days, from: iso(days[0]), to: iso(days[6]), iso };
}

async function loadMealsTab() {
  const { days, from, to, iso } = mealsWeekRange();
  document.getElementById("meals-week-label").textContent =
    `${days[0].toLocaleDateString("de-DE")} – ${days[6].toLocaleDateString("de-DE")}`;
  try {
    [mealsRecipes, mealsPlan] = await Promise.all([
      api("/meals/recipes"),
      api(`/meals/plan?date_from=${from}&date_to=${to}`),
    ]);
  } catch { mealsRecipes = []; mealsPlan = []; }
  renderMealsPlan(days, iso);
  renderMealsRecipes();
}

function mealsCellSelect(dayIso, meal) {
  const entry = mealsPlan.find(e => e.date === dayIso && e.meal === meal);
  const opts = ['<option value="">— frei —</option>',
    ...mealsRecipes.map(r => `<option value="${r.id}" ${entry && entry.recipe_id === r.id ? "selected" : ""}>${esc(r.name)}</option>`),
    `<option value="note" ${entry && !entry.recipe_id && entry.note ? "selected" : ""}>✎ Notiz…</option>`];
  return `<select data-meal-cell data-day="${dayIso}" data-meal="${meal}">${opts.join("")}</select>`
    + (entry && !entry.recipe_id && entry.note ? `<span class="sh-sub">${esc(entry.note)}</span>` : "");
}

function renderMealsPlan(days, iso) {
  const body = document.getElementById("meals-plan-body");
  body.innerHTML = days.map(d => {
    const di = iso(d);
    return `<tr>
      <td>${d.toLocaleDateString("de-DE", { weekday: "short", day: "2-digit", month: "2-digit" })}</td>
      <td>${mealsCellSelect(di, "mittag")}</td>
      <td>${mealsCellSelect(di, "abend")}</td>
    </tr>`;
  }).join("");
}

document.getElementById("meals-plan-body").addEventListener("change", async e => {
  const sel = e.target.closest("[data-meal-cell]");
  if (!sel) return;
  const { day, meal } = sel.dataset;
  const v = sel.value;
  let payload;
  if (v === "") {
    await api(`/meals/plan?day=${day}&meal=${meal}`, { method: "DELETE" });
    loadMealsTab();
    return;
  } else if (v === "note") {
    const note = prompt("Notiz für " + meal + " am " + day + ":", "");
    if (note === null) { loadMealsTab(); return; }
    payload = { date: day, meal, recipe_id: null, note };
  } else {
    payload = { date: day, meal, recipe_id: parseInt(v, 10), note: "" };
  }
  await api("/meals/plan", { method: "PUT", body: JSON.stringify(payload) });
  loadMealsTab();
});

function renderMealsRecipes() {
  const tb = document.getElementById("meals-recipe-list");
  tb.innerHTML = mealsRecipes.length
    ? mealsRecipes.map(r => `<tr>
        <td>${esc(r.name)}${r.servings ? ` <span class="sh-sub">${r.servings} Portionen</span>` : ""}</td>
        <td>${esc(r.tags || "")}</td>
        <td><button type="button" class="link-btn" data-meals-recipe-del="${r.id}">Löschen</button></td>
      </tr>`).join("")
    : emptyRow(3, "list", "Noch keine Rezepte.");
}

document.getElementById("meals-recipe-list").addEventListener("click", async e => {
  const id = e.target.closest("[data-meals-recipe-del]")?.dataset.mealsRecipeDel;
  if (!id) return;
  if (!confirm("Rezept löschen?")) return;
  await api(`/meals/recipes/${id}`, { method: "DELETE" });
  loadMealsTab();
});

document.getElementById("meals-recipe-form").addEventListener("submit", async e => {
  e.preventDefault();
  const sv = document.getElementById("meals-recipe-servings").value;
  await api("/meals/recipes", {
    method: "POST",
    body: JSON.stringify({
      name: document.getElementById("meals-recipe-name").value.trim(),
      ingredients: document.getElementById("meals-recipe-ingredients").value,
      instructions: document.getElementById("meals-recipe-instructions").value,
      servings: sv ? parseInt(sv, 10) : null,
      tags: document.getElementById("meals-recipe-tags").value.trim(),
    }),
  });
  e.target.reset();
  loadMealsTab();
});

document.getElementById("meals-ai-suggest").addEventListener("click", async () => {
  const host = document.getElementById("meals-ai-suggestions");
  host.innerHTML = `<p class="page-sub">Die KI überlegt …</p>`;
  let list = [];
  try {
    list = await api("/meals/recipes/suggest", {
      method: "POST",
      body: JSON.stringify({ count: 3, prompt: document.getElementById("meals-ai-prompt").value.trim() }),
    });
  } catch (err) { host.innerHTML = `<p class="page-sub">Fehler: ${esc(err.message || "")}</p>`; return; }
  host.innerHTML = list.length ? list.map((r, i) => `
    <div class="sh-auto-card">
      <strong>${esc(r.name)}</strong> ${r.tags ? `<span class="sh-sub">${esc(r.tags)}</span>` : ""}
      <p class="page-sub" style="white-space:pre-line">${esc(r.ingredients)}</p>
      <p class="page-sub" style="white-space:pre-line">${esc(r.instructions)}</p>
      <button type="button" class="btn-ghost btn-sm" data-meals-save="${i}">Als Rezept speichern</button>
    </div>`).join("") : `<p class="page-sub">Keine Vorschläge.</p>`;
  host._suggestions = list;
});

document.getElementById("meals-ai-suggestions").addEventListener("click", async e => {
  const idx = e.target.closest("[data-meals-save]")?.dataset.mealsSave;
  if (idx == null) return;
  const r = e.target.closest("#meals-ai-suggestions")._suggestions[parseInt(idx, 10)];
  await api("/meals/recipes", { method: "POST", body: JSON.stringify({ ...r, source: "ki" }) });
  toast("Rezept gespeichert.");
  loadMealsTab();
});

document.getElementById("meals-shopping-refresh").addEventListener("click", async () => {
  const { from, to } = mealsWeekRange();
  const host = document.getElementById("meals-shopping");
  let items = [];
  try { items = await api(`/meals/shopping-list?date_from=${from}&date_to=${to}`); } catch { /* */ }
  if (!items.length) { host.innerHTML = `<p class="page-sub">Keine verplanten Rezepte mit Zutaten diese Woche.</p>`; return; }
  host.innerHTML = `<ul class="settings-list">${items.map(i =>
    `<li><span>${esc(i.item)}</span><span class="page-sub">${esc(i.amounts || "")}</span></li>`).join("")}</ul>
    <div class="form-actions">
      <button type="button" class="btn-ghost btn-sm" data-meals-push="wishlist">→ Wunschliste</button>
      <button type="button" class="btn-ghost btn-sm" data-meals-push="todo">→ To-do</button>
    </div>`;
});

document.getElementById("meals-shopping").addEventListener("click", async e => {
  const target = e.target.closest("[data-meals-push]")?.dataset.mealsPush;
  if (!target) return;
  const { from, to } = mealsWeekRange();
  try {
    const r = await api("/meals/shopping-list/push", {
      method: "POST",
      body: JSON.stringify({ date_from: from, date_to: to, target }),
    });
    toast(`${r.added} Einträge auf ${target === "todo" ? "To-do" : "Wunschliste"}.`);
  } catch (err) { toast(err.message || "Fehlgeschlagen."); }
});

// ================= TRIPS (URLAUBE) =================
let tripsCache = [];

function fmtDate(d) {
  if (!d) return "";
  return new Date(d + "T00:00:00").toLocaleDateString("de-DE");
}

async function loadTrips() {
  tripsCache = await api("/trips");
  populateTripSelects();
  const grid = document.getElementById("trip-grid");
  grid.innerHTML = "";
  if (tripsCache.length === 0) {
    grid.innerHTML = `<div class="empty-state"><span class="empty-icon">${svgIcon("map")}</span><span>Noch keine Urlaube angelegt.</span></div>`;
  }
  tripsCache.forEach(t => {
    const card = document.createElement("div");
    card.className = "trip-card";
    const hasDates = t.start_date || t.end_date;
    let budgetHtml = "";
    if (t.budget) {
      const pct = Math.min(100, (t.total_spent / t.budget) * 100);
      const cls = t.total_spent > t.budget ? "over" : pct >= 80 ? "warn" : "ok";
      budgetHtml = `
        <div class="budget-track"><div class="budget-fill ${cls}" style="width:${pct}%"></div></div>
        <p class="trip-meta">${eur(t.total_spent)} von ${eur(t.budget)} Budget
          ${t.total_spent > t.budget ? ` – ${eur(t.total_spent - t.budget)} über Budget` : ""}</p>`;
    }
    card.innerHTML = `
      <h4><span class="row-icon"><svg class="panel-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2V6z"/><path d="M9 4v14M15 6v14"/></svg></span>${t.name}</h4>
      ${hasDates ? `<p class="trip-dates">${fmtDate(t.start_date)} – ${fmtDate(t.end_date)}</p>` : ""}
      <div class="trip-total">${eur(t.total_spent)}</div>
      ${budgetHtml}
      <p class="trip-meta">${t.transaction_count} Buchung(en)</p>
      <button class="link-btn" onclick="deleteTrip(${t.id})">Löschen</button>`;
    grid.appendChild(card);
  });
}

function populateTripSelects() {
  const txSel = document.getElementById("tx-trip");
  const filterSel = document.getElementById("tx-filter-trip");
  txSel.innerHTML = '<option value="">–</option>';
  filterSel.innerHTML = '<option value="">Alle Urlaube</option>';
  tripsCache.forEach(t => {
    [txSel, filterSel].forEach(sel => {
      const opt = document.createElement("option");
      opt.value = t.id; opt.textContent = t.name;
      sel.appendChild(opt);
    });
  });
}

document.getElementById("trip-form").addEventListener("submit", async e => {
  e.preventDefault();
  const name = document.getElementById("trip-name").value;
  const start_date = document.getElementById("trip-start").value || null;
  const end_date = document.getElementById("trip-end").value || null;
  const budgetVal = document.getElementById("trip-budget").value;
  const budget = budgetVal ? parseFloat(budgetVal) : null;
  await api("/trips", { method: "POST", body: JSON.stringify({ name, start_date, end_date, budget }) });
  document.getElementById("trip-form").reset();
  closeTripModal();
  loadTrips();
});

function openTripModal() {
  document.getElementById("trip-modal").classList.remove("hidden");
}
function closeTripModal() {
  document.getElementById("trip-modal").classList.add("hidden");
}
document.getElementById("trip-new-btn").addEventListener("click", openTripModal);
document.getElementById("trip-modal-close").addEventListener("click", closeTripModal);

window.deleteTrip = async id => {
  if (!confirm("Urlaub wirklich löschen? Zugehörige Buchungen bleiben erhalten, verlieren aber die Zuordnung.")) return;
  await api(`/trips/${id}`, { method: "DELETE" });
  loadTrips();
};


// Hub: offene proaktive Vorschläge (models.ProactiveProposal) + das
// Assistenten-Gedächtnis (assistant_memory.py) direkt im Browser.
// Backend: routers/proactive.py, routers/assistant_memory_routes.py.
// Beide werden aus dashboard.js:loadHubTab() aufgerufen.

const HUB_URGENCY_MARK = { hoch: "❗", mittel: "🤖", niedrig: "💡" };
const HUB_MEM_CAT = {
  praeferenz: "Präferenz", vorhaben: "Vorhaben", erledigt: "erledigt",
  kontext: "Kontext", zusammenfassung: "Zusammenfassung", fakt: "Fakt",
};

async function loadHubProposals() {
  const panel = document.getElementById("hub-proposals-panel");
  const body = document.getElementById("hub-proposals-body");
  if (!panel || !body) return;
  let items;
  try {
    items = await api("/proactive/proposals");
  } catch {
    panel.classList.add("hidden");
    return;
  }
  if (!items.length) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  body.innerHTML = items.map(p => `
    <div class="hub-proposal" data-proposal="${p.id}" style="padding:10px 0;border-top:1px solid var(--border,#e5e0d8)">
      <div><strong>${HUB_URGENCY_MARK[p.urgency] || "🤖"} ${esc(p.title)}</strong></div>
      ${p.body ? `<p class="page-sub" style="margin:2px 0 8px">${esc(p.body)}</p>` : ""}
      <div class="hub-jarvis-actions">
        ${p.options.map(o => `<button type="button" class="btn-ghost btn-sm"
          data-proposal-answer="${p.id}" data-proposal-key="${o.key}">${esc(o.label)}</button>`).join("")}
      </div>
    </div>`).join("");
}

async function loadHubMemory() {
  const panel = document.getElementById("hub-memory-panel");
  const body = document.getElementById("hub-memory-body");
  if (!panel || !body) return;
  let items;
  try {
    items = await api("/assistant-memory");
  } catch {
    panel.classList.add("hidden");
    return;
  }
  if (!items.length) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  body.innerHTML = items.map(m => `
    <div class="hub-list-row" style="cursor:default">
      <span>${m.pinned ? "📌 " : ""}${esc(m.text)}
        <span class="page-sub">· ${HUB_MEM_CAT[m.category] || m.category} ⋆${m.importance}${m.source === "destillation" ? " · auto" : ""}</span>
      </span>
      <button type="button" class="link-btn" data-memory-forget="${m.id}" title="Vergessen">×</button>
    </div>`).join("");
}

async function loadHubEnergy() {
  const panel = document.getElementById("hub-energy-panel");
  const body = document.getElementById("hub-energy-body");
  if (!panel || !body) return;
  let d;
  try {
    d = await api("/energy/summary");
  } catch {
    panel.classList.add("hidden");
    return;
  }
  if (!d.has_data) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  const nf = (n, dec = 2) => Number(n).toFixed(dec).replace(".", ",");
  const monthProj = d.month_kwh > 0
    ? d.month_eur / (new Date().getDate()) * 30 : 0;
  const spark = (typeof sparklineSvg === "function" && d.points)
    ? `<span class="card-sparkline">${sparklineSvg(d.points.map(p => p.kwh))}</span>` : "";
  const weekDelta = d.prev_week_kwh > 0
    ? ((d.week_kwh - d.prev_week_kwh) / d.prev_week_kwh) * 100 : null;
  body.innerHTML = `
    <p style="font-size:28px;font-weight:800;margin:0 0 2px">${nf(d.current_w, 0)} W</p>
    <p class="page-sub" style="margin:0 0 10px">gerade · ${nf(d.price_eur_kwh)} €/kWh</p>
    <div class="hub-list-row" style="cursor:default"><span>Heute</span><span>${nf(d.today_kwh, 2)} kWh · ${nf(d.today_eur)} €</span></div>
    <div class="hub-list-row" style="cursor:default"><span>Diesen Monat</span><span>${nf(d.month_eur)} €${monthProj ? ` <span class="page-sub">(≈ ${nf(monthProj)} € Hochr.)</span>` : ""}</span></div>
    <div class="hub-list-row" style="cursor:default"><span>Diese Woche</span><span>${nf(d.week_kwh, 2)} kWh${weekDelta != null ? ` <span class="${weekDelta > 5 ? "neg" : weekDelta < -5 ? "pos" : "page-sub"}">${weekDelta > 0 ? "+" : ""}${nf(weekDelta, 0)} %</span>` : ""}</span></div>
    ${spark ? `<div style="margin-top:8px">${spark}<span class="page-sub"> kWh/Tag, 14 Tage</span></div>` : ""}`;
}

document.addEventListener("click", async (e) => {
  const ans = e.target.closest("[data-proposal-answer]");
  if (ans) {
    const id = ans.dataset.proposalAnswer;
    const key = ans.dataset.proposalKey;
    ans.closest(".hub-proposal").querySelectorAll("button").forEach(b => (b.disabled = true));
    try {
      const { result } = await api(`/proactive/proposals/${id}/answer`, {
        method: "POST", body: JSON.stringify({ key }),
      });
      toast(result || "Erledigt");
    } catch (err) {
      toast(err.message || "Ging nicht", "err");
    }
    loadHubProposals();
    return;
  }
  const forget = e.target.closest("[data-memory-forget]");
  if (forget) {
    forget.disabled = true;
    try {
      await api(`/assistant-memory/${forget.dataset.memoryForget}`, { method: "DELETE" });
    } catch (err) {
      toast(err.message || "Ging nicht", "err");
    }
    loadHubMemory();
  }
});

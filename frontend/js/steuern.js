// ================= STEUERN-TAB (Spar-Tipps + KI-Frage) =================
// Backend: app/tax_advice.py, GET /api/tax/tips, POST /api/tax/ask.
// Regelbasiert aus den echten Daten; ausdrücklich keine Steuerberatung.

const STEUERN_SEV = {
  hoch: { cls: "sev-high", label: "Prüfen" },
  mittel: { cls: "sev-mid", label: "Chance" },
  info: { cls: "sev-info", label: "Hinweis" },
};
const STEUERN_AREA = { kapital: "Kapitalerträge", finanzen: "Einkommen / Ausgaben" };

function steuernEsc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

async function loadSteuernTab() {
  const yearSel = document.getElementById("steuern-year");
  if (!yearSel.options.length) {
    const y = new Date().getFullYear();
    for (let i = 0; i < 4; i++) {
      const opt = document.createElement("option");
      opt.value = y - i; opt.textContent = y - i;
      yearSel.appendChild(opt);
    }
    yearSel.addEventListener("change", loadSteuernTips);
  }
  await loadSteuernProfile();
  await loadSteuernTips();
}

async function loadSteuernProfile() {
  let p;
  try { p = await api("/tax/profile"); } catch { return; }
  document.getElementById("steuern-church").value = String(p.church_tax_rate || 0);
  document.getElementById("steuern-mtr").value = p.marginal_tax_rate ? Math.round(p.marginal_tax_rate * 100) : "";
  document.getElementById("steuern-freibetrag").value = p.sparerpauschbetrag != null ? p.sparerpauschbetrag : "";
  document.getElementById("steuern-married").checked = !!p.filing_married;
  // CH: Kirchensteuer/Freibetrag sind DE-Konzepte -> Felder ausgrauen
  const isCH = p.country === "CH";
  document.getElementById("steuern-church").disabled = isCH;
  document.getElementById("steuern-freibetrag").disabled = isCH;
}

document.getElementById("steuern-profile-form").addEventListener("submit", async e => {
  e.preventDefault();
  const mtr = parseFloat(document.getElementById("steuern-mtr").value);
  const fb = parseFloat(document.getElementById("steuern-freibetrag").value);
  const payload = {
    church_tax_rate: parseFloat(document.getElementById("steuern-church").value) || 0,
    marginal_tax_rate: isFinite(mtr) ? mtr / 100 : 0,
    filing_married: document.getElementById("steuern-married").checked,
  };
  if (isFinite(fb)) payload.sparerpauschbetrag = fb;
  await api("/tax/profile", { method: "PUT", body: JSON.stringify(payload) });
  toast("Steuer-Profil gespeichert.");
  await loadSteuernTips();
});

async function setSteuernTipStatus(tipId, status) {
  const year = Number(document.getElementById("steuern-year").value) || new Date().getFullYear();
  try {
    await api(`/tax/tips/${encodeURIComponent(tipId)}/status`, {
      method: "POST", body: JSON.stringify({ year, status }),
    });
    await loadSteuernTips();
  } catch { /* api() zeigt den Fehler */ }
}
window.setSteuernTipStatus = setSteuernTipStatus;

async function loadSteuernTips() {
  const year = document.getElementById("steuern-year").value || new Date().getFullYear();
  const box = document.getElementById("steuern-tips");
  box.innerHTML = `<p class="page-sub">Wird geladen …</p>`;
  let data;
  try {
    data = await api(`/tax/tips?year=${year}`);
  } catch {
    box.innerHTML = `<p class="page-sub">Konnte die Tipps nicht laden.</p>`;
    return;
  }

  document.getElementById("steuern-country").textContent = data.country === "CH" ? "Schweiz" : "Deutschland";
  renderSteuernSummary(data.facts, data.country);

  box.innerHTML = data.tips.length
    ? data.tips.map(t => steuernTipCard(t, false)).join("")
    : `<p class="page-sub">Aktuell keine offenen Ansatzpunkte – solide aufgestellt.</p>`;

  const dwrap = document.getElementById("steuern-dismissed-wrap");
  const dbox = document.getElementById("steuern-dismissed");
  const dismissed = data.dismissed || [];
  dwrap.classList.toggle("hidden", !dismissed.length);
  dbox.innerHTML = dismissed.map(t => steuernTipCard(t, true)).join("");
}

function steuernTipCard(t, isDismissed) {
  const sev = STEUERN_SEV[t.severity] || STEUERN_SEV.info;
  const actions = isDismissed
    ? `<button type="button" class="btn-ghost btn-sm" onclick="setSteuernTipStatus('${t.id}','open')">wieder aufnehmen</button>
       <span class="steuern-area">${t.status === "done" ? "erledigt" : "nicht relevant"}</span>`
    : `<button type="button" class="btn-ghost btn-sm" onclick="setSteuernTipStatus('${t.id}','done')">✓ erledigt</button>
       <button type="button" class="btn-ghost btn-sm" onclick="setSteuernTipStatus('${t.id}','not_relevant')">nicht relevant</button>`;
  return `<div class="steuern-tip ${sev.cls}${isDismissed ? " is-dismissed" : ""}">
    <div class="steuern-tip-head">
      <span class="steuern-badge">${sev.label}</span>
      <strong>${steuernEsc(t.title)}</strong>
      <span class="steuern-area">${steuernEsc(STEUERN_AREA[t.area] || t.area)}</span>
    </div>
    <p>${steuernEsc(t.detail)}</p>
    <div class="steuern-tip-actions">${actions}</div>
  </div>`;
}

function renderSteuernSummary(f, country) {
  const cards = document.getElementById("steuern-summary-cards");
  const eur = v => (v == null ? "–" : Number(v).toLocaleString("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }));
  const items = [];
  if (country !== "CH") {
    items.push(["Geschätzte steuerpfl. Kapitalerträge", eur(f.kapitalertrag_geschaetzt)]);
    items.push(["Sparerpauschbetrag frei", eur(f.freibetrag_rest)]);
    if (f.kap_ueber_freibetrag > 0) items.push(["Über dem Freibetrag", eur(f.kap_ueber_freibetrag)]);
    items.push(["Realisierte Gewinne", eur(f.realisierte_gewinne)]);
  } else {
    items.push(["Dividenden (steuerbar)", eur(f.dividenden_jahr)]);
    items.push(["Nettovermögen", eur(f.nettovermoegen)]);
    items.push(["Realisierte Gewinne", eur(f.realisierte_gewinne) + " (privat steuerfrei)"]);
  }
  cards.innerHTML = items.map(([label, val]) =>
    `<div class="card"><span class="card-label">${steuernEsc(label)}</span><span class="card-value">${steuernEsc(val)}</span></div>`).join("");
}

document.getElementById("steuern-ask-form").addEventListener("submit", async e => {
  e.preventDefault();
  const input = document.getElementById("steuern-ask-input");
  const q = input.value.trim();
  if (!q) return;
  const reply = document.getElementById("steuern-ask-reply");
  reply.classList.remove("hidden", "is-error");
  reply.textContent = "Denkt nach …";
  const year = document.getElementById("steuern-year").value || new Date().getFullYear();
  try {
    const r = await api("/tax/ask", { method: "POST", body: JSON.stringify({ question: q, year: Number(year) }) });
    reply.textContent = r.reply || "–";
    reply.classList.toggle("is-error", !r.ok);
  } catch {
    reply.textContent = "Die Frage konnte nicht gesendet werden.";
    reply.classList.add("is-error");
  }
});

document.getElementById("steuern-proj-form").addEventListener("submit", async e => {
  e.preventDefault();
  const box = document.getElementById("steuern-proj-result");
  box.classList.remove("hidden");
  box.textContent = "Rechnet …";
  const num = id => parseFloat(document.getElementById(id).value) || 0;
  const payload = {
    start: num("proj-start"), monthly: num("proj-monthly"),
    annual_return_pct: num("proj-return"), years: Math.round(num("proj-years")) || 30,
    ter_pct: num("proj-ter"),
    church_tax_rate: document.getElementById("proj-church").checked ? undefined : 0,
  };
  let r;
  try {
    r = await api("/tax/project", { method: "POST", body: JSON.stringify(payload) });
  } catch { box.textContent = "Konnte nicht rechnen."; return; }
  const eur = v => Number(v).toLocaleString("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
  const a = r.annahmen;
  const row = (label, val, strong) =>
    `<div class="steuern-proj-row${strong ? " is-strong" : ""}"><span>${steuernEsc(label)}</span><em>${eur(val)}</em></div>`;
  box.innerHTML = `
    <p class="page-sub">${a.jahre} Jahre · ${a.rendite_pa_pct} % p.a. (nach ${a.ter_pct} % TER) · eingezahlt ${eur(r.eingezahlt)}</p>
    ${row("Endvermögen brutto (ohne jede Steuer)", r.brutto, true)}
    ${row("… nach laufender Steuer (Vorabpauschale) – ohne Kirchensteuer", r.ohne_kirchensteuer.netto_laufend)}
    ${row("… nach Verkauf – ohne Kirchensteuer", r.ohne_kirchensteuer.netto_nach_verkauf, true)}
    ${a.kirchensteuer_pct ? row("… nach Verkauf – mit Kirchensteuer", r.mit_kirchensteuer.netto_nach_verkauf) : ""}
    ${a.kirchensteuer_pct ? `<p class="page-sub">Kirchensteuer (${a.kirchensteuer_pct} %) kostet über die Laufzeit rund <strong>${eur(Math.abs(r.kirchensteuer_kostet))}</strong> Endvermögen.</p>` : `<p class="page-sub">Ohne Kirchensteuer gerechnet (Haken setzen, um sie einzubeziehen).</p>`}`;
});

document.getElementById("steuern-goto-report").addEventListener("click", e => {
  e.preventDefault();
  const btn = document.querySelector('.nav-btn[data-tab="investments"]');
  if (btn) btn.click();
  setTimeout(() => document.querySelector('[data-inv-subtab="steuer"]')?.click(), 150);
});

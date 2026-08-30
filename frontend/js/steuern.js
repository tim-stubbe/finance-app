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
  await loadSteuernTips();
}

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

  if (!data.tips.length) {
    box.innerHTML = `<p class="page-sub">Aktuell keine offensichtlichen Ansatzpunkte – solide aufgestellt.</p>`;
    return;
  }
  box.innerHTML = data.tips.map(t => {
    const sev = STEUERN_SEV[t.severity] || STEUERN_SEV.info;
    return `<div class="steuern-tip ${sev.cls}">
      <div class="steuern-tip-head">
        <span class="steuern-badge">${sev.label}</span>
        <strong>${steuernEsc(t.title)}</strong>
        <span class="steuern-area">${steuernEsc(STEUERN_AREA[t.area] || t.area)}</span>
      </div>
      <p>${steuernEsc(t.detail)}</p>
    </div>`;
  }).join("");
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

document.getElementById("steuern-goto-report").addEventListener("click", e => {
  e.preventDefault();
  const btn = document.querySelector('.nav-btn[data-tab="investments"]');
  if (btn) btn.click();
  setTimeout(() => document.querySelector('[data-inv-subtab="steuer"]')?.click(), 150);
});

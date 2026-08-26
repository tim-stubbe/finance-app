// ================= INIT =================
async function initCurrency() {
  try {
    const s = await api("/settings/currency");
    displayCurrency = s.currency;
    if (displayCurrency === "CHF") {
      const fx = await api("/fx/rate?to=CHF");
      displayRate = fx.rate;
    } else {
      displayRate = 1;
    }
  } catch (e) {
    displayCurrency = "EUR";
    displayRate = 1;
  }
  updateCurrencyToggleUI();
}

function updateCurrencyToggleUI() {
  document.querySelectorAll(".currency-toggle-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.currency === displayCurrency);
  });
}

// Wohnsitzland - unabhaengig von der Anzeige-Waehrung (EUR/CHF oben), blendet
// nur landesspezifische Anbindungs-Panels in den Einstellungen ein/aus (siehe
// [data-country-only] in index.html, z.B. FinTS ist deutschlandspezifisch).
function applyCountryVisibility(country) {
  document.querySelectorAll("[data-country-only]").forEach(panel => {
    panel.classList.toggle("hidden", panel.dataset.countryOnly !== country);
  });
  document.querySelectorAll("#country-switch [data-country-option]").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.countryOption === country);
  });
}

async function loadCountrySettings() {
  try {
    const s = await api("/settings/country");
    applyCountryVisibility(s.country);
  } catch (e) {
    applyCountryVisibility("DE");
  }
}

document.querySelectorAll("#country-switch [data-country-option]").forEach(btn => {
  btn.addEventListener("click", async () => {
    const country = btn.dataset.countryOption;
    await api("/settings/country", { method: "PUT", body: JSON.stringify({ country }) });
    applyCountryVisibility(country);
  });
});

document.querySelectorAll(".currency-toggle-btn").forEach(btn => {
  btn.addEventListener("click", async () => {
    if (btn.dataset.currency === displayCurrency) return;
    await api("/settings/currency", { method: "PUT", body: JSON.stringify({ currency: btn.dataset.currency }) });
    // Neu laden statt live umzurechnen - so ist garantiert, dass wirklich jede
    // Zahl (inkl. aller Chart-Daten) mit dem neuen Kurs konsistent ist, statt
    // an einer vergessenen Stelle den alten Wert stehen zu lassen.
    location.reload();
  });
});

async function init() {
  document.getElementById("tx-date").value = new Date().toISOString().slice(0, 10);
  document.getElementById("db-year").value = new Date().getFullYear();
  initThemeSwitchUI();
  moveNavIndicator(document.querySelector(".nav-btn.active"));
  await initCurrency();
  await loadAccounts();
  await loadCategories();
  // Hub ist jetzt die Startseite, nicht mehr das Dashboard - das lädt wie
  // jeder andere Tab erst bei Klick (siehe Zeile 112 und den nav-btn-Handler).
  await loadHubTab();
  await loadGlobalTopbar();
  refreshGoalsBadge();
  refreshProjectsBadge();
  refreshIntegrationBadge();
  // Ohne das bleibt immichSkipConfirm auf dem Standardwert false, bis der
  // Nutzer einmal den Einstellungen-Tab geöffnet hat - die Bestätigung beim
  // Papierkorb-Löschen im Fotos-Tab erschien dadurch trotz aktivierter
  // Einstellung immer wieder, weil der Wert nie aus dem Backend geladen wurde.
  loadImmichSettings().catch(() => {});
  loadVersionWatermark();
  handleEnableBankingReturn();
  handleEbayReturn();
}
startApp();

async function loadVersionWatermark() {
  const el = document.getElementById("version-watermark-hub");
  if (!el) return;
  let v;
  try {
    v = await api("/version");
  } catch (e) {
    el.textContent = "";
    return;
  }
  let text = v.git_sha === "dev" ? "lokaler Build" : v.git_sha_short;
  if (v.build_date) text += " · " + relativeTimeDe(new Date(v.build_date));
  let title = `Version ${v.git_sha}` + (v.build_date ? `, gebaut ${new Date(v.build_date).toLocaleString("de-DE")}` : "");

  el.innerHTML = `<span>${esc(text)}</span>`;
  el.title = title;
  el.classList.remove("is-outdated");

  // Veraltet-Hinweis: nur anzeigen, wenn sich der neueste veroeffentlichte
  // Stand wirklich ermitteln liess (setzt ein oeffentliches GHCR-Paket
  // voraus) UND er vom laufenden Stand abweicht. Laesst er sich nicht
  // ermitteln, bleibt die Zeile wie bisher - lieber nichts zeigen als etwas
  // Falsches behaupten.
  if (v.git_sha === "dev") return;
  try {
    const latest = await api("/version/latest");
    if (latest.available && latest.git_sha !== v.git_sha) {
      el.classList.add("is-outdated");
      el.innerHTML += ` <span title="Neuere Version veröffentlicht (${esc(latest.git_sha_short)}) – wartet auf Watchtower oder manuellen Neustart">⚠️ veraltet</span>`;
    }
  } catch (e) {
    // Stumm bleiben - der Vergleich ist ein Nice-to-have, kein Kernfeature.
  }
}

// Cursor-folgender Glanz auf Cards/Panels (siehe .card::before in style.css) -
// ein einzelner delegierter Listener statt einem pro Karte, da Karten/Panels
// staendig neu gerendert werden (jedes innerHTML= wuerde direkte Listener
// wieder verlieren).
document.addEventListener("mousemove", e => {
  const el = e.target.closest(".card, .panel, .integration-card");
  if (!el) return;
  const rect = el.getBoundingClientRect();
  el.style.setProperty("--mx", `${e.clientX - rect.left}px`);
  el.style.setProperty("--my", `${e.clientY - rect.top}px`);
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  });
}


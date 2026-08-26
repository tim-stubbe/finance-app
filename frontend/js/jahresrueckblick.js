// ================= JAHRESRÜCKBLICK ("Wrapped"-artige Story) =================
const MONTH_NAMES_DE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];
const YEAR_REVIEW_GRADIENTS = [
  "radial-gradient(circle at 50% 15%, #3987e5, #16223a 70%)",
  "radial-gradient(circle at 50% 15%, #d95926, #2a1608 70%)",
  "radial-gradient(circle at 50% 15%, #199e70, #0c2018 70%)",
  "radial-gradient(circle at 50% 15%, #9085e9, #1a1830 70%)",
  "radial-gradient(circle at 50% 15%, #d55181, #2a1220 70%)",
  "radial-gradient(circle at 50% 15%, #c98500, #2a1a08 70%)",
];

let yearReviewSlides = [];
let yearReviewIndex = 0;
let yearReviewTimer = null;

function buildYearReviewSlides(d) {
  const slides = [];
  slides.push({
    icon: "sparkles",
    eyebrow: `Jahresrückblick ${d.year}`,
    value: `${d.year}`,
    label: "Dein Jahr in Zahlen - so lief's finanziell.",
  });
  slides.push({
    icon: "trending-up",
    eyebrow: "Einnahmen & Ausgaben",
    value: eur(d.total_income),
    label: `Einnahmen im Jahr ${d.year}`,
    sub: `Ausgaben: ${eur(Math.abs(d.total_expense))}`,
  });
  if (d.savings_rate !== null) {
    slides.push({
      icon: "wallet",
      eyebrow: "Gespart",
      value: eur(d.saved),
      label: d.saved >= 0
        ? `Du hast ${d.savings_rate.toFixed(0)}% deiner Einnahmen zurückgelegt.`
        : `Du hast mehr ausgegeben als eingenommen.`,
    });
  }
  if (d.biggest_expense) {
    slides.push({
      icon: "flame",
      eyebrow: "Größte einzelne Ausgabe",
      value: eur(d.biggest_expense.amount),
      label: d.biggest_expense.name,
      sub: [d.biggest_expense.category_name, fmtDate(d.biggest_expense.date)].filter(Boolean).join(" · "),
    });
  }
  if (d.top_category) {
    slides.push({
      icon: "tag",
      eyebrow: "Teuerste Kategorie",
      value: eur(d.top_category.total),
      label: d.top_category.name,
      sub: `${d.top_category.count} Buchung(en)`,
    });
  }
  if (d.most_frequent_category && d.most_frequent_category.name !== (d.top_category && d.top_category.name)) {
    slides.push({
      icon: "repeat",
      eyebrow: "Am häufigsten gebucht",
      value: `${d.most_frequent_category.count}×`,
      label: d.most_frequent_category.name,
      sub: eur(d.most_frequent_category.total),
    });
  }
  if (d.busiest_month) {
    slides.push({
      icon: "calendar",
      eyebrow: "Aktivster Monat",
      value: MONTH_NAMES_DE[d.busiest_month.month - 1],
      label: `${d.busiest_month.count} Buchungen - dein geschäftigster Monat ${d.year}.`,
    });
  }
  if (d.income_change_pct !== null || d.expense_change_pct !== null) {
    const parts = [];
    if (d.income_change_pct !== null) parts.push(`Einnahmen ${d.income_change_pct >= 0 ? "+" : ""}${d.income_change_pct.toFixed(0)}%`);
    if (d.expense_change_pct !== null) parts.push(`Ausgaben ${d.expense_change_pct >= 0 ? "+" : ""}${d.expense_change_pct.toFixed(0)}%`);
    slides.push({
      icon: "trending-up",
      eyebrow: `Im Vergleich zu ${d.year - 1}`,
      value: parts.join(" · "),
      label: "Veränderung zum Vorjahr",
    });
  }
  if (d.investment_return_pct !== null) {
    slides.push({
      icon: "trending-up",
      eyebrow: "Investment-Rendite",
      value: `${d.investment_return_pct >= 0 ? "+" : ""}${d.investment_return_pct.toFixed(1)}%`,
      label: "Dein Portfolio der letzten 12 Monate.",
    });
  }
  slides.push({
    icon: "landmark",
    eyebrow: "Nettovermögen heute",
    value: eur(d.net_worth_now),
    label: "Dein aktueller Stand - weiter so!",
  });
  slides.push({
    icon: "check-circle",
    eyebrow: `${d.year}`,
    value: "Das war's!",
    label: "Bis zum nächsten Jahresrückblick.",
    isOutro: true,
  });
  return slides;
}

function renderYearReviewDots() {
  const dotsEl = document.getElementById("year-review-dots");
  dotsEl.innerHTML = yearReviewSlides.map((_, i) =>
    `<div class="year-review-dot ${i < yearReviewIndex ? "is-done" : i === yearReviewIndex ? "is-active" : ""}"></div>`
  ).join("");
}

function renderYearReviewSlide() {
  const slide = yearReviewSlides[yearReviewIndex];
  const el = document.getElementById("year-review-slide");
  el.style.setProperty("--yr-bg", YEAR_REVIEW_GRADIENTS[yearReviewIndex % YEAR_REVIEW_GRADIENTS.length]);
  el.innerHTML = `
    ${svgIcon(slide.icon, "year-review-icon")}
    <p class="year-review-eyebrow">${esc(slide.eyebrow)}</p>
    <p class="year-review-value">${esc(slide.value)}</p>
    <p class="year-review-label">${esc(slide.label)}</p>
    ${slide.sub ? `<p class="year-review-sub">${esc(slide.sub)}</p>` : ""}
    ${slide.isOutro ? `<button type="button" class="btn-primary" id="year-review-done">Schließen</button>` : ""}
  `;
  renderYearReviewDots();
  document.getElementById("year-review-done")?.addEventListener("click", closeYearReview);
  clearTimeout(yearReviewTimer);
  yearReviewTimer = setTimeout(yearReviewNext, 5000);
}

function yearReviewNext() {
  if (yearReviewIndex >= yearReviewSlides.length - 1) { closeYearReview(); return; }
  yearReviewIndex++;
  renderYearReviewSlide();
}
function yearReviewPrev() {
  yearReviewIndex = Math.max(0, yearReviewIndex - 1);
  renderYearReviewSlide();
}

async function openYearReview() {
  let data;
  try {
    data = await api(`/year-review?year=${new Date().getFullYear()}`);
  } catch (e) {
    return;
  }
  yearReviewSlides = buildYearReviewSlides(data);
  yearReviewIndex = 0;
  document.getElementById("year-review-overlay").classList.remove("hidden");
  renderYearReviewSlide();
}

function closeYearReview() {
  clearTimeout(yearReviewTimer);
  document.getElementById("year-review-overlay").classList.add("hidden");
}

document.getElementById("sync-all-btn").addEventListener("click", async () => {
  const btn = document.getElementById("sync-all-btn");
  const resultEl = document.getElementById("sync-all-result");
  btn.disabled = true;
  const originalHtml = btn.innerHTML;
  btn.textContent = "Synchronisiere …";
  resultEl.classList.add("hidden");
  try {
    const result = await api("/sync-all", { method: "POST" });
    if (result.connections.length === 0) {
      resultEl.textContent = "Keine Bank-/Broker-Verbindungen eingerichtet (siehe Einstellungen).";
    } else {
      resultEl.textContent = result.connections.map(c => `${c.name} (${c.kind}): ${c.status || "–"}`).join(" · ");
    }
    resultEl.classList.remove("hidden");
    loadHubTab();
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
  }
});
document.getElementById("year-review-open").addEventListener("click", openYearReview);
document.getElementById("year-review-close").addEventListener("click", closeYearReview);
document.getElementById("year-review-next").addEventListener("click", yearReviewNext);
document.getElementById("year-review-prev").addEventListener("click", yearReviewPrev);
document.addEventListener("keydown", e => {
  if (document.getElementById("year-review-overlay").classList.contains("hidden")) return;
  if (e.key === "ArrowRight") yearReviewNext();
  else if (e.key === "ArrowLeft") yearReviewPrev();
  else if (e.key === "Escape") closeYearReview();
});


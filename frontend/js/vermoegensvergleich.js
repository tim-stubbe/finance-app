// ================= VERMÖGENSVERGLEICH =================
let benchmarkChart = null;

async function loadBenchmark() {
  const data = await api("/benchmark");
  const box = document.getElementById("benchmark-result");
  const hint = document.getElementById("benchmark-hint");

  document.getElementById("profile-birth-year").value = data.birth_year ?? "";

  if (!data.configured) {
    box.classList.add("hidden");
    hint.classList.remove("hidden");
    return;
  }
  box.classList.remove("hidden");
  hint.classList.add("hidden");

  const own = data.brackets.find(b => b.is_own);
  // Bei Werten ausserhalb der belegten Marken ist nur die Grenze bekannt -
  // dann keine Scheingenauigkeit vortäuschen.
  const pctText = data.percentile_exact
    ? `rund ${Math.round(data.percentile)} %`
    : (data.percentile >= 90 ? "über 90 %" : "unter 10 %");

  document.getElementById("benchmark-headline").innerHTML =
    `Mit ${data.age} Jahren gehörst du zur Gruppe <strong>${esc(own.label)}</strong>.
     Dein Nettovermögen von <strong>${eur(data.net_worth)}</strong> liegt über dem von
     <strong>${pctText}</strong> der Haushalte dieser Gruppe.<br>
     <span class="benchmark-verdict">${esc(data.verdict)}</span>`;

  // Skala der eigenen Gruppe: die drei belegten Marken plus die eigene Lage.
  document.getElementById("benchmark-scale").innerHTML = `
    <div class="benchmark-marks">
      <div><span class="benchmark-mark-label">Untere 10 %</span><span>${eur(own.p10)}</span></div>
      <div><span class="benchmark-mark-label">Median (50 %)</span><span>${eur(own.p50)}</span></div>
      <div><span class="benchmark-mark-label">Obere 10 % ab</span><span>${eur(own.p90)}</span></div>
    </div>`;

  const labels = data.brackets.map(b => b.label);
  const medians = data.brackets.map(b => toDisplay(b.p50));
  const eigen = data.brackets.map(() => toDisplay(data.net_worth));

  if (benchmarkChart) benchmarkChart.destroy();
  benchmarkChart = new Chart(document.getElementById("benchmark-chart"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: `Median der Altersgruppe (${data.data_year})`,
          data: medians,
          // Die eigene Gruppe hervorheben, die anderen zurücknehmen.
          backgroundColor: data.brackets.map(b =>
            b.is_own ? cssVar("--accent-strong") : cssVar("--border-strong")),
          borderRadius: 6,
        },
        {
          label: "Dein Nettovermögen",
          data: eigen,
          type: "line",
          borderColor: cssVar("--pos"),
          borderWidth: 2,
          borderDash: [6, 4],
          pointRadius: 0,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: cssVar("--text-secondary") } },
        tooltip: { callbacks: { label: c => `${c.dataset.label}: ${eur(c.raw / displayRate)}` } },
      },
      scales: {
        x: { ticks: { color: cssVar("--muted") }, grid: { display: false } },
        y: {
          ticks: { color: cssVar("--muted"), callback: v => eur(v / displayRate) },
          grid: { color: cssVar("--border") },
        },
      },
    },
  });

  document.getElementById("benchmark-note").innerHTML =
    `Quelle: ${esc(data.source)} (Stand ${data.data_year}).
     <a href="${esc(data.source_url)}" target="_blank" rel="noopener">Zur Studie</a>.
     Verglichen werden <strong>Haushalts</strong>vermögen, zugeordnet nach dem Alter der ältesten
     Person im Haushalt – bei einem Paarhaushalt steht dort also das Vermögen von zwei Personen.
     Enthalten sind dort auch Immobilien, Fahrzeuge und Betriebsvermögen: Was du hier in der App
     nicht erfasst hast, fehlt auf deiner Seite des Vergleichs.`;
}

document.getElementById("birth-year-form").addEventListener("submit", async e => {
  e.preventDefault();
  const raw = document.getElementById("profile-birth-year").value;
  const birth_year = raw === "" ? null : parseInt(raw, 10);
  await api("/settings/birth-year", { method: "PUT", body: JSON.stringify({ birth_year }) });
  toast("Geburtsjahr gespeichert.");
  await loadBenchmark();
});


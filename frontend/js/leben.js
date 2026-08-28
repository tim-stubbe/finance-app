// ================= LEBEN (persönliche Lebensbereiche) =================
let lifeAreasCache = [];

async function loadLifeTab() {
  const [areas, checkins] = await Promise.all([
    api("/life-areas"),
    api("/life-checkins"),
  ]);
  lifeAreasCache = areas;
  loadLifeYearHeatmap();
  const checkinsByArea = new Map();
  checkins.forEach(c => {
    if (!checkinsByArea.has(c.area_id)) checkinsByArea.set(c.area_id, []);
    checkinsByArea.get(c.area_id).push(c);
  });

  const list = document.getElementById("life-areas-list");
  if (!areas.length) {
    list.innerHTML = `<div class="empty-state"><span class="empty-icon">${svgIcon("target")}</span><span>Noch keine Lebensbereiche angelegt. Leg oben rechts einen an.</span></div>`;
  } else {
    list.innerHTML = "";
    areas.forEach(a => list.appendChild(renderLifeAreaCard(a, (checkinsByArea.get(a.id) || []).slice(0, 5))));
  }

  loadContacts();
  loadMediaItems();
  loadHealthMetrics();
}

// ---------- Kontakte (People/CRM-Light) ----------
async function loadContacts() {
  const contacts = await api("/contacts");
  const tbody = document.getElementById("contacts-list");
  if (!contacts.length) {
    tbody.innerHTML = emptyRow(4, "user", "Noch keine Kontakte.");
    return;
  }
  tbody.innerHTML = contacts.map(c => `
    <tr>
      <td>${esc(c.name)}</td>
      <td>${esc(c.notes || "–")}</td>
      <td>${c.last_interaction_at ? fmtDate(c.last_interaction_at) : "–"}</td>
      <td>
        <button type="button" class="link-btn" data-contact-touch="${c.id}">Jetzt kontaktiert</button>
        <button type="button" class="link-btn" data-contact-delete="${c.id}">Löschen</button>
      </td>
    </tr>`).join("");
}

document.getElementById("contact-form").addEventListener("submit", async e => {
  e.preventDefault();
  const name = document.getElementById("contact-name").value.trim();
  if (!name) return;
  await api("/contacts", {
    method: "POST",
    body: JSON.stringify({ name, notes: document.getElementById("contact-notes").value.trim() || null }),
  });
  document.getElementById("contact-form").reset();
  loadContacts();
});

document.getElementById("contacts-list").addEventListener("click", async e => {
  const touchId = e.target.closest("[data-contact-touch]")?.dataset.contactTouch;
  if (touchId) {
    await api(`/contacts/${touchId}/touch`, { method: "POST" });
    loadContacts();
    return;
  }
  const delId = e.target.closest("[data-contact-delete]")?.dataset.contactDelete;
  if (delId) {
    await api(`/contacts/${delId}`, { method: "DELETE" });
    loadContacts();
  }
});

// ---------- Leseliste / Medien-Tracking ----------
let mediaCache = [];
let mediaFilter = "alle";
const MEDIA_STATUS_LABELS = { offen: "Offen", "läuft": "Läuft", fertig: "Fertig", abgebrochen: "Abgebrochen" };

async function loadMediaItems() {
  mediaCache = await api("/media");
  renderMediaList();
}

function renderMediaList() {
  const tbody = document.getElementById("media-list");
  const items = mediaFilter === "alle" ? mediaCache : mediaCache.filter(m => m.status === mediaFilter);
  if (!items.length) {
    tbody.innerHTML = emptyRow(4, "file-text", "Nichts in der Leseliste.");
    return;
  }
  tbody.innerHTML = items.map(m => `
    <tr>
      <td>${m.url ? `<a href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.title)}</a>` : esc(m.title)}</td>
      <td>${esc(m.media_type)}</td>
      <td>
        <select data-media-status="${m.id}">
          ${Object.entries(MEDIA_STATUS_LABELS).map(([v, l]) => `<option value="${v}" ${v === m.status ? "selected" : ""}>${l}</option>`).join("")}
        </select>
      </td>
      <td><button type="button" class="link-btn" data-media-delete="${m.id}">Löschen</button></td>
    </tr>`).join("");
}

document.querySelectorAll("#media-filter-tabs .range-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#media-filter-tabs .range-tab").forEach(b => b.classList.toggle("active", b === btn));
    mediaFilter = btn.dataset.mediaFilter;
    renderMediaList();
  });
});

document.getElementById("media-form").addEventListener("submit", async e => {
  e.preventDefault();
  const title = document.getElementById("media-title").value.trim();
  if (!title) return;
  await api("/media", {
    method: "POST",
    body: JSON.stringify({
      title,
      media_type: document.getElementById("media-type").value.trim() || "Buch",
      url: document.getElementById("media-url").value.trim() || null,
    }),
  });
  document.getElementById("media-form").reset();
  document.getElementById("media-type").value = "Buch";
  loadMediaItems();
});

document.getElementById("media-list").addEventListener("change", async e => {
  const id = e.target.closest("[data-media-status]")?.dataset.mediaStatus;
  if (id) await api(`/media/${id}`, { method: "PATCH", body: JSON.stringify({ status: e.target.value }) });
});

document.getElementById("media-list").addEventListener("click", async e => {
  const delId = e.target.closest("[data-media-delete]")?.dataset.mediaDelete;
  if (delId) {
    await api(`/media/${delId}`, { method: "DELETE" });
    loadMediaItems();
  }
});

// ---------- Gesundheits-Grunddaten ----------
let healthChart = null;

async function loadHealthMetrics() {
  const type = document.getElementById("health-metric-type").value;
  const points = await api(`/health-metrics?metric_type=${type}&days=90`);
  const ctx = document.getElementById("chart-health");
  const label = type === "gewicht" ? "Gewicht (kg)" : "Schlaf (Std.)";
  const data = {
    labels: points.map(p => fmtDate(p.date)),
    datasets: [{
      label, data: points.map(p => p.value),
      borderColor: cssVar("--accent"), backgroundColor: "transparent", tension: 0.25, pointRadius: 2,
    }],
  };
  if (healthChart) { healthChart.destroy(); healthChart = null; }
  if (!points.length) return;
  healthChart = new Chart(ctx, {
    type: "line", data,
    options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: false } } },
  });
}

document.getElementById("health-metric-type").addEventListener("change", loadHealthMetrics);

document.getElementById("health-form").addEventListener("submit", async e => {
  e.preventDefault();
  const dateVal = document.getElementById("health-date").value;
  const value = parseFloat(document.getElementById("health-value").value);
  if (!dateVal || isNaN(value)) return;
  await api("/health-metrics", {
    method: "POST",
    body: JSON.stringify({ metric_type: document.getElementById("health-metric-type").value, date: dateVal, value }),
  });
  document.getElementById("health-form").reset();
  loadHealthMetrics();
});

function lifeAreaIsOverdue(a) {
  if (!a.check_interval_days) return false;
  // Fallback auf created_at spiegelt main._scheduled_life_check_reminder.
  const reference = new Date(a.last_checked_at || a.created_at);
  const days = (Date.now() - reference.getTime()) / (1000 * 60 * 60 * 24);
  return days >= a.check_interval_days;
}

function renderLifeAreaHeatmap(a) {
  const days = a.checkin_days_30 || [];
  const daySet = new Set(days);
  const cells = [];
  for (let i = 29; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    const iso = d.toISOString().slice(0, 10);
    cells.push(`<span class="life-heatmap-day${daySet.has(iso) ? " filled" : ""}" title="${iso}"></span>`);
  }
  return `<div class="life-heatmap">${cells.join("")}</div>`;
}

const WEEKDAY_LABELS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

function renderLifeAreaWeekGrid(a) {
  if (!a.target_days_per_week) return "";
  const weekDays = a.week_days || [];
  const done = weekDays.filter(Boolean).length;
  const met = done >= a.target_days_per_week;
  const cells = WEEKDAY_LABELS.map((label, i) => `
    <div class="life-week-cell${weekDays[i] ? " filled" : ""}">
      <span class="life-week-daylabel">${label}</span>
      <span class="life-week-check">${weekDays[i] ? "✓" : ""}</span>
    </div>
  `).join("");
  return `
    <div class="life-week-grid-wrap">
      <p class="page-sub life-week-count${met ? " met" : ""}">${done}/${a.target_days_per_week}x diese Woche${met ? " ✓" : ""}</p>
      <div class="life-week-grid">${cells}</div>
    </div>
  `;
}

function renderLifeAreaCard(a, recentCheckins) {
  const card = document.createElement("div");
  card.className = "goal-card";
  const overdue = lifeAreaIsOverdue(a);
  const lastChecked = a.last_checked_at
    ? new Date(a.last_checked_at).toLocaleDateString("de-DE")
    : "noch kein Check-in";
  const progress = a.progress_percent != null ? a.progress_percent : null;
  const streak = a.streak_days || 0;
  card.innerHTML = `
    <div class="goal-card-head">
      <h4>${esc(a.name)}</h4>
      ${a.target_date ? `<span class="goal-chip">bis ${fmtDate(a.target_date)}</span>` : ""}
    </div>
    ${a.description ? `<p class="goal-desc">${esc(a.description)}</p>` : ""}
    ${progress != null ? `
      <div class="budget-track"><div class="goal-fill${progress >= 100 ? " done" : ""}" style="width:${Math.min(progress, 100)}%"></div></div>
      <p class="goal-values">${progress}%</p>
    ` : ""}
    <p class="goal-meta ${overdue ? "goal-error" : ""}">
      ${overdue ? "⚠️ " : ""}Letzter Check-in: ${lastChecked}${a.check_interval_days ? ` · Intervall ${a.check_interval_days} Tage` : ""}
    </p>
    <div class="life-streak${streak > 0 ? " active" : ""}">${streak > 0 ? `🔥 ${streak} Tag${streak === 1 ? "" : "e"} Streak` : "Noch keine Streak"}</div>
    ${renderLifeAreaWeekGrid(a)}
    ${renderLifeAreaHeatmap(a)}
    <div class="todo-row-list">
      ${recentCheckins.map(c => `
        <div class="todo-row">
          <span class="todo-title">${esc(c.note)}</span>
          <span class="page-sub">${new Date(c.created_at).toLocaleDateString("de-DE")}</span>
        </div>
      `).join("")}
    </div>
    <div class="filter-row" style="margin-top:4px">
      ${checkedInToday(a)
        ? `<span class="btn-ghost btn-sm" style="cursor:default;opacity:0.7">✓ Heute erledigt</span>`
        : `<button type="button" class="btn-primary btn-sm" data-life-tick="${a.id}">✓ Heute</button>`}
      <button type="button" class="btn-ghost btn-sm" data-life-checkin="${a.id}">+ Check-in mit Notiz</button>
      <button type="button" class="link-btn" data-life-edit="${a.id}">Bearbeiten</button>
      <button type="button" class="link-btn" data-notes-entity="life_area" data-notes-id="${a.id}" data-notes-label="${esc(a.name)}">📝 Notizen</button>
    </div>
  `;
  return card;
}

// Für den Ein-Klick-Häkchen-Button: heute schon abgehakt, wenn ein Streak-Tag
// den heutigen ISO-Tag enthält - dieselbe Datenquelle wie die Heatmap, kein
// zusätzlicher Serverstatus nötig.
function checkedInToday(a) {
  const today = new Date().toISOString().slice(0, 10);
  return (a.checkin_days_30 || []).includes(today);
}

document.getElementById("life-areas-list").addEventListener("click", async e => {
  const tickId = e.target.closest("[data-life-tick]")?.dataset.lifeTick;
  if (tickId) {
    await api("/life-checkins", { method: "POST", body: JSON.stringify({ area_id: parseInt(tickId), note: "Erledigt" }) });
    toast("Häkchen gesetzt.");
    loadLifeTab();
    return;
  }
  const checkinId = e.target.closest("[data-life-checkin]")?.dataset.lifeCheckin;
  if (checkinId) {
    document.getElementById("life-checkin-area-id").value = checkinId;
    document.getElementById("life-checkin-form").reset();
    document.getElementById("life-checkin-modal").classList.remove("hidden");
    return;
  }
  const editId = e.target.closest("[data-life-edit]")?.dataset.lifeEdit;
  if (editId) {
    openLifeAreaModal(lifeAreasCache.find(a => a.id === parseInt(editId)));
  }
});

function openLifeAreaModal(area) {
  document.getElementById("life-area-modal-title").textContent = area ? "Lebensbereich bearbeiten" : "Neuer Lebensbereich";
  document.getElementById("life-area-id").value = area ? area.id : "";
  document.getElementById("life-area-name").value = area ? area.name : "";
  document.getElementById("life-area-description").value = area?.description || "";
  document.getElementById("life-area-target-date").value = area?.target_date || "";
  document.getElementById("life-area-progress").value = area?.progress_percent ?? "";
  document.getElementById("life-area-interval").value = area?.check_interval_days || "";
  document.getElementById("life-area-week-target").value = area?.target_days_per_week || "";
  document.getElementById("life-area-archive").classList.toggle("hidden", !area);
  document.getElementById("life-area-modal").classList.remove("hidden");
}
document.getElementById("life-area-new-btn").addEventListener("click", () => openLifeAreaModal(null));
document.getElementById("life-area-modal-close").addEventListener("click", () => {
  document.getElementById("life-area-modal").classList.add("hidden");
});
document.getElementById("life-checkin-modal-close").addEventListener("click", () => {
  document.getElementById("life-checkin-modal").classList.add("hidden");
});

document.getElementById("life-area-form").addEventListener("submit", async e => {
  e.preventDefault();
  const id = document.getElementById("life-area-id").value;
  const progressVal = document.getElementById("life-area-progress").value;
  const payload = {
    name: document.getElementById("life-area-name").value,
    description: document.getElementById("life-area-description").value || null,
    target_date: document.getElementById("life-area-target-date").value || null,
    progress_percent: progressVal !== "" ? parseInt(progressVal) : null,
    check_interval_days: document.getElementById("life-area-interval").value
      ? parseInt(document.getElementById("life-area-interval").value) : null,
    target_days_per_week: document.getElementById("life-area-week-target").value
      ? parseInt(document.getElementById("life-area-week-target").value) : null,
  };
  if (id) {
    await api(`/life-areas/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
  } else {
    await api("/life-areas", { method: "POST", body: JSON.stringify(payload) });
  }
  document.getElementById("life-area-modal").classList.add("hidden");
  loadLifeTab();
});

document.getElementById("life-area-archive").addEventListener("click", async () => {
  const id = document.getElementById("life-area-id").value;
  if (!id || !confirm("Lebensbereich archivieren? Der Verlauf bleibt erhalten, der Bereich verschwindet aber aus der Liste.")) return;
  await api(`/life-areas/${id}`, { method: "PATCH", body: JSON.stringify({ active: false }) });
  document.getElementById("life-area-modal").classList.add("hidden");
  loadLifeTab();
});

document.getElementById("life-checkin-form").addEventListener("submit", async e => {
  e.preventDefault();
  const progressVal = document.getElementById("life-checkin-progress").value;
  const payload = {
    area_id: parseInt(document.getElementById("life-checkin-area-id").value),
    note: document.getElementById("life-checkin-note").value,
    progress_percent: progressVal !== "" ? parseInt(progressVal) : null,
  };
  await api("/life-checkins", { method: "POST", body: JSON.stringify(payload) });
  document.getElementById("life-checkin-modal").classList.add("hidden");
  loadLifeTab();
});


// ---------- Jahres-Heatmap (GitHub-Stil) über alle Lebensbereiche ----------
async function loadLifeYearHeatmap() {
  const panel = document.getElementById("life-year-panel");
  let data = [];
  try { data = await api("/life-areas/heatmap?days=371"); } catch { panel.hidden = true; return; }
  if (!data.length || !data.some(d => d.count > 0)) { panel.hidden = true; return; }
  panel.hidden = false;
  const first = new Date(data[0].date + "T00:00:00");
  const pad = (first.getDay() + 6) % 7;               // Mo = 0
  const cells = Array(pad).fill(null).concat(data);
  const weeks = Math.ceil(cells.length / 7);
  const max = Math.max(...data.map(d => d.count), 1);
  const lvl = c => c === 0 ? 0 : Math.min(4, 1 + Math.floor((c - 1) / max * 3));
  const S = 13, G = 3;
  let rects = "";
  cells.forEach((c, i) => {
    if (!c) return;
    const wk = Math.floor(i / 7), dy = i % 7;
    rects += `<rect x="${wk * (S + G)}" y="${dy * (S + G)}" width="${S}" height="${S}" rx="2" class="lyh lyh-${lvl(c.count)}"><title>${c.date}: ${c.count} Check-in(s)</title></rect>`;
  });
  document.getElementById("life-year-heatmap").innerHTML =
    `<svg class="life-year-heatmap-svg" viewBox="0 0 ${weeks * (S + G)} ${7 * (S + G)}" preserveAspectRatio="xMinYMin meet">${rects}</svg>`;
}

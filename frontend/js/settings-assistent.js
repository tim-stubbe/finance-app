// ================= JARVIS-VERHALTEN: MORGEN-BRIEFING, QUIET MODE, AKTIVITÄT =================
// Einstellungen → Benachrichtigungen (siehe index.html settings-view-
// benachrichtigungen) - Endpunkte in main.py (settings/morning-briefing,
// settings/quiet-hours, settings/quiet-until, assistant/suggestions).

function _fillHourSelect(sel) {
  if (sel.options.length) return;
  for (let h = 0; h < 24; h++) {
    const opt = document.createElement("option");
    opt.value = h;
    opt.textContent = `${String(h).padStart(2, "0")} Uhr`;
    sel.appendChild(opt);
  }
}
function _fillMinuteSelect(sel) {
  if (sel.options.length) return;
  for (const m of [0, 15, 30, 45]) {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = String(m).padStart(2, "0");
    sel.appendChild(opt);
  }
}

// ---------- Morgen-Briefing ----------
async function loadMorningBriefingSettings() {
  _fillHourSelect(document.getElementById("morning-briefing-hour"));
  _fillMinuteSelect(document.getElementById("morning-briefing-minute"));
  const s = await api("/settings/morning-briefing");
  document.getElementById("morning-briefing-enabled").checked = s.enabled;
  document.getElementById("morning-briefing-hour").value = s.hour;
  document.getElementById("morning-briefing-minute").value = s.minute;
  document.getElementById("morning-briefing-send-empty").checked = s.send_empty;
}

document.getElementById("morning-briefing-form").addEventListener("submit", async e => {
  e.preventDefault();
  await api("/settings/morning-briefing", {
    method: "PUT",
    body: JSON.stringify({
      enabled: document.getElementById("morning-briefing-enabled").checked,
      hour: parseInt(document.getElementById("morning-briefing-hour").value, 10),
      minute: parseInt(document.getElementById("morning-briefing-minute").value, 10),
      send_empty: document.getElementById("morning-briefing-send-empty").checked,
    }),
  });
  toast("Morgen-Briefing gespeichert.");
});

// ---------- Quiet Mode ----------
async function loadQuietHoursSettings() {
  _fillHourSelect(document.getElementById("quiet-hours-start"));
  _fillHourSelect(document.getElementById("quiet-hours-end"));
  const s = await api("/settings/quiet-hours");
  document.getElementById("quiet-hours-enabled").checked = s.enabled;
  document.getElementById("quiet-hours-start").value = s.start_hour;
  document.getElementById("quiet-hours-end").value = s.end_hour;

  const statusEl = document.getElementById("quiet-until-status");
  const clearBtn = document.getElementById("quiet-until-clear");
  if (s.quiet_until && new Date(s.quiet_until) > new Date()) {
    statusEl.textContent = `Manuell still bis ${new Date(s.quiet_until).toLocaleString("de-DE")}.`;
    clearBtn.classList.remove("hidden");
  } else {
    statusEl.textContent = "Keine manuelle Überschreibung aktiv.";
    clearBtn.classList.add("hidden");
  }
}

document.getElementById("quiet-hours-form").addEventListener("submit", async e => {
  e.preventDefault();
  await api("/settings/quiet-hours", {
    method: "PUT",
    body: JSON.stringify({
      enabled: document.getElementById("quiet-hours-enabled").checked,
      start_hour: parseInt(document.getElementById("quiet-hours-start").value, 10),
      end_hour: parseInt(document.getElementById("quiet-hours-end").value, 10),
    }),
  });
  toast("Ruhezeiten gespeichert.");
});

document.getElementById("quiet-until-set").addEventListener("click", async () => {
  const val = document.getElementById("quiet-until-input").value;
  if (!val) return;
  // val ist "HH:MM" (Feldtyp time) - heute damit befuellen, liegt der
  // Zeitpunkt schon in der Vergangenheit, ist morgen gemeint (gleiche Logik
  // wie beim Telegram-Kommando /ruhe HH:MM, siehe telegram_bot.py).
  const [h, m] = val.split(":").map(Number);
  const target = new Date();
  target.setHours(h, m, 0, 0);
  if (target <= new Date()) target.setDate(target.getDate() + 1);
  await api("/settings/quiet-until", { method: "PUT", body: JSON.stringify({ until: target.toISOString() }) });
  await loadQuietHoursSettings();
  toast("Ruhe gesetzt.");
});

document.getElementById("quiet-until-clear").addEventListener("click", async () => {
  await api("/settings/quiet-until", { method: "PUT", body: JSON.stringify({ until: null }) });
  await loadQuietHoursSettings();
  toast("Ruhe-Überschreibung aufgehoben.");
});

// ---------- Mid-Week-Zwischenstand ----------
async function loadMidweekCheckinSettings() {
  const s = await api("/settings/midweek-checkin");
  document.getElementById("midweek-checkin-enabled").checked = s.enabled;
}

document.getElementById("midweek-checkin-enabled").addEventListener("change", async e => {
  await api("/settings/midweek-checkin", { method: "PUT", body: JSON.stringify({ enabled: e.target.checked }) });
  toast(e.target.checked ? "Mid-Week-Zwischenstand aktiviert." : "Mid-Week-Zwischenstand deaktiviert.");
});

// ---------- "Was Jarvis getan hat" ----------
const ASSISTANT_SUGGESTION_STATUS_LABELS = {
  pending: "offen", accepted: "bestätigt", rejected: "abgelehnt", snoozed: "verschoben",
};

async function loadAssistantActivity() {
  const list = document.getElementById("assistant-activity-list");
  let items = [];
  try {
    items = await api("/assistant/suggestions");
  } catch (e) {
    return;
  }
  if (!items.length) {
    list.innerHTML = `<li class="page-sub" style="background:none;padding:0">Noch keine Vorschläge.</li>`;
    return;
  }
  list.innerHTML = items.map(s => `
    <li>
      <span>${esc(s.title)}</span>
      <span class="page-sub">${ASSISTANT_SUGGESTION_STATUS_LABELS[s.status] || esc(s.status)} · ${new Date(s.created_at).toLocaleDateString("de-DE")}</span>
    </li>`).join("");
}

// ---------- Routinen (Einstellungen: anlegen/löschen; Abhaken im Hub, siehe dashboard.js) ----------
const WEEKDAY_LABELS_DE = { mon: "Mo", tue: "Di", wed: "Mi", thu: "Do", fri: "Fr", sat: "Sa", sun: "So" };

async function loadRoutinesSettings() {
  _fillHourSelect(document.getElementById("routine-hour"));
  _fillMinuteSelect(document.getElementById("routine-minute"));
  const list = document.getElementById("routines-list");
  let routines = [];
  try {
    routines = await api("/routines");
  } catch (e) {
    return;
  }
  if (!routines.length) {
    list.innerHTML = `<li class="page-sub" style="background:none;padding:0">Noch keine Routinen angelegt.</li>`;
    return;
  }
  list.innerHTML = routines.map(r => `
    <li>
      <span>${esc(r.name)} <span class="page-sub">(${r.weekdays.map(w => WEEKDAY_LABELS_DE[w] || w).join(", ")}, ${String(r.hour).padStart(2, "0")}:${String(r.minute).padStart(2, "0")} Uhr, ${r.items.length} Punkt${r.items.length !== 1 ? "e" : ""})</span></span>
      <button type="button" class="btn-ghost btn-sm" data-delete-routine="${r.id}">Löschen</button>
    </li>`).join("");
}

document.getElementById("routines-list").addEventListener("click", async e => {
  const btn = e.target.closest("[data-delete-routine]");
  if (!btn) return;
  if (!confirm("Routine wirklich löschen?")) return;
  await api(`/routines/${btn.dataset.deleteRoutine}`, { method: "DELETE" });
  loadRoutinesSettings();
});

document.getElementById("routine-weekdays").addEventListener("click", e => {
  const btn = e.target.closest("[data-weekday]");
  if (!btn) return;
  btn.classList.toggle("active");
});

document.getElementById("routine-form").addEventListener("submit", async e => {
  e.preventDefault();
  const weekdays = [...document.querySelectorAll("#routine-weekdays .theme-option.active")].map(b => b.dataset.weekday);
  if (!weekdays.length) {
    toast("Bitte mindestens einen Wochentag wählen.");
    return;
  }
  const items = document.getElementById("routine-items").value.split("\n").map(s => s.trim()).filter(Boolean);
  await api("/routines", {
    method: "POST",
    body: JSON.stringify({
      name: document.getElementById("routine-name").value,
      weekdays,
      hour: parseInt(document.getElementById("routine-hour").value, 10),
      minute: parseInt(document.getElementById("routine-minute").value, 10),
      items,
      active: true,
    }),
  });
  document.getElementById("routine-form").reset();
  document.querySelectorAll("#routine-weekdays .theme-option.active").forEach(b => b.classList.remove("active"));
  loadRoutinesSettings();
  toast("Routine angelegt.");
});

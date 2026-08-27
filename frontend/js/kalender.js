// ================= KALENDER =================
let calendarEventsCache = [];
let calendarCollectionsCache = [];

function fmtDateTime(iso) {
  const d = new Date(iso);
  return d.toLocaleString("de-DE", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

async function loadCalendarTab() {
  calendarCollectionsCache = await api("/calendar/collections").catch(() => []);
  await loadCalendarEvents();
  await loadCalendarConflicts();
}

async function loadCalendarConflicts() {
  const warn = document.getElementById("calendar-conflict-warning");
  const conflicts = await api("/calendar/conflicts?days=30").catch(() => []);
  if (!conflicts.length) {
    warn.classList.add("hidden");
    return;
  }
  warn.innerHTML = `⚠️ ${conflicts.length} Terminüberschneidung${conflicts.length > 1 ? "en" : ""}: ` +
    conflicts.map(c => `„${esc(c.event_a_title)}“ ↔ „${esc(c.event_b_title)}“ (${fmtDateTime(c.event_a_start)})`).join(" · ");
  warn.classList.remove("hidden");
}

async function loadCalendarEvents() {
  const showPast = document.getElementById("calendar-show-past").checked;
  const start = new Date();
  start.setDate(start.getDate() - (showPast ? 30 : 0));
  start.setHours(0, 0, 0, 0);
  const end = new Date();
  end.setDate(end.getDate() + 60);
  end.setHours(23, 59, 59, 0);
  const list = document.getElementById("calendar-event-list");
  list.innerHTML = skelRows ? skelRows(3) : "";
  try {
    calendarEventsCache = await api(`/calendar-events?start=${start.toISOString()}&end=${end.toISOString()}`);
  } catch (e) {
    list.innerHTML = `<p class="page-sub">${esc(e.message)}</p>`;
    return;
  }
  renderCalendarEvents();
}

function renderCalendarEvents() {
  const list = document.getElementById("calendar-event-list");
  if (!calendarEventsCache.length) {
    list.innerHTML = `<div class="empty-state"><span class="empty-icon">${svgIcon("calendar")}</span><span>Keine Termine im gewählten Zeitraum.</span></div>`;
    return;
  }
  const now = new Date();
  const groups = new Map();
  calendarEventsCache.forEach(ev => {
    const key = new Date(ev.start).toLocaleDateString("de-DE", { weekday: "long", day: "2-digit", month: "2-digit", year: "numeric" });
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(ev);
  });
  list.innerHTML = [...groups.entries()].map(([day, events]) => `
    <div class="calendar-day-group">
      <h4 class="calendar-day-label">${esc(day)}</h4>
      ${events.map(ev => `
        <div class="todo-row" ${ev.is_recurring ? "" : `data-calendar-edit="${ev.id}" style="cursor:pointer"`}>
          <span class="todo-title">
            ${ev.is_recurring ? '<span title="Wiederkehrender Termin - Serie am Handy/Radicale bearbeiten">🔁</span> ' : ""}${esc(ev.title)}
            ${new Date(ev.start) < now ? '<span class="page-sub" style="display:inline">· vergangen</span>' : ""}
          </span>
          <span class="todo-due">${ev.all_day ? "ganztägig" : new Date(ev.start).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}${ev.location ? " · " + esc(ev.location) : ""}${ev.travel_minutes != null ? ` · 🚗 ~${ev.travel_minutes} Min` : ""}</span>
        </div>
      `).join("")}
    </div>
  `).join("");
}

document.getElementById("calendar-show-past").addEventListener("change", loadCalendarEvents);

document.getElementById("calendar-event-list").addEventListener("click", e => {
  const id = e.target.closest("[data-calendar-edit]")?.dataset.calendarEdit;
  if (id) openCalendarModal(calendarEventsCache.find(ev => ev.id === Number(id)));
});

function openCalendarModal(ev) {
  document.getElementById("calendar-collection").innerHTML = calendarCollectionsCache
    .map(c => `<option value="${esc(c.url)}">${esc(c.name)}</option>`).join("")
    || '<option value="">Kein Kalender verbunden – Termin bleibt nur lokal</option>';

  document.getElementById("calendar-modal-title").textContent = ev ? "Termin bearbeiten" : "Neuer Termin";
  document.getElementById("calendar-event-id").value = ev ? ev.id : "";
  document.getElementById("calendar-title").value = ev ? ev.title : "";
  document.getElementById("calendar-all-day").checked = ev ? ev.all_day : false;
  document.getElementById("calendar-location").value = ev?.location || "";
  document.getElementById("calendar-collection").value = ev?.calendar_url || "";

  const start = ev ? new Date(ev.start) : new Date();
  document.getElementById("calendar-start-date").value = start.toISOString().slice(0, 10);
  document.getElementById("calendar-start-time").value = ev ? start.toTimeString().slice(0, 5) : "09:00";
  if (ev?.end) {
    const end = new Date(ev.end);
    document.getElementById("calendar-end-date").value = end.toISOString().slice(0, 10);
    document.getElementById("calendar-end-time").value = end.toTimeString().slice(0, 5);
  } else {
    document.getElementById("calendar-end-date").value = "";
    document.getElementById("calendar-end-time").value = "";
  }

  document.getElementById("calendar-delete-btn").classList.toggle("hidden", !ev);
  syncCalendarFormVisibility();
  document.getElementById("calendar-modal").classList.remove("hidden");
}

function syncCalendarFormVisibility() {
  const allDay = document.getElementById("calendar-all-day").checked;
  document.getElementById("calendar-start-time-wrap").classList.toggle("hidden", allDay);
  document.getElementById("calendar-end-time-wrap").classList.toggle("hidden", allDay);
}
document.getElementById("calendar-all-day").addEventListener("change", syncCalendarFormVisibility);

function closeCalendarModal() {
  document.getElementById("calendar-modal").classList.add("hidden");
}
document.getElementById("calendar-new-btn").addEventListener("click", () => openCalendarModal(null));
document.getElementById("calendar-modal-close").addEventListener("click", closeCalendarModal);

document.getElementById("calendar-form").addEventListener("submit", async e => {
  e.preventDefault();
  const id = document.getElementById("calendar-event-id").value;
  const allDay = document.getElementById("calendar-all-day").checked;
  const startDate = document.getElementById("calendar-start-date").value;
  const startTime = document.getElementById("calendar-start-time").value || "00:00";
  const endDate = document.getElementById("calendar-end-date").value;
  const endTime = document.getElementById("calendar-end-time").value || "00:00";
  const start = allDay ? `${startDate}T00:00:00` : `${startDate}T${startTime}:00`;
  const end = endDate ? (allDay ? `${endDate}T00:00:00` : `${endDate}T${endTime}:00`) : null;

  const payload = {
    title: document.getElementById("calendar-title").value,
    start, end,
    location: document.getElementById("calendar-location").value || null,
    all_day: allDay,
  };
  if (!id) payload.calendar_url = document.getElementById("calendar-collection").value || null;

  if (id) {
    await api(`/calendar-events/${id}`, { method: "PUT", body: JSON.stringify(payload) });
  } else {
    await api("/calendar-events", { method: "POST", body: JSON.stringify(payload) });
  }
  closeCalendarModal();
  await loadCalendarEvents();
});

document.getElementById("calendar-delete-btn").addEventListener("click", async () => {
  const id = document.getElementById("calendar-event-id").value;
  if (!id || !confirm("Termin wirklich löschen?")) return;
  await api(`/calendar-events/${id}`, { method: "DELETE" });
  closeCalendarModal();
  await loadCalendarEvents();
});

const SETTINGS_VIEWS = ["allgemein", "banken", "ki", "benachrichtigungen", "verbindungen", "daten"];

document.getElementById("settings-subtabs").addEventListener("click", e => {
  const view = e.target.closest("[data-settings-view]")?.dataset.settingsView;
  if (!view) return;
  document.querySelectorAll("#settings-subtabs .range-tab").forEach(b =>
    b.classList.toggle("active", b.dataset.settingsView === view));
  SETTINGS_VIEWS.forEach(v =>
    document.getElementById(`settings-view-${v}`).classList.toggle("hidden", v !== view));
});

// Zeichen und Klasse je Zustand. Das Ausrufezeichen steht bewusst auch bei
// "partial": halb eingerichtet ist genauso wenig nutzbar wie gar nicht.
const INTEGRATION_MARKS = {
  ok: { mark: "✓", cls: "is-ok" },
  partial: { mark: "❗", cls: "is-partial" },
  missing: { mark: "❗", cls: "is-missing" },
  off: { mark: "⏸", cls: "is-off" },
};

async function loadIntegrationStatus() {
  const box = document.getElementById("integration-status");
  let data;
  try {
    data = await api("/integrations/status");
  } catch (e) {
    box.innerHTML = `<p class="page-sub">Status konnte nicht geladen werden: ${esc(e.message)}</p>`;
    return;
  }

  box.innerHTML = data.items.map(it => {
    const m = INTEGRATION_MARKS[it.status] || INTEGRATION_MARKS.missing;
    const fehlt = it.missing.length
      ? `<div class="integration-missing">Es fehlt: ${it.missing.map(m => esc(m)).join(", ")}</div>`
      : "";
    // Ollama ist die einzige Anbindung, ohne die sichtbare Funktionen ausfallen -
    // alles andere ist Zusatz und soll nicht wie ein Versäumnis wirken.
    const pflicht = (!it.optional && it.status !== "ok")
      ? `<div class="integration-required">Für die KI-Funktionen nötig</div>` : "";
    return `<div class="integration-card ${m.cls}">
      <div class="integration-mark">${m.mark}</div>
      <div class="integration-body">
        <div class="integration-name">${esc(it.name)}</div>
        <div class="integration-purpose">${esc(it.purpose)}</div>
        <div class="integration-purpose">${esc(it.detail)}</div>
        ${fehlt}${pflicht}
      </div>
    </div>`;
  }).join("");

  updateIntegrationBadge(data.incomplete);
  applySettingsPanelCollapse(data.items);
}

// Klappt die Einstellungen-Panels bereits vollständig eingerichteter
// Anbindungen standardmäßig zu - bewusst NUR die einzelnen Formulare unten,
// nicht die große Übersicht ("Einrichtungsstatus") oben, die soll unverändert
// alles auf einen Blick zeigen. Jedes Panel bleibt per Klick auf den Titel
// auf-/zuklappbar, auch die noch offenen.
function applySettingsPanelCollapse(items) {
  const byKey = Object.fromEntries(items.map(it => [it.key, it]));
  document.querySelectorAll(".panel[data-integration-key]").forEach(panel => {
    const key = panel.dataset.integrationKey;
    const it = byKey[key];
    if (!it) return;
    const titleEl = panel.querySelector(".panel-title");
    titleEl.querySelector(".panel-collapsed-hint")?.remove();
    if (it.status === "ok") {
      const hint = document.createElement("span");
      hint.className = "panel-collapsed-hint";
      hint.textContent = "✓ eingerichtet";
      titleEl.appendChild(hint);
      // Nur beim ersten Laden automatisch zuklappen - ein Klick des Nutzers
      // (data-user-toggled) soll nicht bei jedem Neuladen überschrieben werden.
      if (!panel.dataset.userToggled) panel.classList.add("is-collapsed");
    }
  });
}

document.addEventListener("click", e => {
  const titleEl = e.target.closest(".panel[data-integration-key] > .panel-title");
  if (!titleEl) return;
  const panel = titleEl.closest(".panel");
  panel.classList.toggle("is-collapsed");
  panel.dataset.userToggled = "1";
});

function updateIntegrationBadge(count) {
  const badge = document.getElementById("integration-nav-badge");
  if (!badge) return;
  badge.textContent = count > 0 ? count : "";
  badge.classList.toggle("hidden", !count);
}

// Beim Start einmal zählen, damit die Plakette stimmt, ohne dass man die
// Einstellungen geöffnet haben muss.
async function refreshIntegrationBadge() {
  try {
    const data = await api("/integrations/status");
    updateIntegrationBadge(data.incomplete);
  } catch (e) {
    // Für den Start unkritisch
  }
}

async function loadSettingsTab() {
  await loadCountrySettings();
  await loadAuthSettingsPanel();
  await loadIntegrationStatus();
  await loadBudgets();
  await loadOllamaSettings();
  await loadSyncSchedule();
  await loadAutoCategorizeSettings();
  await loadWebSearchSettings();
  await loadImmichSettings();
  await loadWebhookSettings();
  await loadNativeSyncSettings();
  await loadScalableSettings();
  await loadMailSettings();
  await loadCreditCardSettings();
  await loadNotificationSettings();
  await loadMorningBriefingSettings();
  await loadQuietHoursSettings();
  await loadMidweekCheckinSettings();
  await loadAssistantActivity();
  await loadRoutinesSettings();
  await loadAlertRules();
  await loadCallSettings();
  await loadBackupSettings();
  await loadBackupsList();
  await loadTaxExportFilters();
  await loadFintsSettings();
  await loadBankConnections();
  await loadBitvavoConnections();
  await loadPaypalConnections();
  await loadEnableBankingSettings();
  await loadEnableBankingConnections();
  await loadEbaySettings();
  await loadEbayConnections();
  await loadRadicaleSettings();
  await loadTravelSettings();
}


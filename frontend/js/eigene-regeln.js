// ================= EIGENE REGELN =================
const ALERT_RULE_LABELS = {
  category_spend_above: "Ausgaben über Betrag",
  account_balance_below: "Kontostand unter Betrag",
  category_deviation: "Abweichung vom Schnitt",
  goal_progress_above: "Ziel-Fortschritt erreicht",
};

async function loadAlertRules() {
  if (!categoriesCache.length) await loadCategories();
  if (!accountsCache.length) accountsCache = await api("/accounts");

  const catSel = document.getElementById("alert-rule-category");
  catSel.innerHTML = categoriesCache.filter(c => c.type === "ausgabe")
    .map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
  const accSel = document.getElementById("alert-rule-account");
  accSel.innerHTML = accountsCache.map(a => `<option value="${a.id}">${esc(a.name)}</option>`).join("");
  // Nur offene, automatisch messbare Ziele - manuelle Meilensteine haben keinen
  // Fortschritt in Prozent, das Backend lehnt sie fuer diese Regel auch ab.
  const goalSel = document.getElementById("alert-rule-goal");
  const measurableGoals = (await api("/goals").catch(() => []))
    .filter(g => g.status === "open" && g.goal_type === "auto_financial");
  goalSel.innerHTML = measurableGoals.length
    ? measurableGoals.map(g => `<option value="${g.id}">${esc(g.title)}</option>`).join("")
    : `<option value="">Kein automatisch messbares Ziel vorhanden</option>`;

  const rules = await api("/alert-rules");
  const list = document.getElementById("alert-rules-list");
  if (!rules.length) {
    list.innerHTML = `<p class="page-sub">Noch keine eigenen Regeln angelegt.</p>`;
    return;
  }
  list.innerHTML = rules.map(r => {
    const target = r.category_name || r.account_name || r.goal_title || "?";
    const unit = (r.rule_type === "category_deviation" || r.rule_type === "goal_progress_above") ? "%" : "€";
    return `
      <div class="todo-row">
        <span class="todo-title">
          ${esc(ALERT_RULE_LABELS[r.rule_type] || r.rule_type)} · ${esc(target)}
          <span class="page-sub" style="display:inline">– Schwelle ${r.threshold}${unit}</span>
        </span>
        <label class="checkbox-label" style="margin:0">
          <input type="checkbox" data-alert-rule-toggle="${r.id}" ${r.active ? "checked" : ""}>
          <span>aktiv</span>
        </label>
        <button type="button" class="link-btn" data-alert-rule-delete="${r.id}">Löschen</button>
      </div>`;
  }).join("");
}

function syncAlertRuleFormFields() {
  const type = document.getElementById("alert-rule-type").value;
  const usesCategory = type === "category_spend_above" || type === "category_deviation";
  document.getElementById("alert-rule-category-wrap").classList.toggle("hidden", !usesCategory);
  document.getElementById("alert-rule-account-wrap").classList.toggle("hidden", type !== "account_balance_below");
  document.getElementById("alert-rule-goal-wrap").classList.toggle("hidden", type !== "goal_progress_above");
  document.getElementById("alert-rule-threshold-wrap").firstChild.textContent =
    (type === "category_deviation" || type === "goal_progress_above") ? "Schwellwert (%) " : "Schwellwert (€) ";
}
document.getElementById("alert-rule-type").addEventListener("change", syncAlertRuleFormFields);

document.getElementById("alert-rule-form").addEventListener("submit", async e => {
  e.preventDefault();
  const type = document.getElementById("alert-rule-type").value;
  const payload = {
    rule_type: type,
    threshold: parseFloat(document.getElementById("alert-rule-threshold").value),
    category_id: (type === "category_spend_above" || type === "category_deviation")
      ? parseInt(document.getElementById("alert-rule-category").value, 10) : null,
    account_id: type === "account_balance_below" ? parseInt(document.getElementById("alert-rule-account").value, 10) : null,
    goal_id: type === "goal_progress_above" ? parseInt(document.getElementById("alert-rule-goal").value, 10) || null : null,
  };
  if (type === "goal_progress_above" && !payload.goal_id) {
    toast("Kein automatisch messbares Ziel vorhanden – erst ein Ziel mit Auswertungsregel anlegen.");
    return;
  }
  await api("/alert-rules", { method: "POST", body: JSON.stringify(payload) });
  document.getElementById("alert-rule-threshold").value = "";
  toast("Regel angelegt.");
  loadAlertRules();
});

document.getElementById("alert-rules-list").addEventListener("change", async e => {
  const id = e.target.closest("[data-alert-rule-toggle]")?.dataset.alertRuleToggle;
  if (id) {
    await api(`/alert-rules/${id}`, { method: "PATCH", body: JSON.stringify({ active: e.target.checked }) });
  }
});

document.getElementById("alert-rules-list").addEventListener("click", async e => {
  const id = e.target.closest("[data-alert-rule-delete]")?.dataset.alertRuleDelete;
  if (id) {
    await api(`/alert-rules/${id}`, { method: "DELETE" });
    loadAlertRules();
  }
});

async function loadCallSettings() {
  const s = await api("/settings/calls");
  document.getElementById("calls-enabled").checked = s.enabled;
  document.getElementById("twilio-remove").classList.toggle("hidden", !s.twilio_configured);
  document.getElementById("twilio-token").placeholder = s.twilio_configured
    ? "gespeichert – zum Ändern neuen Token eingeben" : "wird verschlüsselt gespeichert";
}

document.getElementById("calls-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const sidInput = document.getElementById("twilio-sid");
  const tokenInput = document.getElementById("twilio-token");
  const fromInput = document.getElementById("twilio-from");
  const toInput = document.getElementById("twilio-to");
  const payload = {
    enabled: document.getElementById("calls-enabled").checked,
    twilio_account_sid: sidInput.value.trim() || null,
    twilio_auth_token: tokenInput.value.trim() || null,
    twilio_from_number: fromInput.value.trim() || null,
    twilio_to_number: toInput.value.trim() || null,
  };
  await api("/settings/calls", { method: "PUT", body: JSON.stringify(payload) });
  tokenInput.value = "";
  toast("Gespeichert.");
  loadCallSettings();
});

document.getElementById("calls-test").addEventListener("click", async () => {
  const statusEl = document.getElementById("calls-status");
  statusEl.textContent = "Löse Anruf aus …";
  try {
    const r = await api("/calls/test", { method: "POST" });
    statusEl.textContent = r.message;
  } catch (e) {
    // api() zeigt den Fehler bereits per alert() an
  }
});

document.getElementById("twilio-remove").addEventListener("click", async () => {
  await api("/settings/calls/twilio", { method: "DELETE" });
  toast("Twilio entfernt.");
  loadCallSettings();
});

document.getElementById("sync-schedule-form").addEventListener("submit", async e => {
  e.preventDefault();
  const hour = parseInt(document.getElementById("sync-hour").value);
  await api("/settings/sync-schedule", { method: "PUT", body: JSON.stringify({ hour }) });
  toast(`Gespeichert – automatischer Sync läuft künftig um ${String(hour).padStart(2, "0")}:00 Uhr.`);
});


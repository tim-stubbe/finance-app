// ================= SMART-HOME: KI-AUTOMATIONEN (Phase 4) =================
// Die KI schlägt Abläufe vor UND schreibt die Home-Assistant-Automation dazu
// (YAML). Nichts wird automatisch scharf geschaltet – der Nutzer prüft das
// YAML und legt es explizit an. Backend: backend/app/smarthome_automations.py,
// Endpunkte unter /api/smarthome/automations.
let shAutoData = [];

const SH_AUTO_STATUS_LABEL = {
  vorschlag: "Vorschlag", entwurf: "Entwurf", angelegt: "aktiv in HA", verworfen: "verworfen",
};

async function loadSmartHomeAutomations() {
  try {
    shAutoData = await api("/smarthome/automations");
  } catch {
    shAutoData = [];
  }
  renderSmartHomeAutomations();
  loadSmartHomeLiveAutomations();
}

// ---------- Live-Automationen aus Home Assistant ----------
async function loadSmartHomeLiveAutomations() {
  const host = document.getElementById("sh-auto-live");
  if (!host) return;
  let rows = [];
  try { rows = await api("/smarthome/automations/live"); } catch { host.innerHTML = ""; return; }
  if (!rows.length) { host.innerHTML = `<p class="page-sub">Keine Automationen in Home Assistant.</p>`; return; }
  host.innerHTML = `<table class="data-table"><thead><tr>
      <th>Automation</th><th>Zuletzt</th><th></th><th></th></tr></thead><tbody>${
    rows.map(a => `<tr data-ent="${esc(a.entity_id)}">
      <td>${esc(a.name)}${a.running ? ` <span class="sh-sub">läuft</span>` : ""}</td>
      <td>${a.last_triggered ? new Date(a.last_triggered).toLocaleString("de-DE") : "–"}</td>
      <td><label class="checkbox-label" style="margin:0"><input type="checkbox" data-sh-auto-toggle ${a.enabled ? "checked" : ""}> aktiv</label></td>
      <td><button type="button" class="btn-ghost btn-sm" data-sh-auto-run>Jetzt ausführen</button></td>
    </tr>`).join("")}</tbody></table>`;
}

document.getElementById("sh-auto-live").addEventListener("click", async e => {
  const row = e.target.closest("[data-ent]");
  if (!row) return;
  const ent = row.dataset.ent;
  if (e.target.matches("[data-sh-auto-toggle]")) {
    try {
      await api(`/smarthome/automations/live/${encodeURIComponent(ent)}/toggle?enabled=${e.target.checked}`, { method: "POST" });
    } catch (err) { toast(err.message || "Umschalten fehlgeschlagen."); e.target.checked = !e.target.checked; }
  } else if (e.target.matches("[data-sh-auto-run]")) {
    try { await api(`/smarthome/automations/live/${encodeURIComponent(ent)}/run`, { method: "POST" }); toast("Automation ausgeführt."); }
    catch (err) { toast(err.message || "Ausführen fehlgeschlagen."); }
  }
});

document.getElementById("sh-auto-logbook-wrap").addEventListener("toggle", async e => {
  if (!e.target.open) return;
  const host = document.getElementById("sh-auto-logbook");
  host.innerHTML = `<p class="page-sub">Lädt …</p>`;
  let rows = [];
  try { rows = await api("/smarthome/automations/logbook?hours=24"); } catch { host.innerHTML = `<p class="page-sub">Verlauf nicht verfügbar.</p>`; return; }
  host.innerHTML = rows.length
    ? `<ul class="settings-list">${rows.map(r => `<li><span>${esc(r.name)}</span><span class="page-sub">${r.when ? new Date(r.when).toLocaleString("de-DE") : ""}</span></li>`).join("")}</ul>`
    : `<p class="page-sub">In den letzten 24 h nichts ausgelöst.</p>`;
});

function shAutoStatus(msg) {
  document.getElementById("sh-auto-status").textContent = msg || "";
}

function renderSmartHomeAutomations() {
  const host = document.getElementById("sh-auto-list");
  const rows = shAutoData.filter(d => d.status !== "verworfen");
  if (!rows.length) {
    host.innerHTML = `<p class="page-sub">Noch keine Vorschläge. „Vorschläge holen" fragt die KI nach sinnvollen Abläufen für deine Geräte.</p>`;
    return;
  }
  host.innerHTML = rows.map(d => {
    const ents = (d.spec && d.spec.entities || []).map(esc).join(", ");
    const warn = (d.warnings || []).length
      ? `<ul class="sh-auto-warn">${d.warnings.map(w => `<li>${esc(w)}</li>`).join("")}</ul>` : "";
    const hasYaml = d.status === "entwurf" || d.status === "angelegt";
    const yamlBlock = hasYaml
      ? `<textarea class="sh-auto-yaml" spellcheck="false">${esc(d.yaml || "")}</textarea>${warn}`
      : "";
    let actions = "";
    if (d.status === "vorschlag") {
      actions = `<button type="button" class="btn-ghost btn-sm" data-act="draft">YAML entwerfen</button>
                 <button type="button" class="btn-ghost btn-sm" data-act="reject">Verwerfen</button>`;
    } else if (hasYaml) {
      actions = `<button type="button" class="btn-ghost btn-sm" data-act="save">Speichern</button>
                 <button type="button" class="btn-primary btn-sm" data-act="apply">${d.status === "angelegt" ? "Erneut anlegen" : "In Home Assistant anlegen"}</button>
                 <button type="button" class="btn-ghost btn-sm" data-act="redraft">Neu entwerfen</button>
                 <button type="button" class="btn-ghost btn-sm" data-act="reject">Verwerfen</button>`;
    }
    return `<div class="sh-auto-card" data-id="${d.id}">
      <div class="sh-auto-head">
        <strong>${esc(d.title)}</strong>
        <span class="sh-auto-badge status-${d.status}">${SH_AUTO_STATUS_LABEL[d.status] || esc(d.status)}</span>
      </div>
      ${d.description ? `<p class="page-sub">${esc(d.description)}</p>` : ""}
      ${ents ? `<p class="sh-sub">Geräte: ${ents}</p>` : ""}
      ${d.ha_entity_id ? `<p class="sh-sub">→ ${esc(d.ha_entity_id)}</p>` : ""}
      ${yamlBlock}
      <div class="sh-auto-actions">${actions}</div>
    </div>`;
  }).join("");
}

document.getElementById("sh-auto-list").addEventListener("click", async e => {
  const btn = e.target.closest("[data-act]");
  if (!btn) return;
  const card = btn.closest("[data-id]");
  const id = card.dataset.id;
  const act = btn.dataset.act;
  btn.disabled = true;
  try {
    if (act === "draft" || act === "redraft") {
      shAutoStatus("Die KI schreibt das YAML … (kann einen Moment dauern)");
      await api(`/smarthome/automations/${id}/draft`, { method: "POST" });
    } else if (act === "save") {
      const yaml = card.querySelector(".sh-auto-yaml").value;
      await api(`/smarthome/automations/${id}`, { method: "PUT", body: JSON.stringify({ yaml_text: yaml }) });
    } else if (act === "apply") {
      shAutoStatus("Lege Automation in Home Assistant an …");
      await api(`/smarthome/automations/${id}/apply`, { method: "POST" });
      toast("Automation in Home Assistant angelegt.");
    } else if (act === "reject") {
      await api(`/smarthome/automations/${id}/reject`, { method: "POST" });
    }
    shAutoStatus("");
  } catch (err) {
    shAutoStatus("Fehler: " + (err.message || err));
  } finally {
    btn.disabled = false;
    loadSmartHomeAutomations();
  }
});

document.getElementById("sh-auto-suggest").addEventListener("click", async e => {
  e.target.disabled = true;
  shAutoStatus("Die KI überlegt sich sinnvolle Abläufe …");
  try {
    const created = await api("/smarthome/automations/suggest", { method: "POST", body: JSON.stringify({ count: 5 }) });
    shAutoStatus(created.length ? "" : "Keine neuen Vorschläge – vielleicht ist schon alles abgedeckt.");
  } catch (err) {
    shAutoStatus("Fehler: " + (err.message || err));
  } finally {
    e.target.disabled = false;
    loadSmartHomeAutomations();
  }
});

document.getElementById("sh-auto-freeform-btn").addEventListener("click", async () => {
  const input = document.getElementById("sh-auto-freeform");
  const text = input.value.trim();
  if (!text) return;
  shAutoStatus("Die KI schreibt das YAML …");
  try {
    await api("/smarthome/automations/draft-freeform", { method: "POST", body: JSON.stringify({ text }) });
    input.value = "";
    shAutoStatus("");
  } catch (err) {
    shAutoStatus("Fehler: " + (err.message || err));
  } finally {
    loadSmartHomeAutomations();
  }
});

// ================= COCKPIT-MODUS (Jarvis-Bildschirm) =================
// Ein reduzierter Vollbild-Modus für Tablet/Wand: Haus-Status groß, Sprach-
// und Textsteuerung im Zentrum, "Heute" + "Was hängt?" kompakt daneben,
// plus 2-4 HA-Verlaufs-Charts. Aktivierung: ?cockpit=1 in der URL oder der
// "Cockpit"-Knopf. Nichts hier ruft neue Backend-Logik auf - alles geht
// über /api/jarvis/command bzw. bestehende Lese-Endpunkte.
(function () {
  "use strict";

  let pollTimer = null;
  let historyTimer = null;
  let recorder = null;
  let chunks = [];

  function el(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

  function ensureRoot() {
    let root = el("cockpit-root");
    if (root) return root;
    root = document.createElement("div");
    root.id = "cockpit-root";
    root.hidden = true;
    root.innerHTML = `
      <div class="ck-topbar">
        <span class="ck-clock" id="ck-clock">–</span>
        <div class="ck-status" id="ck-house">Haus-Status wird geladen …</div>
        <button type="button" class="ck-exit" id="ck-exit" title="Cockpit verlassen">✕</button>
      </div>
      <div class="ck-main">
        <div class="ck-say" id="ck-reply">Sag oder tippe einen Befehl.</div>
        <form class="ck-input" id="ck-form" autocomplete="off">
          <button type="button" class="ck-mic" id="ck-mic" title="Sprechen">🎤</button>
          <input type="text" id="ck-text" placeholder="„Licht im Wohnzimmer aus“, „was hängt?“, „Termine heute“ …">
          <button type="submit" class="ck-send">▸</button>
        </form>
      </div>
      <div class="ck-side">
        <section class="ck-card"><h3>Heute</h3><div id="ck-today">…</div></section>
        <section class="ck-card"><h3>Was hängt?</h3><div id="ck-hanging">…</div></section>
        <section class="ck-card" id="ck-vehicle-card" hidden><h3>Fahrzeug</h3><div id="ck-vehicle">…</div></section>
        <section class="ck-card ck-charts-card"><h3>Verläufe</h3><div id="ck-charts">…</div></section>
        <section class="ck-card ck-fp-card" id="ck-floorplan"><h3>Grundriss</h3><div id="ck-floorplan-slot"></div></section>
      </div>`;
    document.body.appendChild(root);

    el("ck-exit").addEventListener("click", () => setCockpit(false));
    el("ck-form").addEventListener("submit", e => { e.preventDefault(); sendText(el("ck-text").value); });
    el("ck-mic").addEventListener("click", toggleMic);
    return root;
  }

  // Den bestehenden Grundriss-Panel (Smart-Home-Tab) ins Cockpit umhängen und
  // beim Verlassen zurück - nichts neu bauen, dieselbe smarthome-floorplan.js.
  let fpHome = null; // { parent, next }
  function borrowFloorplan() {
    const panel = document.getElementById("sh-floorplan-panel");
    const slot = document.getElementById("ck-floorplan-slot");
    if (!panel || !slot || panel.parentElement === slot) return;
    fpHome = { parent: panel.parentElement, next: panel.nextElementSibling };
    slot.appendChild(panel);
    if (typeof loadSmartHomeFloorplan === "function") { try { loadSmartHomeFloorplan(); } catch {} }
  }
  function returnFloorplan() {
    const panel = document.getElementById("sh-floorplan-panel");
    if (!panel || !fpHome) return;
    fpHome.parent.insertBefore(panel, fpHome.next);
    fpHome = null;
  }

  function setCockpit(on) {
    ensureRoot().hidden = !on;
    document.body.classList.toggle("cockpit-active", on);
    const url = new URL(location.href);
    if (on) { url.searchParams.set("cockpit", "1"); } else { url.searchParams.delete("cockpit"); }
    history.replaceState(null, "", url);
    if (on) { borrowFloorplan(); startPolling(); refreshAll(); }
    else { stopPolling(); stopMic(); returnFloorplan(); }
  }
  window.setCockpit = setCockpit;
  window.toggleCockpit = () => setCockpit(ensureRoot().hidden);

  // ---------- Polling ----------
  function startPolling() {
    stopPolling();
    pollTimer = setInterval(() => { if (!document.hidden) refreshHouse(); }, 15000);
    historyTimer = setInterval(() => { if (!document.hidden) refreshCharts(); }, 120000);
    setInterval(tickClock, 1000); tickClock();
  }
  function stopPolling() {
    clearInterval(pollTimer); clearInterval(historyTimer);
    pollTimer = historyTimer = null;
  }
  function tickClock() {
    const c = el("ck-clock");
    if (c) c.textContent = new Date().toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  }

  function refreshAll() { refreshHouse(); refreshToday(); refreshHanging(); refreshCharts(); refreshVehicle(); }

  async function refreshVehicle() {
    const card = document.getElementById("ck-vehicle-card");
    try {
      const [v, s] = await Promise.all([api("/vehicle"), api("/vehicle/fuel-summary")]);
      const rows = [];
      if (s.last_odometer_km != null) rows.push(["Kilometerstand", s.last_odometer_km.toLocaleString("de-DE") + " km"]);
      if (s.avg_consumption_l_per_100km != null) rows.push(["Ø Verbrauch", s.avg_consumption_l_per_100km.toFixed(1) + " l/100 km"]);
      if (s.avg_cost_per_km != null) rows.push(["Ø Kosten", s.avg_cost_per_km.toFixed(3) + " €/km"]);
      if (!rows.length) { card.hidden = true; return; }
      document.getElementById("ck-vehicle").innerHTML =
        `<div class="ck-vhead">${esc(v.name || "Fahrzeug")}</div>` +
        rows.map(([k, val]) => `<div class="ck-vrow"><span>${esc(k)}</span><em>${esc(val)}</em></div>`).join("");
      card.hidden = false;
    } catch { card.hidden = true; }   // kein Fahrzeug eingerichtet -> Karte weg
  }

  async function refreshHouse() {
    try {
      const s = await api("/jarvis/house-summary");
      const box = el("ck-house");
      if (!s.ha_configured) { box.textContent = "Smart Home nicht eingerichtet"; return; }
      if (s.ha_connected === false) { box.textContent = "Home Assistant nicht erreichbar"; return; }
      const bits = [];
      bits.push(`💡 ${s.lights_on}/${s.lights_total} an`);
      if (s.climate_on && s.climate_on.length) bits.push(`🌡️ ${s.climate_on.join(", ")}`);
      if (s.contacts_open && s.contacts_open.length) bits.push(`🚪 offen: ${s.contacts_open.join(", ")}`);
      if (s.covers_open && s.covers_open.length) bits.push(`🪟 ${s.covers_open.length} Rollladen offen`);
      if (s.total_power_w) bits.push(`⚡ ${Math.round(s.total_power_w)} W`);
      box.innerHTML = bits.map(esc).join(" &nbsp;·&nbsp; ");
    } catch { el("ck-house").textContent = "Haus-Status nicht verfügbar"; }
  }

  async function refreshToday() {
    const box = el("ck-today");
    try {
      const [evs, todos] = await Promise.all([
        api("/calendar/upcoming?days=1").catch(() => []),
        api("/todos").catch(() => []),
      ]);
      const today = new Date().toISOString().slice(0, 10);
      const te = (evs || []).filter(e => (e.start || "").slice(0, 10) === today);
      const due = (todos || []).filter(t => !t.done && t.due_date && t.due_date <= today).slice(0, 6);
      let h = "";
      h += te.length
        ? "<ul>" + te.map(e => `<li>${esc((e.start || "").slice(11, 16) || "—")} ${esc(e.title)}</li>`).join("") + "</ul>"
        : '<p class="ck-muted">Keine Termine heute.</p>';
      if (due.length) h += "<ul class=\"ck-due\">" + due.map(t => `<li>⚠️ ${esc(t.title)}</li>`).join("") + "</ul>";
      box.innerHTML = h;
    } catch { box.innerHTML = '<p class="ck-muted">nicht verfügbar</p>'; }
  }

  async function refreshHanging() {
    const box = el("ck-hanging");
    try {
      const r = await api("/jarvis/command", { method: "POST", body: JSON.stringify({ text: "was hängt?" }) });
      box.innerHTML = `<p>${esc(r.reply || "–").replace(/\n/g, "<br>")}</p>`;
    } catch { box.innerHTML = '<p class="ck-muted">nicht verfügbar</p>'; }
  }

  async function refreshCharts() {
    const box = el("ck-charts");
    try {
      const d = await api("/smarthome/entity-history?hours=24");
      if (!d.ha_configured) { box.innerHTML = '<p class="ck-muted">Smart Home nicht eingerichtet.</p>'; return; }
      const series = d.series || {};
      const keys = Object.keys(series);
      if (!keys.length) { box.innerHTML = '<p class="ck-muted">Keine entity_ids hinterlegt (Smart-Home-Einstellungen).</p>'; return; }
      box.innerHTML = keys.slice(0, 4).map(k => sparkline(k, series[k])).join("");
    } catch { box.innerHTML = '<p class="ck-muted">nicht verfügbar</p>'; }
  }

  function sparkline(name, points) {
    const nums = (points || []).map(p => typeof p.v === "number" ? p.v : null).filter(v => v != null);
    if (nums.length < 2) return `<div class="ck-spark"><span>${esc(name)}</span><em class="ck-muted">zu wenig Daten</em></div>`;
    const min = Math.min(...nums), max = Math.max(...nums), span = max - min || 1;
    const w = 220, hh = 34;
    const path = nums.map((v, i) =>
      `${i === 0 ? "M" : "L"}${(i / (nums.length - 1) * w).toFixed(1)},${(hh - (v - min) / span * hh).toFixed(1)}`).join(" ");
    return `<div class="ck-spark"><span>${esc(name)}</span>
      <svg viewBox="0 0 ${w} ${hh}" preserveAspectRatio="none"><path d="${path}"/></svg>
      <em>${nums[nums.length - 1]}</em></div>`;
  }

  // ---------- Befehl senden ----------
  async function sendText(text) {
    text = (text || "").trim();
    if (!text) return;
    el("ck-text").value = "";
    setReply("…");
    try {
      const r = await api("/jarvis/command", { method: "POST", body: JSON.stringify({ text }) });
      setReply(r.reply || (r.ok ? "Erledigt." : "Das hat nicht geklappt."), !r.ok);
      if (r.actions && r.actions.length) refreshHouse();
    } catch { setReply("Konnte den Befehl nicht senden.", true); }
  }

  function setReply(txt, isError) {
    const r = el("ck-reply");
    r.textContent = txt;
    r.classList.toggle("is-error", !!isError);
  }

  // ---------- Sprache (wie smarthome.js: MediaRecorder -> /voice/command) ----------
  async function toggleMic() {
    if (recorder && recorder.state === "recording") { recorder.stop(); return; }
    if (!navigator.mediaDevices || !window.MediaRecorder) { setReply("Dieser Browser kann kein Audio aufnehmen.", true); return; }
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch { setReply("Mikrofon blockiert – Zugriff im Browser erlauben.", true); return; }
    chunks = [];
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
    recorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      el("ck-mic").classList.remove("is-recording");
      await sendVoice(new Blob(chunks, { type: chunks[0]?.type || "audio/webm" }));
    };
    recorder.start();
    el("ck-mic").classList.add("is-recording");
    setReply("Höre zu …");
  }
  function stopMic() { try { if (recorder && recorder.state === "recording") recorder.stop(); } catch {} }

  async function sendVoice(blob) {
    const fd = new FormData();
    fd.append("file", blob, "aufnahme.webm");
    const headers = {};
    const csrf = typeof getCsrfToken === "function" ? getCsrfToken() : null;
    if (csrf) headers["X-CSRF-Token"] = csrf;
    let res;
    try {
      res = await fetch(API + "/smarthome/voice/command", { method: "POST", headers, body: fd });
    } catch { setReply("Netzwerkfehler bei der Sprachaufnahme.", true); return; }
    if (res.status === 501) { setReply("Sprach-Backend nicht aktiv (STT_BACKEND=stub). Siehe Smart-Home-Einstellungen.", true); return; }
    if (!res.ok) { setReply("Fehler bei der Spracherkennung.", true); return; }
    const j = await res.json();
    const said = j.transcript ? `„${j.transcript}" → ` : "";
    setReply(said + (j.reply || (j.ok ? "Erledigt." : "Das hat nicht geklappt.")), !j.ok);
    if (j.reply_audio_b64) {
      try { new Audio(`data:${j.reply_audio_format || "audio/wav"};base64,${j.reply_audio_b64}`).play().catch(() => {}); } catch {}
    }
    if (j.actions && j.actions.length) refreshHouse();
  }

  // ---------- Auto-Start ----------
  document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("cockpit-open-btn");
    if (btn) btn.addEventListener("click", () => setCockpit(true));
    if (new URLSearchParams(location.search).get("cockpit") === "1") {
      // erst starten, wenn die App entsperrt ist (auth-gate); grob per Timeout.
      const boot = () => { if (!document.getElementById("app") || document.getElementById("app").classList.contains("hidden")) return setTimeout(boot, 400); setCockpit(true); };
      boot();
    }
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !ensureRoot().hidden) refreshAll(); });
})();

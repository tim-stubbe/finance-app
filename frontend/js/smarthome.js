// ================= SMART-HOME-TAB (Home Assistant <-> lokale Ollama) =================
// Phase 1: Text-Steuerung + Zustandsabfrage + Cockpit-UI. Die eigentliche
// Pipeline (Schnellpfad/Alias, sonst Ollama-Intent) steckt im Backend
// (app/smarthome.py). Voice = Phase 2, 3D-Grundriss = Phase 3.
let smartHomeDevices = [];

async function loadSmartHomeTab() {
  loadSmartHomeHealth();
  loadSmartHomeDevices();
  loadSmartHomeAliases();
  loadSmartHomeHistory();
  if (typeof loadSmartHomeFloorplan === "function") loadSmartHomeFloorplan();
  if (typeof loadSmartHomeAutomations === "function") loadSmartHomeAutomations();
  loadSmartHomeEnergy();
}

async function loadSmartHomeEnergy() {
  const panel = document.getElementById("smarthome-energy-panel");
  let e;
  try { e = await api("/smarthome/energy"); } catch { panel.hidden = true; return; }
  if (!e.power_sensors.length && !e.energy_sensors.length) { panel.hidden = true; return; }
  panel.hidden = false;
  document.getElementById("smarthome-energy-summary").textContent =
    `Aktuell ${e.total_power_w.toLocaleString("de-DE")} W · geschätzt ${eur(e.est_daily_cost)}/Tag · ${eur(e.est_monthly_cost)}/Monat (${e.price_per_kwh.toFixed(2)} €/kWh)`;
  const rows = [
    ...e.power_sensors.map(p => `<tr><td>${esc(p.name)}</td><td>${p.watt.toLocaleString("de-DE")} W</td></tr>`),
    ...e.energy_sensors.map(x => `<tr><td>${esc(x.name)}</td><td>${x.kwh != null ? x.kwh.toLocaleString("de-DE") + " kWh" : "–"}</td></tr>`),
  ];
  document.getElementById("smarthome-energy-list").innerHTML = rows.join("") || emptyRow(2, "list", "–");
}

async function loadSmartHomeHealth() {
  const line = document.getElementById("smarthome-status-line");
  const hint = document.getElementById("smarthome-setup-hint");
  try {
    const h = await api("/smarthome/health");
    smartHomeSetupSSE(h.ha_connected);
    const ha = h.ha_connected
      ? '<span class="sh-ok">Home Assistant verbunden</span>'
      : (h.ha_configured
          ? '<span class="sh-warn">Home Assistant nicht erreichbar</span>'
          : '<span class="sh-warn">Home Assistant nicht eingerichtet</span>');
    const ol = h.ollama_connected
      ? `<span class="sh-ok">Ollama verbunden</span> (${esc(h.ollama_model || "?")})`
      : '<span class="sh-warn">Ollama nicht erreichbar</span>';
    const dry = h.dry_run ? ' · <strong>Trockenlauf aktiv</strong>' : "";
    const live = h.live ? ' · <span class="sh-ok">● live</span>' : "";
    line.innerHTML = `${ha} &nbsp;·&nbsp; ${ol}${live}${dry}`;
    hint.classList.toggle("hidden", !!h.ha_configured);
  } catch {
    line.textContent = "Status konnte nicht geprüft werden.";
  }
}

async function loadSmartHomeDevices() {
  const tbody = document.getElementById("smarthome-device-list");
  if (!tbody.children.length) tbody.innerHTML = emptyRow(4, "list", "Lädt …");
  try {
    smartHomeDevices = await api("/smarthome/devices");
  } catch {
    tbody.innerHTML = emptyRow(4, "list", "Geräte konnten nicht geladen werden (Home Assistant nicht erreichbar?).");
    return;
  }
  if (!smartHomeDevices.length) {
    tbody.innerHTML = emptyRow(4, "list", "Keine (freigegebenen) Geräte gefunden.");
    return;
  }
  tbody.innerHTML = smartHomeDevices.map(d => `
    <tr>
      <td>${esc(d.name)}<span class="sh-sub">${esc(d.entity_id)}</span></td>
      <td>${d.area ? esc(d.area) : "–"}</td>
      <td>${esc(d.state)}</td>
      <td>${d.toggleable
        ? `<button type="button" class="link-btn" data-sh-toggle="${esc(d.entity_id)}">umschalten</button>`
        : ""}</td>
    </tr>`).join("");
}

document.getElementById("smarthome-device-list").addEventListener("click", async e => {
  const entityId = e.target.closest("[data-sh-toggle]")?.dataset.shToggle;
  if (!entityId) return;
  const dev = smartHomeDevices.find(d => d.entity_id === entityId);
  const verb = dev && dev.state === "on" ? "aus" : "an";
  await sendSmartHomeCommand(`${dev ? dev.name : entityId} ${verb}`, false);
});

document.getElementById("smarthome-devices-refresh").addEventListener("click", () => {
  loadSmartHomeHealth();
  loadSmartHomeDevices();
});

// ---------- Befehl ----------
document.getElementById("smarthome-command-form").addEventListener("submit", async e => {
  e.preventDefault();
  const input = document.getElementById("smarthome-command-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  await sendSmartHomeCommand(text, false);
});

async function sendSmartHomeCommand(text, confirm) {
  const replyEl = document.getElementById("smarthome-reply");
  const confirmEl = document.getElementById("smarthome-confirm");
  replyEl.classList.remove("hidden", "is-error");
  replyEl.textContent = "…";
  confirmEl.classList.add("hidden");

  let res;
  try {
    res = await api("/smarthome/command", { method: "POST", body: JSON.stringify({ text, confirm }) });
  } catch (err) {
    replyEl.textContent = "Fehler: " + (err.message || err);
    replyEl.classList.add("is-error");
    return;
  }

  if (res.needs_confirmation && res.intent === "control") {
    document.getElementById("smarthome-confirm-text").textContent = res.reply || "Ausführen?";
    confirmEl.classList.remove("hidden");
    replyEl.classList.add("hidden");
  } else {
    replyEl.textContent = res.reply || (res.ok ? "Erledigt." : "Das hat nicht geklappt.");
    replyEl.classList.toggle("is-error", !res.ok);
  }

  if (res.actions && res.actions.length) {
    loadSmartHomeDevices();
  }
  loadSmartHomeHistory();
}

// ---------- Sprache (MediaRecorder -> /voice/command) ----------
let smartHomeRecorder = null;
let smartHomeChunks = [];

document.getElementById("smarthome-mic-btn").addEventListener("click", async () => {
  const btn = document.getElementById("smarthome-mic-btn");
  if (smartHomeRecorder && smartHomeRecorder.state === "recording") {
    smartHomeRecorder.stop();
    return;
  }
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    toast("Dieser Browser kann kein Audio aufnehmen.");
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    toast("Kein Mikrofonzugriff.");
    return;
  }
  smartHomeChunks = [];
  smartHomeRecorder = new MediaRecorder(stream);
  smartHomeRecorder.ondataavailable = e => { if (e.data.size) smartHomeChunks.push(e.data); };
  smartHomeRecorder.onstop = async () => {
    stream.getTracks().forEach(t => t.stop());
    btn.textContent = "🎤";
    btn.classList.remove("btn-primary");
    const blob = new Blob(smartHomeChunks, { type: smartHomeChunks[0]?.type || "audio/webm" });
    await sendSmartHomeVoice(blob);
  };
  smartHomeRecorder.start();
  btn.textContent = "⏹";
  btn.classList.add("btn-primary");
});

async function sendSmartHomeVoice(blob) {
  const replyEl = document.getElementById("smarthome-reply");
  replyEl.classList.remove("hidden", "is-error");
  replyEl.textContent = "Höre zu …";
  const fd = new FormData();
  fd.append("file", blob, "aufnahme.webm");

  // Bewusst direkt per fetch (nicht api()): der 501-Fall "Sprach-Backend nicht
  // aktiv" ist erwartbar und soll keinen alert() auslösen, sondern nur den
  // Hinweis unter dem Feld einblenden.
  let httpRes;
  try {
    const headers = {};
    const csrf = typeof getCsrfToken === "function" ? getCsrfToken() : null;
    if (csrf) headers["X-CSRF-Token"] = csrf;
    httpRes = await fetch(API + "/smarthome/voice/command", { method: "POST", headers, body: fd });
  } catch {
    replyEl.textContent = "Netzwerkfehler bei der Sprachaufnahme.";
    replyEl.classList.add("is-error");
    return;
  }
  if (httpRes.status === 501) {
    document.getElementById("smarthome-mic-hint").style.display = "block";
    replyEl.classList.add("hidden");
    return;
  }
  if (!httpRes.ok) {
    replyEl.textContent = "Fehler bei der Spracherkennung.";
    replyEl.classList.add("is-error");
    return;
  }
  const res = await httpRes.json();

  const said = res.transcript ? `„${res.transcript}" → ` : "";
  replyEl.textContent = said + (res.reply || (res.ok ? "Erledigt." : "Das hat nicht geklappt."));
  replyEl.classList.toggle("is-error", !res.ok);
  if (res.reply_audio_b64) {
    try {
      const audio = new Audio(`data:${res.reply_audio_format || "audio/wav"};base64,${res.reply_audio_b64}`);
      audio.play().catch(() => {});
    } catch { /* Wiedergabe optional */ }
  }
  if (res.actions && res.actions.length) loadSmartHomeDevices();
  loadSmartHomeHistory();
}

// ---------- Freihändig zuhören (serverseitiges Weckwort) ----------
// Der Browser streamt fortlaufend 16-kHz-Mono-PCM per WebSocket an
// /api/smarthome/voice/stream. Der Server erkennt das Weckwort ("hey jarvis",
// openWakeWord), nimmt danach den Befehl auf und schickt das Ergebnis zurück.
let shListen = null; // { ws, stream, ctx, node, source }

async function shToggleListen() {
  const btn = document.getElementById("smarthome-listen-btn");
  const hint = document.getElementById("smarthome-listen-hint");
  if (shListen) {
    shStopListen();
    btn.classList.remove("btn-primary");
    hint.style.display = "none";
    return;
  }
  if (!navigator.mediaDevices || !window.AudioContext || !window.WebSocket) {
    toast("Dieser Browser kann nicht freihändig zuhören.");
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  } catch {
    toast("Kein Mikrofonzugriff.");
    return;
  }

  const wsUrl = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/api/smarthome/voice/stream";
  const ws = new WebSocket(wsUrl);
  ws.binaryType = "arraybuffer";
  const ctx = new AudioContext();
  const source = ctx.createMediaStreamSource(stream);
  const node = ctx.createScriptProcessor(4096, 1, 1);
  shListen = { ws, stream, ctx, node, source };

  btn.classList.add("btn-primary");
  hint.style.display = "block";
  hint.textContent = "Verbinde …";

  node.onaudioprocess = e => {
    if (!shListen || ws.readyState !== 1) return;
    const inBuf = e.inputBuffer.getChannelData(0);
    const pcm = shDownsampleTo16k(inBuf, ctx.sampleRate);
    if (pcm.byteLength) ws.send(pcm.buffer);
  };
  source.connect(node);
  node.connect(ctx.destination); // laeuft nur, wenn verbunden; Ausgabe bleibt still

  ws.onopen = () => { hint.textContent = "Warte auf Weckwort (hey jarvis) …"; };
  ws.onmessage = ev => {
    let m;
    try { m = JSON.parse(ev.data); } catch { return; }
    if (m.type === "ready") {
      hint.textContent = `Warte auf Weckwort (${m.wake_word || "hey jarvis"}) …`;
    } else if (m.type === "wake") {
      hint.textContent = "🎙️ Weckwort erkannt – sprich deinen Befehl …";
    } else if (m.type === "error") {
      hint.textContent = "Fehler: " + (m.message || "unbekannt");
      shStopListen();
      btn.classList.remove("btn-primary");
    } else if (m.type === "result") {
      hint.textContent = `Warte auf Weckwort (hey jarvis) …`;
      if (m.ignored) return;
      const replyEl = document.getElementById("smarthome-reply");
      replyEl.classList.remove("hidden", "is-error");
      replyEl.textContent = (m.transcript ? `„${m.transcript}" → ` : "") + (m.reply || "");
      replyEl.classList.toggle("is-error", !m.ok);
      if (m.reply_audio_b64) {
        try { new Audio(`data:${m.reply_audio_format || "audio/wav"};base64,${m.reply_audio_b64}`).play().catch(() => {}); } catch { /* egal */ }
      }
      if (m.actions && m.actions.length) loadSmartHomeDevices();
      loadSmartHomeHistory();
    }
  };
  ws.onclose = () => { if (shListen) { shStopListen(); btn.classList.remove("btn-primary"); hint.style.display = "none"; } };
  ws.onerror = () => { hint.textContent = "Verbindung zum Sprach-Stream fehlgeschlagen."; };
}

function shStopListen() {
  if (!shListen) return;
  try { shListen.node.disconnect(); shListen.source.disconnect(); } catch { /* egal */ }
  try { shListen.node.onaudioprocess = null; } catch { /* egal */ }
  try { shListen.stream.getTracks().forEach(t => t.stop()); } catch { /* egal */ }
  try { shListen.ctx.close(); } catch { /* egal */ }
  try { shListen.ws.close(); } catch { /* egal */ }
  shListen = null;
}

// Float32 @ inRate -> Int16 @ 16 kHz (lineare Interpolation).
function shDownsampleTo16k(input, inRate) {
  if (inRate === 16000) {
    const out = new Int16Array(input.length);
    for (let i = 0; i < input.length; i++) out[i] = Math.max(-1, Math.min(1, input[i])) * 0x7fff;
    return out;
  }
  const ratio = inRate / 16000;
  const outLen = Math.floor(input.length / ratio);
  const out = new Int16Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const pos = i * ratio;
    const i0 = Math.floor(pos);
    const frac = pos - i0;
    const s = (input[i0] || 0) * (1 - frac) + (input[i0 + 1] || 0) * frac;
    out[i] = Math.max(-1, Math.min(1, s)) * 0x7fff;
  }
  return out;
}

document.getElementById("smarthome-listen-btn").addEventListener("click", shToggleListen);

document.getElementById("smarthome-confirm-yes").addEventListener("click", () => {
  document.getElementById("smarthome-confirm").classList.add("hidden");
  sendSmartHomeCommand("ja", true);
});
document.getElementById("smarthome-confirm-no").addEventListener("click", () => {
  document.getElementById("smarthome-confirm").classList.add("hidden");
  sendSmartHomeCommand("nein", false);
});

// ---------- Aliase ----------
async function loadSmartHomeAliases() {
  const tbody = document.getElementById("smarthome-alias-list");
  let aliases = [];
  try {
    aliases = await api("/smarthome/aliases");
  } catch { /* Tabelle bleibt leer */ }
  tbody.innerHTML = aliases.length
    ? aliases.map(a => `
      <tr>
        <td>${esc(a.phrase)}</td>
        <td>${esc(a.entity_id)}</td>
        <td><button type="button" class="link-btn" data-sh-alias-del="${a.id}">Löschen</button></td>
      </tr>`).join("")
    : emptyRow(3, "list", "Noch keine Aliase.");
}

document.getElementById("smarthome-alias-form").addEventListener("submit", async e => {
  e.preventDefault();
  const phrase = document.getElementById("smarthome-alias-phrase").value.trim();
  const entityId = document.getElementById("smarthome-alias-entity").value.trim();
  if (!phrase || !entityId) return;
  try {
    await api("/smarthome/aliases", { method: "POST", body: JSON.stringify({ phrase, entity_id: entityId }) });
    e.target.reset();
    loadSmartHomeAliases();
  } catch (err) {
    toast(err.message || "Alias konnte nicht angelegt werden.");
  }
});

document.getElementById("smarthome-alias-list").addEventListener("click", async e => {
  const id = e.target.closest("[data-sh-alias-del]")?.dataset.shAliasDel;
  if (!id) return;
  await api(`/smarthome/aliases/${id}`, { method: "DELETE" });
  loadSmartHomeAliases();
});

// ---------- Verlauf ----------
async function loadSmartHomeHistory() {
  const tbody = document.getElementById("smarthome-history-list");
  let rows = [];
  try {
    rows = await api("/smarthome/history?limit=25");
  } catch { /* Tabelle bleibt leer */ }
  tbody.innerHTML = rows.length
    ? rows.map(r => `
      <tr>
        <td>${r.created_at ? new Date(r.created_at).toLocaleString("de-DE") : "–"}</td>
        <td>${esc(r.text || "")}<span class="sh-sub">${esc(r.intent || "")}</span></td>
        <td>${r.domain ? esc(`${r.domain}.${r.service || ""}`) : "–"}${r.entity_id ? `<span class="sh-sub">${esc(r.entity_id)}</span>` : ""}</td>
        <td>${r.ok ? "✓" : `<span class="sh-warn">✗</span> ${esc(r.error || "")}`}</td>
      </tr>`).join("")
    : emptyRow(4, "list", "Noch keine Aktionen protokolliert.");
}

document.getElementById("smarthome-goto-settings")?.addEventListener("click", e => {
  e.preventDefault();
  goToTab("settings");
});

// --- Live-Updates: Server-Sent-Events aus dem HA-WebSocket-Cache ---------
let smartHomeSSE = null;
let smartHomeSSERefreshTimer = null;

function smartHomeSetupSSE(haConnected) {
  if (!haConnected) {
    if (smartHomeSSE) { smartHomeSSE.close(); smartHomeSSE = null; }
    return;
  }
  if (smartHomeSSE) return;
  try {
    smartHomeSSE = new EventSource(API + "/smarthome/events");
  } catch { return; }
  smartHomeSSE.onmessage = () => {
    // Ereignisse buendeln - nach 1,2 s Ruhe einmal die sichtbaren Listen neu laden
    clearTimeout(smartHomeSSERefreshTimer);
    smartHomeSSERefreshTimer = setTimeout(() => {
      const tab = document.getElementById("tab-smarthome");
      if (!tab || !tab.classList.contains("active")) return;
      loadSmartHomeDevices();
      loadSmartHomeEnergy();
      const editing = typeof fpEdit !== "undefined" && (fpEdit || fpDrag);
      if (!editing && typeof loadSmartHomeFloorplan === "function") loadSmartHomeFloorplan();
    }, 1200);
  };
  smartHomeSSE.onerror = () => { /* EventSource verbindet selbst neu */ };
}

// Fallback-Polling (falls SSE nicht laeuft) - langsamer, da der Normalfall
// jetzt SSE ist. Grundriss waehrend einer Bearbeitung nicht anfassen.
setInterval(() => {
  const tab = document.getElementById("tab-smarthome");
  if (!tab || !tab.classList.contains("active")) {
    if (typeof shListen !== "undefined" && shListen) {
      shStopListen();
      document.getElementById("smarthome-listen-btn").classList.remove("btn-primary");
      document.getElementById("smarthome-listen-hint").style.display = "none";
    }
    return;
  }
  loadSmartHomeHealth();
  const liveSSE = smartHomeSSE && smartHomeSSE.readyState === 1;
  if (liveSSE) return;
  loadSmartHomeDevices();
  const editing = typeof fpEdit !== "undefined" && (fpEdit || fpDrag);
  if (!editing && typeof loadSmartHomeFloorplan === "function") loadSmartHomeFloorplan();
}, 15000);

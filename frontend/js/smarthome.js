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

// ---------- Freihändig zuhören (Weckwort-gesteuert) ----------
// Der Browser hört über einen einfachen Lautstärke-Schwellwert (Web Audio)
// mit. Ein Sprachsegment wird aufgenommen und an /voice/command?wake=1
// geschickt; der Server reagiert nur, wenn das Segment mit dem Weckwort
// beginnt. Zwischen den Segmenten wird nichts gesendet.
let shListen = null; // { stream, ctx, analyser, raf, recorder, chunks, speaking, silenceStart }

async function shToggleListen() {
  const btn = document.getElementById("smarthome-listen-btn");
  const hint = document.getElementById("smarthome-listen-hint");
  if (shListen) {
    shStopListen();
    btn.classList.remove("btn-primary");
    hint.style.display = "none";
    return;
  }
  if (!navigator.mediaDevices || !window.MediaRecorder || !window.AudioContext) {
    toast("Dieser Browser kann nicht freihändig zuhören.");
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch {
    toast("Kein Mikrofonzugriff.");
    return;
  }
  const ctx = new AudioContext();
  const src = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  src.connect(analyser);
  const buf = new Uint8Array(analyser.fftSize);
  shListen = { stream, ctx, analyser, buf, recorder: null, chunks: [], speaking: false, silenceStart: 0, startedAt: 0 };

  btn.classList.add("btn-primary");
  hint.style.display = "block";
  hint.textContent = "Hört zu … sag dein Weckwort gefolgt vom Befehl.";

  const THRESH = 0.025, SILENCE_MS = 800, MAX_MS = 8000, MIN_MS = 400;
  const tick = () => {
    if (!shListen) return;
    analyser.getByteTimeDomainData(shListen.buf);
    let sum = 0;
    for (let i = 0; i < shListen.buf.length; i++) {
      const v = (shListen.buf[i] - 128) / 128;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / shListen.buf.length);
    const now = performance.now();

    if (!shListen.speaking && rms > THRESH) {
      shListen.speaking = true;
      shListen.startedAt = now;
      shListen.chunks = [];
      try {
        shListen.recorder = new MediaRecorder(shListen.stream);
        shListen.recorder.ondataavailable = e => { if (e.data.size) shListen.chunks.push(e.data); };
        shListen.recorder.onstop = () => shListenFlush();
        shListen.recorder.start();
      } catch { shListen.speaking = false; }
    } else if (shListen.speaking) {
      if (rms < THRESH) {
        if (!shListen.silenceStart) shListen.silenceStart = now;
        if (now - shListen.silenceStart > SILENCE_MS || now - shListen.startedAt > MAX_MS) {
          const long = now - shListen.startedAt > MIN_MS;
          shListen.speaking = false;
          shListen.silenceStart = 0;
          if (shListen.recorder && shListen.recorder.state === "recording") shListen.recorder.stop();
          if (!long) shListen.chunks = [];
        }
      } else {
        shListen.silenceStart = 0;
      }
    }
    shListen.raf = requestAnimationFrame(tick);
  };
  shListen.raf = requestAnimationFrame(tick);
}

function shStopListen() {
  if (!shListen) return;
  cancelAnimationFrame(shListen.raf);
  try { if (shListen.recorder && shListen.recorder.state === "recording") shListen.recorder.stop(); } catch {}
  shListen.stream.getTracks().forEach(t => t.stop());
  try { shListen.ctx.close(); } catch {}
  shListen = null;
}

async function shListenFlush() {
  if (!shListen || !shListen.chunks.length) return;
  const blob = new Blob(shListen.chunks, { type: shListen.chunks[0].type || "audio/webm" });
  shListen.chunks = [];
  const hint = document.getElementById("smarthome-listen-hint");
  const fd = new FormData();
  fd.append("file", blob, "segment.webm");
  const headers = {};
  const csrf = typeof getCsrfToken === "function" ? getCsrfToken() : null;
  if (csrf) headers["X-CSRF-Token"] = csrf;
  try {
    const resp = await fetch(API + "/smarthome/voice/command?wake=1&speak=1", { method: "POST", headers, body: fd });
    if (resp.status === 501) { hint.textContent = "Sprach-Backend nicht aktiv (STT_BACKEND)."; shStopListen(); document.getElementById("smarthome-listen-btn").classList.remove("btn-primary"); return; }
    if (!resp.ok) return;
    const res = await resp.json();
    if (res.ignored) { hint.textContent = "Hört zu … (kein Weckwort erkannt)"; return; }
    const replyEl = document.getElementById("smarthome-reply");
    replyEl.classList.remove("hidden", "is-error");
    replyEl.textContent = (res.transcript ? `„${res.transcript}" → ` : "") + (res.reply || "");
    replyEl.classList.toggle("is-error", !res.ok);
    hint.textContent = "Hört zu …";
    if (res.reply_audio_b64) {
      try { new Audio(`data:${res.reply_audio_format || "audio/wav"};base64,${res.reply_audio_b64}`).play().catch(() => {}); } catch {}
    }
    if (res.actions && res.actions.length) loadSmartHomeDevices();
    loadSmartHomeHistory();
  } catch { /* Segment verworfen */ }
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

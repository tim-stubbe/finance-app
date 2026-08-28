// ================= SMART-HOME-GRUNDRISS (Phase 3) =================
// 2D-Editor (SVG, Meter = SVG-Einheit) zum Anordnen von Räumen/Geräten +
// 3D-Ansicht (three.js r128, schon fürs Auto-Tab geladen). Geräte zeigen
// ihren Live-Zustand und sind per Klick schaltbar (nutzt die bestehende
// Pipeline über sendSmartHomeCommand aus js/smarthome.js).
// Layout wird als ein JSON-Blob unter /api/smarthome/floorplan gespeichert.

let fpData = { rooms: [], devices: [], states: {} };
let fpEdit = false;
let fpView = "2d";
let fpDirty = false;
let fpThree = null;
let fpDrag = null;

const FP_SVG = () => document.getElementById("sh-fp-svg");

async function loadSmartHomeFloorplan() {
  try {
    fpData = await api("/smarthome/floorplan");
  } catch {
    fpData = { rooms: [], devices: [], states: {} };
  }
  fpData.rooms = fpData.rooms || [];
  fpData.devices = fpData.devices || [];
  fpData.states = fpData.states || {};
  fpRefreshDevicePicker();
  fpRender();
}

// ---------- Geometrie-Helfer ----------
function fpBounds() {
  if (!fpData.rooms.length && !fpData.devices.length) {
    return { minX: 0, minY: 0, maxX: 10, maxY: 8 };
  }
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  fpData.rooms.forEach(r => {
    minX = Math.min(minX, r.x); minY = Math.min(minY, r.y);
    maxX = Math.max(maxX, r.x + r.w); maxY = Math.max(maxY, r.y + r.h);
  });
  fpData.devices.forEach(d => {
    minX = Math.min(minX, d.x); minY = Math.min(minY, d.y);
    maxX = Math.max(maxX, d.x); maxY = Math.max(maxY, d.y);
  });
  if (!isFinite(minX)) return { minX: 0, minY: 0, maxX: 10, maxY: 8 };
  return { minX, minY, maxX, maxY };
}

function fpCenter() {
  const b = fpBounds();
  const snap = v => Math.round(v * 10) / 10;
  return { x: snap((b.minX + b.maxX) / 2), y: snap((b.minY + b.maxY) / 2) };
}

function fpDeviceState(entityId) {
  const s = fpData.states[entityId];
  if (!s) return "unknown";
  if (["on", "open", "playing", "home", "heat", "cool"].includes(s.state)) return "on";
  if (["off", "closed", "idle", "standby", "away", "unavailable"].includes(s.state)) return "off";
  return "unknown";
}

// ---------- 2D-Render ----------
function fpRender() {
  const hint = document.getElementById("sh-fp-hint");
  if (hint) {
    hint.textContent = fpEdit
      ? "Räume/Geräte ziehen · Ecke unten rechts = Größe · Doppelklick Raum = umbenennen · Doppelklick Gerät = entfernen"
      : "Klick auf ein Gerät schaltet es. Bearbeiten zum Anordnen.";
  }
  if (fpView === "3d") { fpRender3d(); return; }

  const svg = FP_SVG();
  const b = fpBounds();
  const pad = 1;
  svg.setAttribute("viewBox",
    `${b.minX - pad} ${b.minY - pad} ${(b.maxX - b.minX) + pad * 2} ${(b.maxY - b.minY) + pad * 2}`);
  svg.classList.toggle("sh-fp-editing", fpEdit);

  let html = "";
  fpData.rooms.forEach(r => {
    html += `<rect class="sh-fp-room" data-room="${esc(r.id)}" x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" rx="0.05"></rect>`;
    html += `<text class="sh-fp-room-label" x="${r.x + r.w / 2}" y="${r.y + r.h / 2}">${esc(r.name || "")}</text>`;
    if (fpEdit) {
      html += `<rect class="sh-fp-resize" data-resize="${esc(r.id)}" x="${r.x + r.w - 0.24}" y="${r.y + r.h - 0.24}" width="0.24" height="0.24"></rect>`;
    }
  });
  fpData.devices.forEach(d => {
    const st = fpDeviceState(d.entity_id);
    const info = fpData.states[d.entity_id] || {};
    const label = info.name || d.entity_id;
    html += `<circle class="sh-fp-dev is-${st}" data-dev="${esc(d.entity_id)}" cx="${d.x}" cy="${d.y}" r="0.28">`
          + `<title>${esc(label)} — ${esc(info.state || "?")}</title></circle>`;
  });
  svg.innerHTML = html;
}

function fpSvgPoint(evt) {
  const svg = FP_SVG();
  const ctm = svg.getScreenCTM();
  if (!ctm) return { x: 0, y: 0 };
  const pt = svg.createSVGPoint();
  pt.x = evt.clientX; pt.y = evt.clientY;
  const p = pt.matrixTransform(ctm.inverse());
  return { x: p.x, y: p.y };
}

// ---------- 3D-Render (nur Ansicht) ----------
function fpInit3d() {
  if (fpThree) return fpThree;
  const canvas = document.getElementById("sh-fp-3d-canvas");
  const wrap = document.getElementById("sh-fp-3d-wrap");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 500);
  camera.position.set(9, 11, 13);
  scene.add(new THREE.AmbientLight(0xffffff, 0.8));
  const dir = new THREE.DirectionalLight(0xffffff, 0.65);
  dir.position.set(10, 20, 8);
  scene.add(dir);
  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  const group = new THREE.Group();
  scene.add(group);

  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();
  renderer.domElement.addEventListener("pointerdown", ev => {
    const rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(mouse, camera);
    const hit = raycaster.intersectObjects(group.children, true)
      .find(h => h.object.userData && h.object.userData.entityId);
    if (hit) fpToggleDevice(hit.object.userData.entityId);
  });

  function resize() {
    const w = wrap.clientWidth, h = wrap.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(wrap);

  (function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  })();

  fpThree = { renderer, scene, camera, controls, group, resize };
  return fpThree;
}

function fpRender3d() {
  const t = fpInit3d();
  t.resize();
  while (t.group.children.length) t.group.remove(t.group.children[0]);

  const b = fpBounds();
  const cx = (b.minX + b.maxX) / 2, cz = (b.minY + b.maxY) / 2;
  const wallH = 1.4;

  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry((b.maxX - b.minX) + 4, (b.maxY - b.minY) + 4),
    new THREE.MeshStandardMaterial({ color: 0x2b2b31, roughness: 1 }));
  ground.rotation.x = -Math.PI / 2;
  t.group.add(ground);

  fpData.rooms.forEach(r => {
    const geo = new THREE.BoxGeometry(r.w, wallH, r.h);
    const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
      color: 0x7a8cc8, transparent: true, opacity: 0.16 }));
    mesh.position.set(r.x + r.w / 2 - cx, wallH / 2, r.y + r.h / 2 - cz);
    t.group.add(mesh);
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo),
      new THREE.LineBasicMaterial({ color: 0x9fb0e0 }));
    edges.position.copy(mesh.position);
    t.group.add(edges);
  });

  fpData.devices.forEach(d => {
    const st = fpDeviceState(d.entity_id);
    const col = st === "on" ? 0xe1ad66 : (st === "off" ? 0x888888 : 0xb5651d);
    const m = new THREE.Mesh(new THREE.SphereGeometry(0.22, 16, 16),
      new THREE.MeshStandardMaterial({
        color: col, emissive: st === "on" ? col : 0x000000, emissiveIntensity: 0.6 }));
    m.position.set(d.x - cx, wallH + 0.35, d.y - cz);
    m.userData.entityId = d.entity_id;
    t.group.add(m);
  });

  t.controls.target.set(0, 0, 0);
}

// ---------- Aktionen ----------
function fpToggleDevice(entityId) {
  const info = fpData.states[entityId] || {};
  const name = info.name || entityId;
  const cur = fpDeviceState(entityId);
  if (typeof sendSmartHomeCommand === "function") {
    sendSmartHomeCommand(`${name} ${cur === "on" ? "aus" : "an"}`, false);
  }
  setTimeout(loadSmartHomeFloorplan, 900);
}

function fpRefreshDevicePicker() {
  const sel = document.getElementById("sh-fp-add-device");
  if (!sel) return;
  const placed = new Set(fpData.devices.map(d => d.entity_id));
  const opts = ['<option value="">+ Gerät …</option>'];
  Object.keys(fpData.states).sort().forEach(eid => {
    if (placed.has(eid)) return;
    opts.push(`<option value="${esc(eid)}">${esc(fpData.states[eid].name || eid)}</option>`);
  });
  sel.innerHTML = opts.join("");
}

function fpSetView(v) {
  fpView = v;
  document.getElementById("sh-fp-view-2d").classList.toggle("active", v === "2d");
  document.getElementById("sh-fp-view-3d").classList.toggle("active", v === "3d");
  document.getElementById("sh-fp-2d-wrap").classList.toggle("hidden", v !== "2d");
  document.getElementById("sh-fp-3d-wrap").classList.toggle("hidden", v !== "3d");
  fpRender();
}

function fpToggleEdit() {
  fpEdit = !fpEdit;
  document.getElementById("sh-fp-edit").classList.toggle("active", fpEdit);
  ["sh-fp-add-room", "sh-fp-add-device", "sh-fp-save"].forEach(id =>
    document.getElementById(id).classList.toggle("hidden", !fpEdit));
  if (fpEdit && fpView === "3d") fpSetView("2d");
  fpRender();
}

function fpAddRoom() {
  const c = fpCenter();
  fpData.rooms.push({ id: "r" + Date.now().toString(36), name: "Raum", x: c.x - 1.5, y: c.y - 1.25, w: 3, h: 2.5 });
  fpDirty = true;
  fpRender();
}

function fpAddDevice(e) {
  const eid = e.target.value;
  if (!eid) return;
  const c = fpCenter();
  fpData.devices.push({ entity_id: eid, x: c.x, y: c.y });
  e.target.value = "";
  fpDirty = true;
  fpRefreshDevicePicker();
  fpRender();
}

function fpSave() {
  api("/smarthome/floorplan", {
    method: "PUT",
    body: JSON.stringify({ rooms: fpData.rooms, devices: fpData.devices }),
  }).then(() => {
    fpDirty = false;
    toast("Grundriss gespeichert.");
  }).catch(err => toast(err.message || "Speichern fehlgeschlagen."));
}

// ---------- Verdrahtung (Elemente existieren, Script liegt am Body-Ende) ----------
(function fpInit() {
  const svg = FP_SVG();
  if (!svg) return;

  svg.addEventListener("pointerdown", e => {
    const devEl = e.target.closest("[data-dev]");
    if (!fpEdit) {
      if (devEl) fpToggleDevice(devEl.dataset.dev);
      return;
    }
    const resizeEl = e.target.closest("[data-resize]");
    const roomEl = e.target.closest("[data-room]");
    const p = fpSvgPoint(e);
    if (resizeEl) {
      const r = fpData.rooms.find(x => x.id === resizeEl.dataset.resize);
      fpDrag = { type: "resize", room: r, sx: p.x, sy: p.y, ow: r.w, oh: r.h };
    } else if (devEl) {
      const d = fpData.devices.find(x => x.entity_id === devEl.dataset.dev);
      fpDrag = { type: "dev", dev: d, dx: d.x - p.x, dy: d.y - p.y };
    } else if (roomEl) {
      const r = fpData.rooms.find(x => x.id === roomEl.dataset.room);
      fpDrag = { type: "room", room: r, dx: r.x - p.x, dy: r.y - p.y };
    }
    if (fpDrag) { svg.setPointerCapture(e.pointerId); e.preventDefault(); }
  });

  svg.addEventListener("pointermove", e => {
    if (!fpDrag) return;
    const p = fpSvgPoint(e);
    const snap = v => Math.round(v * 10) / 10;
    if (fpDrag.type === "room") {
      fpDrag.room.x = snap(p.x + fpDrag.dx);
      fpDrag.room.y = snap(p.y + fpDrag.dy);
    } else if (fpDrag.type === "dev") {
      fpDrag.dev.x = snap(p.x + fpDrag.dx);
      fpDrag.dev.y = snap(p.y + fpDrag.dy);
    } else if (fpDrag.type === "resize") {
      fpDrag.room.w = Math.max(0.5, snap(fpDrag.ow + (p.x - fpDrag.sx)));
      fpDrag.room.h = Math.max(0.5, snap(fpDrag.oh + (p.y - fpDrag.sy)));
    }
    fpDirty = true;
    fpRender();
  });

  const endDrag = () => { fpDrag = null; };
  svg.addEventListener("pointerup", endDrag);
  svg.addEventListener("pointercancel", endDrag);

  svg.addEventListener("dblclick", e => {
    if (!fpEdit) return;
    const roomEl = e.target.closest("[data-room]");
    const devEl = e.target.closest("[data-dev]");
    if (roomEl) {
      const r = fpData.rooms.find(x => x.id === roomEl.dataset.room);
      const name = prompt("Raumname:", r.name || "");
      if (name !== null) { r.name = name.trim(); fpDirty = true; fpRender(); }
    } else if (devEl && confirm("Gerät vom Grundriss entfernen?")) {
      fpData.devices = fpData.devices.filter(x => x.entity_id !== devEl.dataset.dev);
      fpDirty = true;
      fpRefreshDevicePicker();
      fpRender();
    }
  });

  document.getElementById("sh-fp-view-2d").addEventListener("click", () => fpSetView("2d"));
  document.getElementById("sh-fp-view-3d").addEventListener("click", () => fpSetView("3d"));
  document.getElementById("sh-fp-edit").addEventListener("click", fpToggleEdit);
  document.getElementById("sh-fp-add-room").addEventListener("click", fpAddRoom);
  document.getElementById("sh-fp-add-device").addEventListener("change", fpAddDevice);
  document.getElementById("sh-fp-save").addEventListener("click", fpSave);
})();

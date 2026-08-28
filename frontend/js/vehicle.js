// ================= AUTO-TAB (Spezifikationswunsch 2026-08-28) =================
// 3D-Modell-Viewer (three.js r128, per CDN wie Chart.js), Tanklog, eigen-
// ständige Auto-Ziele-Liste (bewusst nicht das normale Ziele-System, siehe
// backend crud_vehicle.py-Docstring).
let vehicleCache = null;
let vehicleFuelCache = [];
let vehicleGoalsCache = [];

async function loadVehicleTab() {
  const [vehicle, fuelEntries, goals, summary] = await Promise.all([
    api("/vehicle"),
    api("/vehicle/fuel-entries"),
    api("/vehicle/goals"),
    api("/vehicle/fuel-summary"),
  ]);
  vehicleCache = vehicle;
  vehicleFuelCache = fuelEntries;
  vehicleGoalsCache = goals;

  document.getElementById("vehicle-name-heading").textContent = vehicle.name;
  document.getElementById("vehicle-stat-odometer").textContent =
    summary.last_odometer_km != null ? `${summary.last_odometer_km.toLocaleString("de-DE")} km` : "–";
  document.getElementById("vehicle-stat-consumption").textContent =
    summary.avg_consumption_l_per_100km != null ? `${summary.avg_consumption_l_per_100km.toFixed(1)} l/100km` : "–";
  document.getElementById("vehicle-stat-cost-per-km").textContent =
    summary.avg_cost_per_km != null ? `${summary.avg_cost_per_km.toFixed(3)} €/km` : "–";
  document.getElementById("vehicle-stat-total-cost").textContent = eur(summary.total_cost);

  loadVehicle3DModel(vehicle.model_3d_url);

  renderVehicleFuelList();
  renderVehicleGoalList();
}

// ---------- 3D-Viewer (three.js r128) ----------
// vehicleThree: { renderer, scene, camera, controls, currentModel, dims, tween }
// "dims" hält die Maße/Achsen des geladenen Modells, damit setVehicleView()
// daraus Kamera-Positionen für Außen-/Innen-/Front-/… Ansichten ableiten kann.
let vehicleThree = null;
let vehicleView = "exterior";

function initVehicleThree() {
  if (vehicleThree) return vehicleThree;
  const canvas = document.getElementById("vehicle-3d-canvas");
  const container = document.getElementById("vehicle-3d-viewer");

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputEncoding = THREE.sRGBEncoding;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();

  // Studio-Reflexionen (Autolack/Chrom) ohne HDR-Datei - prozedurale Szene
  // aus three.js/examples, einmal in eine Env-Map gebacken.
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new THREE.RoomEnvironment(), 0.04).texture;

  const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 2000);
  camera.position.set(4, 2.4, 6);

  scene.add(new THREE.HemisphereLight(0xffffff, 0x2a2a30, 0.45));
  const key = new THREE.DirectionalLight(0xffffff, 1.6);
  key.position.set(6, 10, 6);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.bias = -0.0004;
  const d = 8;
  Object.assign(key.shadow.camera, { left: -d, right: d, top: d, bottom: -d, near: 0.5, far: 60 });
  scene.add(key);

  // Schatten-Fänger: unsichtbare Ebene, die nur den Bodenschatten zeigt.
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(200, 200),
    new THREE.ShadowMaterial({ opacity: 0.32 }),
  );
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  scene.add(ground);

  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.autoRotateSpeed = 1.4;

  function resize() {
    const w = container.clientWidth, h = container.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(container);
  resize();

  const clock = new THREE.Clock();
  function animate() {
    requestAnimationFrame(animate);
    const dt = clock.getDelta();
    const tw = vehicleThree.tween;
    if (tw) {
      tw.t = Math.min(1, tw.t + dt / tw.dur);
      const e = tw.t < 0.5 ? 2 * tw.t * tw.t : 1 - Math.pow(-2 * tw.t + 2, 2) / 2; // easeInOutQuad
      camera.position.lerpVectors(tw.fromPos, tw.toPos, e);
      controls.target.lerpVectors(tw.fromTarget, tw.toTarget, e);
      if (tw.t >= 1) vehicleThree.tween = null;
    }
    controls.update();
    renderer.render(scene, camera);
  }

  vehicleThree = { renderer, scene, camera, controls, ground, currentModel: null, dims: null, tween: null };
  animate();
  return vehicleThree;
}

function loadVehicle3DModel(url) {
  const empty = document.getElementById("vehicle-3d-empty");
  const canvas = document.getElementById("vehicle-3d-canvas");
  const toolbar = document.getElementById("vehicle-view-toolbar");
  const modelbar = document.getElementById("vehicle-stage-modelbar");

  if (!url) {
    empty.classList.remove("hidden");
    canvas.classList.add("hidden");
    toolbar.hidden = true;
    modelbar.hidden = true;
    if (vehicleThree?.currentModel) {
      vehicleThree.scene.remove(vehicleThree.currentModel);
      vehicleThree.currentModel = null;
    }
    return;
  }

  const three = initVehicleThree();
  if (three.currentModel) {
    three.scene.remove(three.currentModel);
    three.currentModel = null;
  }

  new THREE.GLTFLoader().load(
    url,
    gltf => {
      const root = gltf.scene;
      // Auf eine handliche Größe normieren (unabhängig von der Export-Einheit)
      // und mit den Rädern auf y=0 stellen, damit der Bodenschatten passt.
      let box = new THREE.Box3().setFromObject(root);
      const size0 = box.getSize(new THREE.Vector3());
      const maxDim = Math.max(size0.x, size0.y, size0.z) || 1;
      const scale = 4 / maxDim;
      root.scale.setScalar(scale);
      root.updateMatrixWorld(true);
      box = new THREE.Box3().setFromObject(root);
      const center = box.getCenter(new THREE.Vector3());
      root.position.x -= center.x;
      root.position.z -= center.z;
      root.position.y -= box.min.y;
      root.traverse(o => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
      three.scene.add(root);
      three.currentModel = root;

      root.updateMatrixWorld(true);
      const b = new THREE.Box3().setFromObject(root);
      const size = b.getSize(new THREE.Vector3());
      const mid = b.getCenter(new THREE.Vector3());
      // Längsachse des Autos = die größere der beiden Horizontalen.
      const lengthAxis = size.x >= size.z ? "x" : "z";
      three.dims = {
        center: mid, size,
        len: size[lengthAxis], wid: lengthAxis === "x" ? size.z : size.x, hei: size.y,
        lengthDir: new THREE.Vector3(lengthAxis === "x" ? 1 : 0, 0, lengthAxis === "z" ? 1 : 0),
        sideDir: new THREE.Vector3(lengthAxis === "x" ? 0 : 1, 0, lengthAxis === "z" ? 0 : 1),
        radius: Math.max(size.x, size.y, size.z),
      };

      empty.classList.add("hidden");
      canvas.classList.remove("hidden");
      toolbar.hidden = false;
      modelbar.hidden = false;
      setVehicleView(vehicleView, true);
    },
    undefined,
    () => {
      toast("3D-Modell konnte nicht geladen werden.");
      empty.classList.remove("hidden");
      canvas.classList.add("hidden");
      toolbar.hidden = true;
      modelbar.hidden = true;
    },
  );
}

// Kamera auf eine benannte Ansicht setzen ("exterior" | "interior" | "front"
// | "rear" | "side" | "top"). Alle Positionen werden aus der Bounding-Box des
// Modells abgeleitet, damit es für jedes hochgeladene Auto passt.
function setVehicleView(name, instant) {
  vehicleView = name;
  document.querySelectorAll(".vehicle-view-btn[data-view]").forEach(btn => {
    btn.classList.toggle("is-active", btn.dataset.view === name);
  });
  const three = vehicleThree;
  if (!three || !three.dims) return;
  const { center, len, wid, hei, lengthDir, sideDir, radius } = three.dims;
  const up = new THREE.Vector3(0, 1, 0);
  let pos, target = center.clone(), fov = 45, minD = 0.4;

  if (name === "interior") {
    // In die Fahrgastzelle: Kamera etwas hinter der Mitte + zur Seite +
    // auf Kopfhöhe; Blick nach vorne die Längsachse entlang.
    pos = center.clone()
      .add(lengthDir.clone().multiplyScalar(-0.10 * len))
      .add(sideDir.clone().multiplyScalar(0.18 * wid))
      .add(up.clone().multiplyScalar(0.16 * hei));
    target = center.clone()
      .add(lengthDir.clone().multiplyScalar(0.55 * len))
      .add(up.clone().multiplyScalar(0.06 * hei));
    fov = 62;
    minD = 0.01;
  } else if (name === "front") {
    pos = center.clone().add(lengthDir.clone().multiplyScalar(radius * 1.7)).add(up.clone().multiplyScalar(radius * 0.32));
  } else if (name === "rear") {
    pos = center.clone().add(lengthDir.clone().multiplyScalar(-radius * 1.7)).add(up.clone().multiplyScalar(radius * 0.32));
  } else if (name === "side") {
    pos = center.clone().add(sideDir.clone().multiplyScalar(radius * 1.9)).add(up.clone().multiplyScalar(radius * 0.18));
  } else if (name === "top") {
    pos = center.clone().add(up.clone().multiplyScalar(radius * 2.4)).add(lengthDir.clone().multiplyScalar(radius * 0.001));
  } else { // exterior (3/4-Ansicht)
    pos = center.clone()
      .add(lengthDir.clone().multiplyScalar(radius * 1.3))
      .add(sideDir.clone().multiplyScalar(radius * 1.15))
      .add(up.clone().multiplyScalar(radius * 0.8));
  }

  three.camera.fov = fov;
  three.camera.updateProjectionMatrix();
  three.controls.minDistance = minD;
  three.controls.maxDistance = radius * 6;

  if (instant || !three.currentModel) {
    three.camera.position.copy(pos);
    three.controls.target.copy(target);
    three.tween = null;
  } else {
    three.tween = {
      fromPos: three.camera.position.clone(), toPos: pos,
      fromTarget: three.controls.target.clone(), toTarget: target,
      t: 0, dur: 0.7,
    };
  }
}

document.querySelectorAll(".vehicle-view-btn[data-view]").forEach(btn => {
  btn.addEventListener("click", () => setVehicleView(btn.dataset.view));
});

document.getElementById("vehicle-view-spin").addEventListener("click", e => {
  const three = initVehicleThree();
  three.controls.autoRotate = !three.controls.autoRotate;
  e.currentTarget.classList.toggle("is-active", three.controls.autoRotate);
  e.currentTarget.setAttribute("aria-pressed", String(three.controls.autoRotate));
});

document.getElementById("vehicle-view-fs").addEventListener("click", () => {
  const stage = document.getElementById("vehicle-3d-viewer");
  if (document.fullscreenElement) document.exitFullscreen();
  else stage.requestFullscreen?.();
});
document.addEventListener("fullscreenchange", () => {
  const stage = document.getElementById("vehicle-3d-viewer");
  stage.classList.toggle("is-fullscreen", document.fullscreenElement === stage);
});

document.getElementById("vehicle-model-upload").addEventListener("change", async e => {
  const file = e.target.files[0];
  if (!file) return;
  const statusEl = document.getElementById("vehicle-model-upload-status");
  statusEl.textContent = "Lädt hoch …";
  const formData = new FormData();
  formData.append("file", file);
  try {
    const vehicle = await api("/vehicle/model", { method: "POST", body: formData });
    vehicleCache = vehicle;
    loadVehicle3DModel(vehicle.model_3d_url);
    statusEl.textContent = "";
    toast("3D-Modell hochgeladen.");
  } catch {
    statusEl.textContent = "";
  }
  e.target.value = "";
});

document.getElementById("vehicle-model-remove-btn").addEventListener("click", async () => {
  if (!confirm("3D-Modell entfernen?")) return;
  const vehicle = await api("/vehicle/model", { method: "DELETE" });
  vehicleCache = vehicle;
  loadVehicle3DModel(null);
  toast("3D-Modell entfernt.");
});

document.getElementById("vehicle-rename-btn").addEventListener("click", async () => {
  const name = prompt("Name des Autos:", vehicleCache?.name || "Mein Auto");
  if (!name || !name.trim()) return;
  const vehicle = await api("/vehicle", { method: "PUT", body: JSON.stringify({ name: name.trim() }) });
  vehicleCache = vehicle;
  document.getElementById("vehicle-name-heading").textContent = vehicle.name;
});

// ---------- Tanklog ----------
function renderVehicleFuelList() {
  const tbody = document.getElementById("vehicle-fuel-list");
  if (!vehicleFuelCache.length) {
    tbody.innerHTML = emptyRow(6, "list", "Noch keine Tankvorgänge erfasst.");
    return;
  }
  tbody.innerHTML = vehicleFuelCache.map(e => `
    <tr>
      <td>${fmtDate(e.date)}</td>
      <td>${e.odometer_km.toLocaleString("de-DE")} km</td>
      <td>${e.liters != null ? e.liters.toFixed(1) + " l" : "–"}</td>
      <td>${eur(e.total_cost)}</td>
      <td>${e.consumption_l_per_100km != null ? e.consumption_l_per_100km.toFixed(1) : "–"}</td>
      <td><button type="button" class="link-btn" data-vehicle-fuel-delete="${e.id}">Löschen</button></td>
    </tr>`).join("");
}

document.getElementById("vehicle-fuel-list").addEventListener("click", async e => {
  const delId = e.target.closest("[data-vehicle-fuel-delete]")?.dataset.vehicleFuelDelete;
  if (delId) {
    if (!confirm("Tankvorgang wirklich löschen?")) return;
    await api(`/vehicle/fuel-entries/${delId}`, { method: "DELETE" });
    loadVehicleTab();
  }
});

document.getElementById("vehicle-fuel-new-btn").addEventListener("click", () => {
  document.getElementById("vehicle-fuel-form").reset();
  document.getElementById("vehicle-fuel-date").value = new Date().toISOString().slice(0, 10);
  document.getElementById("vehicle-fuel-full-tank").checked = true;
  document.getElementById("vehicle-fuel-modal").classList.remove("hidden");
});
document.getElementById("vehicle-fuel-modal-close").addEventListener("click", () => {
  document.getElementById("vehicle-fuel-modal").classList.add("hidden");
});
document.getElementById("vehicle-fuel-form").addEventListener("submit", async e => {
  e.preventDefault();
  const litersVal = document.getElementById("vehicle-fuel-liters").value;
  const payload = {
    date: document.getElementById("vehicle-fuel-date").value,
    odometer_km: parseFloat(document.getElementById("vehicle-fuel-odometer").value),
    liters: litersVal !== "" ? parseFloat(litersVal) : null,
    total_cost: parseFloat(document.getElementById("vehicle-fuel-cost").value),
    full_tank: document.getElementById("vehicle-fuel-full-tank").checked,
    notes: document.getElementById("vehicle-fuel-notes").value || null,
  };
  await api("/vehicle/fuel-entries", { method: "POST", body: JSON.stringify(payload) });
  document.getElementById("vehicle-fuel-modal").classList.add("hidden");
  loadVehicleTab();
});

// ---------- Auto-Ziele ----------
function renderVehicleGoalList() {
  const host = document.getElementById("vehicle-goal-list");
  if (!vehicleGoalsCache.length) {
    host.innerHTML = `<div class="empty-state"><span class="empty-icon">${svgIcon("target")}</span><span>Noch keine Auto-Ziele.</span></div>`;
    return;
  }
  host.innerHTML = vehicleGoalsCache.map(g => `
    <div class="hub-list-row ${g.done ? "is-done" : ""}" style="cursor:default">
      <label style="display:flex;align-items:center;gap:10px;flex:1;min-width:0;cursor:pointer">
        <input type="checkbox" data-vehicle-goal-toggle="${g.id}" ${g.done ? "checked" : ""}>
        <span style="${g.done ? "text-decoration:line-through;opacity:0.6" : ""}">${esc(g.title)}${g.target_date ? ` <span class="page-sub" style="display:inline">(${fmtDate(g.target_date)})</span>` : ""}</span>
      </label>
      <button type="button" class="link-btn" data-vehicle-goal-delete="${g.id}">Löschen</button>
    </div>`).join("");
}

document.getElementById("vehicle-goal-list").addEventListener("click", async e => {
  const toggleId = e.target.closest("[data-vehicle-goal-toggle]")?.dataset.vehicleGoalToggle;
  if (toggleId) {
    const goal = vehicleGoalsCache.find(g => g.id === parseInt(toggleId));
    await api(`/vehicle/goals/${toggleId}`, { method: "PUT", body: JSON.stringify({ done: !goal.done }) });
    loadVehicleTab();
    return;
  }
  const delId = e.target.closest("[data-vehicle-goal-delete]")?.dataset.vehicleGoalDelete;
  if (delId) {
    if (!confirm("Auto-Ziel wirklich löschen?")) return;
    await api(`/vehicle/goals/${delId}`, { method: "DELETE" });
    loadVehicleTab();
  }
});

document.getElementById("vehicle-goal-new-btn").addEventListener("click", () => {
  document.getElementById("vehicle-goal-form").reset();
  document.getElementById("vehicle-goal-modal").classList.remove("hidden");
});
document.getElementById("vehicle-goal-modal-close").addEventListener("click", () => {
  document.getElementById("vehicle-goal-modal").classList.add("hidden");
});
document.getElementById("vehicle-goal-form").addEventListener("submit", async e => {
  e.preventDefault();
  const payload = {
    title: document.getElementById("vehicle-goal-title").value,
    notes: document.getElementById("vehicle-goal-notes").value || null,
    target_date: document.getElementById("vehicle-goal-date").value || null,
  };
  await api("/vehicle/goals", { method: "POST", body: JSON.stringify(payload) });
  document.getElementById("vehicle-goal-modal").classList.add("hidden");
  loadVehicleTab();
});

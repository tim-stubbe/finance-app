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

  document.getElementById("vehicle-model-remove-btn").classList.toggle("hidden", !vehicle.model_3d_url);
  loadVehicle3DModel(vehicle.model_3d_url);

  renderVehicleFuelList();
  renderVehicleGoalList();
}

// ---------- 3D-Viewer (three.js) ----------
let vehicleThree = null; // { renderer, scene, camera, controls, currentModel }

function initVehicleThree() {
  if (vehicleThree) return vehicleThree;
  const canvas = document.getElementById("vehicle-3d-canvas");
  const container = document.getElementById("vehicle-3d-viewer");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 1000);
  camera.position.set(4, 3, 6);

  scene.add(new THREE.AmbientLight(0xffffff, 0.7));
  const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
  dirLight.position.set(5, 8, 5);
  scene.add(dirLight);

  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  function resize() {
    const w = container.clientWidth, h = container.clientHeight;
    if (w === 0 || h === 0) return;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(container);
  resize();

  function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  }
  animate();

  vehicleThree = { renderer, scene, camera, controls, currentModel: null };
  return vehicleThree;
}

function loadVehicle3DModel(url) {
  const empty = document.getElementById("vehicle-3d-empty");
  const canvas = document.getElementById("vehicle-3d-canvas");
  if (!url) {
    empty.classList.remove("hidden");
    canvas.classList.add("hidden");
    return;
  }
  const three = initVehicleThree();
  if (three.currentModel) {
    three.scene.remove(three.currentModel);
    three.currentModel = null;
  }
  const loader = new THREE.GLTFLoader();
  loader.load(
    url,
    gltf => {
      // Modell zentrieren + auf eine handliche Größe skalieren, unabhängig
      // von den tatsächlichen Maßeinheiten der hochgeladenen Datei - sonst
      // könnte ein Modell winzig oder riesig im Viewer erscheinen, je
      // nachdem in welcher Einheit es exportiert wurde.
      const box = new THREE.Box3().setFromObject(gltf.scene);
      const size = box.getSize(new THREE.Vector3());
      const center = box.getCenter(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z) || 1;
      const scale = 4 / maxDim;
      gltf.scene.scale.setScalar(scale);
      gltf.scene.position.sub(center.multiplyScalar(scale));
      three.scene.add(gltf.scene);
      three.currentModel = gltf.scene;
      empty.classList.add("hidden");
      canvas.classList.remove("hidden");
    },
    undefined,
    () => {
      toast("3D-Modell konnte nicht geladen werden.");
      empty.classList.remove("hidden");
      canvas.classList.add("hidden");
    },
  );
}

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
    document.getElementById("vehicle-model-remove-btn").classList.remove("hidden");
    loadVehicle3DModel(vehicle.model_3d_url);
    statusEl.textContent = "";
    toast("3D-Modell hochgeladen.");
  } catch {
    statusEl.textContent = "";
  }
  e.target.value = "";
});

document.getElementById("vehicle-model-remove-btn").addEventListener("click", async () => {
  const vehicle = await api("/vehicle/model", { method: "DELETE" });
  vehicleCache = vehicle;
  document.getElementById("vehicle-model-remove-btn").classList.add("hidden");
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

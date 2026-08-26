// ================= PROJEKTE (Nebengeschäfte) =================
let projectsCache = [];

async function loadProjectsTab() {
  if (!accountsCache.length) await loadAccounts();
  document.getElementById("project-account").innerHTML = '<option value="">– keins –</option>' +
    accountsCache.map(a => `<option value="${a.id}">${esc(a.name)}</option>`).join("");
  const [projects, issues] = await Promise.all([
    api("/business-projects"),
    api("/business-issues"),
  ]);
  projectsCache = projects;
  const issuesByProject = new Map();
  issues.forEach(i => {
    if (!issuesByProject.has(i.project_id)) issuesByProject.set(i.project_id, []);
    issuesByProject.get(i.project_id).push(i);
  });

  const list = document.getElementById("projects-list");
  if (!projects.length) {
    list.innerHTML = `<div class="empty-state"><span class="empty-icon">${svgIcon("briefcase")}</span><span>Noch keine Projekte angelegt. Leg oben rechts eins an.</span></div>`;
  } else {
    list.innerHTML = "";
    projects.forEach(p => list.appendChild(renderProjectCard(p, issuesByProject.get(p.id) || [])));
  }

  const totalOpen = issues.length;
  const badge = document.getElementById("projects-nav-badge");
  badge.textContent = totalOpen;
  badge.classList.toggle("hidden", !totalOpen);

  loadProjectTimeSummaries();
}

function fmtMinutes(min) {
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return h > 0 ? `${h} Std. ${m} Min.` : `${m} Min.`;
}

// Zeiterfassung pro Projekt - eine Summary fuer alle Projekte auf einmal statt
// eines Aufrufs je Karte, damit das Laden der Projekte-Liste nicht mit der
// Anzahl Projekte langsamer wird.
async function loadProjectTimeSummaries() {
  const summaries = await api("/time-entries/summary");
  const byProject = new Map(summaries.map(s => [s.project_id, s]));
  projectsCache.forEach(p => {
    const s = byProject.get(p.id);
    const el = document.getElementById(`project-time-${p.id}`);
    const btn = document.querySelector(`[data-project-time-toggle="${p.id}"]`);
    if (!el || !btn) return;
    const running = s && s.running_entry_id;
    el.textContent = s && s.total_minutes > 0 ? `⏱ ${fmtMinutes(s.total_minutes)} erfasst` : "";
    btn.textContent = running ? "⏹ Stoppen" : "⏱ Start";
    btn.dataset.projectTimeRunning = running ? s.running_entry_id : "";
    btn.classList.toggle("btn-warn", !!running);
  });
}

document.getElementById("projects-list").addEventListener("click", async e => {
  const toggleId = e.target.closest("[data-project-time-toggle]")?.dataset.projectTimeToggle;
  if (toggleId) {
    const btn = e.target.closest("[data-project-time-toggle]");
    if (btn.dataset.projectTimeRunning) {
      await api(`/time-entries/${btn.dataset.projectTimeRunning}/stop`, { method: "POST" });
    } else {
      await api(`/projects/${toggleId}/time-entries/start`, { method: "POST" });
    }
    loadProjectTimeSummaries();
  }
});

function projectIsOverdue(p) {
  if (!p.check_interval_days) return false;
  // Fallback auf created_at spiegelt main._scheduled_business_check_reminder -
  // ohne das galt ein gerade erst angelegtes Projekt sofort als überfällig.
  const reference = new Date(p.last_checked_at || p.created_at);
  const days = (Date.now() - reference.getTime()) / (1000 * 60 * 60 * 24);
  return days >= p.check_interval_days;
}

function renderProjectCard(p, openIssues) {
  const card = document.createElement("div");
  card.className = "goal-card";
  const overdue = projectIsOverdue(p);
  const lastChecked = p.last_checked_at
    ? new Date(p.last_checked_at).toLocaleDateString("de-DE")
    : "noch nie geprüft";
  card.innerHTML = `
    <div class="goal-card-head">
      <h4>${esc(p.name)}</h4>
      <span class="goal-chip ${openIssues.length ? "is-warn" : ""}">${openIssues.length} offen</span>
    </div>
    ${p.description ? `<p class="goal-desc">${esc(p.description)}</p>` : ""}
    ${p.account_name ? `<p class="goal-values">${esc(p.account_name)} · diesen Monat ${eur(p.income_this_month)} · gesamt ${eur(p.income_total)}</p>` : ""}
    <p class="goal-meta ${overdue ? "goal-error" : ""}">
      ${overdue ? "⚠️ " : ""}Zuletzt geprüft: ${lastChecked}${p.check_interval_days ? ` · Intervall ${p.check_interval_days} Tage` : ""}
    </p>
    <div id="project-issues-${p.id}" class="todo-row-list"></div>
    <p class="goal-meta" id="project-time-${p.id}"></p>
    <div class="filter-row" style="margin-top:4px">
      <button type="button" class="btn-ghost btn-sm" data-project-checked="${p.id}">✓ Geprüft</button>
      <button type="button" class="btn-ghost btn-sm" data-project-add-issue="${p.id}">+ Punkt</button>
      <button type="button" class="btn-ghost btn-sm" data-project-time-toggle="${p.id}">⏱ …</button>
      <button type="button" class="link-btn" data-project-edit="${p.id}">Bearbeiten</button>
      <button type="button" class="link-btn" data-notes-entity="business_project" data-notes-id="${p.id}" data-notes-label="${esc(p.name)}">📝 Notizen</button>
    </div>
  `;
  const issuesWrap = card.querySelector(`#project-issues-${p.id}`);
  issuesWrap.innerHTML = openIssues.map(i => `
    <div class="todo-row">
      <span class="todo-title">${esc(i.title)}${i.notes ? `<br><span class="page-sub">${esc(i.notes)}</span>` : ""}</span>
      <button type="button" class="link-btn" data-issue-resolve="${i.id}">✓ Erledigt</button>
    </div>
  `).join("");
  return card;
}

document.getElementById("projects-list").addEventListener("click", async e => {
  const checkedId = e.target.closest("[data-project-checked]")?.dataset.projectChecked;
  if (checkedId) {
    await api(`/business-projects/${checkedId}/checked`, { method: "POST" });
    toast("Als geprüft bestätigt.");
    loadProjectsTab();
    return;
  }
  const addIssueId = e.target.closest("[data-project-add-issue]")?.dataset.projectAddIssue;
  if (addIssueId) {
    document.getElementById("project-issue-project-id").value = addIssueId;
    document.getElementById("project-issue-form").reset();
    document.getElementById("project-issue-modal").classList.remove("hidden");
    return;
  }
  const editId = e.target.closest("[data-project-edit]")?.dataset.projectEdit;
  if (editId) {
    openProjectModal(projectsCache.find(p => p.id === parseInt(editId)));
    return;
  }
  const resolveId = e.target.closest("[data-issue-resolve]")?.dataset.issueResolve;
  if (resolveId) {
    await api(`/business-issues/${resolveId}/resolve`, { method: "POST" });
    loadProjectsTab();
  }
});

function openProjectModal(project) {
  document.getElementById("project-modal-title").textContent = project ? "Projekt bearbeiten" : "Neues Projekt";
  document.getElementById("project-id").value = project ? project.id : "";
  document.getElementById("project-name").value = project ? project.name : "";
  document.getElementById("project-description").value = project?.description || "";
  document.getElementById("project-interval").value = project?.check_interval_days || "";
  document.getElementById("project-account").value = project?.account_id || "";
  document.getElementById("project-archive").classList.toggle("hidden", !project);
  document.getElementById("project-modal").classList.remove("hidden");
}
document.getElementById("project-new-btn").addEventListener("click", () => openProjectModal(null));
document.getElementById("project-modal-close").addEventListener("click", () => {
  document.getElementById("project-modal").classList.add("hidden");
});
document.getElementById("project-issue-modal-close").addEventListener("click", () => {
  document.getElementById("project-issue-modal").classList.add("hidden");
});

document.getElementById("project-form").addEventListener("submit", async e => {
  e.preventDefault();
  const id = document.getElementById("project-id").value;
  const payload = {
    name: document.getElementById("project-name").value,
    description: document.getElementById("project-description").value || null,
    check_interval_days: document.getElementById("project-interval").value
      ? parseInt(document.getElementById("project-interval").value) : null,
    account_id: document.getElementById("project-account").value
      ? parseInt(document.getElementById("project-account").value) : null,
  };
  if (id) {
    await api(`/business-projects/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
  } else {
    await api("/business-projects", { method: "POST", body: JSON.stringify(payload) });
  }
  document.getElementById("project-modal").classList.add("hidden");
  loadProjectsTab();
});

document.getElementById("project-archive").addEventListener("click", async () => {
  const id = document.getElementById("project-id").value;
  if (!id || !confirm("Projekt archivieren? Offene Punkte bleiben erhalten, das Projekt verschwindet aber aus der Liste.")) return;
  await api(`/business-projects/${id}`, { method: "PATCH", body: JSON.stringify({ active: false }) });
  document.getElementById("project-modal").classList.add("hidden");
  loadProjectsTab();
});

document.getElementById("project-issue-form").addEventListener("submit", async e => {
  e.preventDefault();
  const payload = {
    project_id: parseInt(document.getElementById("project-issue-project-id").value),
    title: document.getElementById("project-issue-title").value,
    notes: document.getElementById("project-issue-notes").value || null,
  };
  await api("/business-issues", { method: "POST", body: JSON.stringify(payload) });
  document.getElementById("project-issue-modal").classList.add("hidden");
  loadProjectsTab();
});

async function refreshProjectsBadge() {
  try {
    const issues = await api("/business-issues");
    const badge = document.getElementById("projects-nav-badge");
    badge.textContent = issues.length;
    badge.classList.toggle("hidden", !issues.length);
  } catch (e) {
    // Beim App-Start unkritisch
  }
}


// ================= FOTOS (IMMICH) =================
// Je Duplikatgruppe die Menge der aktuell zum Papierkorb ausgewaehlten
// Bild-IDs - eine echte, von den anderen Bildern unabhaengige Mehrfachauswahl.
// Kein "genau ein Bild bleibt" mehr: leer = alles bleibt, komplett gefuellt =
// alles geht raus, beides ist ein gueltiger Zustand.
const photoTrash = new Map();
// Immichs Vorschlag bleibt als fester Bezugspunkt fuer die
// Uebereinstimmungs-Prozente erhalten, unabhaengig davon, was der Nutzer
// gerade aus-/abgewaehlt hat - sonst wuerde sich die Prozentzahl bei jedem
// Klick auf ein anderes Bild beziehen und waere nicht mehr vergleichbar.
const photoSuggestedKeep = new Map();
// Übereinstimmung je Gruppe, nachgeladen nachdem die Bilder schon stehen -
// die Berechnung braucht einen Moment und soll die Anzeige nicht aufhalten.
const photoSimilarity = new Map();
let photoGroupsCache = [];
let photoPage = { offset: 0, hasMore: false, total: 0 };

function formatBytes(n) {
  if (!n) return "";
  const mb = n / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.round(n / 1024)} KB`;
}

// Ohne Rueckgriff auf Admin-Rechte (server.statistics) bleibt available=false -
// dann einfach unauffaellig nichts anzeigen, statt eine Fehlermeldung fuer
// eine reine Zusatzinfo.
async function loadPhotoStats() {
  const el = document.getElementById("photos-stats");
  try {
    const s = await api("/immich/stats");
    if (!s.available) { el.classList.add("hidden"); return; }
    const totalGb = (s.usage_bytes / 1024 / 1024 / 1024).toFixed(1);
    el.textContent = `📚 Bibliothek: ${s.photos.toLocaleString("de-DE")} Fotos, ` +
      `${s.videos.toLocaleString("de-DE")} Videos, ${totalGb} GB belegt.`;
    el.classList.remove("hidden");
  } catch {
    el.classList.add("hidden");
  }
}

async function loadPhotosTab(offset = 0) {
  const hint = document.getElementById("photos-setup-hint");
  const hintText = document.getElementById("photos-setup-text");
  const summary = document.getElementById("photos-summary");
  const wrap = document.getElementById("photos-groups");

  const s = await api("/settings/immich");
  if (!s.url || !s.api_key_set) {
    hint.classList.remove("hidden");
    summary.classList.add("hidden");
    wrap.innerHTML = "";
    hintText.textContent = !s.url && !s.api_key_set
      ? "Es fehlen Server-Adresse und API-Schlüssel."
      : (!s.url ? "Es fehlt die Server-Adresse." : "Es fehlt der API-Schlüssel.");
    return;
  }
  hint.classList.add("hidden");
  loadPhotoStats();

  wrap.innerHTML = `<p class="page-sub loading-pulse">Suche doppelte Aufnahmen …</p>`;
  let data;
  try {
    data = await api(`/immich/duplicates?offset=${offset}&limit=20`);
  } catch (e) {
    summary.classList.add("hidden");
    wrap.innerHTML = `<div class="panel"><p class="page-sub">${esc(e.message)}</p></div>`;
    return;
  }

  photoPage = { offset: data.offset, hasMore: data.has_more, total: data.total_groups };
  photoTrash.clear();
  photoSuggestedKeep.clear();
  data.groups.forEach(g => {
    // Immichs Vorschlag übernehmen; falls keiner kommt, das erste Bild.
    const suggested = g.suggested_keep_ids.find(id => g.assets.some(a => a.id === id)) || g.assets[0]?.id;
    photoSuggestedKeep.set(g.duplicate_id, suggested);
    // Vorbelegung wie bisher (alles ausser dem Vorschlag zum Papierkorb) -
    // spart bei der haeufigsten Auswahl ("das beste Bild behalten") weiterhin
    // Klicks. Der Nutzer kann jedes Bild einzeln umschalten, auch den
    // Vorschlag selbst, bis hin zu "alles" oder "nichts".
    g.assets.sort((a, b) => (b.id === suggested) - (a.id === suggested));
    photoTrash.set(g.duplicate_id, new Set(g.assets.filter(a => a.id !== suggested).map(a => a.id)));
  });
  summary.classList.remove("hidden");
  if (data.total_groups === 0) {
    summary.innerHTML = `<strong>Keine Duplikate gefunden.</strong> Deine Bibliothek ist sauber.`;
    wrap.innerHTML = "";
    return;
  }
  // Der Papierkorb-Zustand kommt vom Server und ist keine Behauptung: Immich
  // löscht bei abgeschaltetem Papierkorb sofort endgültig.
  const trashNote = data.trash_enabled
    ? `Die übrigen wandern in Immichs Papierkorb und sind dort
       ${data.trash_days ? `${data.trash_days} Tage lang ` : ""}wiederherstellbar.`
    : `<span class="photos-warn">⚠️ Achtung: In Immich ist der Papierkorb abgeschaltet.
       Aufräumen ist deshalb gesperrt – sonst wären Bilder sofort unwiderruflich weg.</span>`;
  const from = data.offset + 1;
  const to = data.offset + data.groups.length;
  summary.innerHTML = `<strong>${data.total_groups} Gruppen</strong>
    mit insgesamt ${data.total_assets} Aufnahmen – angezeigt ${from}–${to}.
    Wähle je Gruppe, welche Bilder in den Papierkorb sollen – jedes Bild einzeln,
    auch alle oder keins. ${trashNote}`;

  // Auf Wunsch zuerst die staerksten Uebereinstimmungen zeigen (100% zuerst,
  // absteigend) statt Immichs eigener Reihenfolge. Das Backend liefert schon
  // best_similarity_percent je Gruppe mit (billiger Vorab-Vergleich, siehe
  // main._best_similarity) - damit steht die Sortierung sofort, ohne auf die
  // vollstaendigen Paar-Vergleiche zu warten. Sobald loadSimilarities() die
  // genauen Werte nachliefert, wird nochmal nachsortiert (kann die Reihenfolge
  // leicht verfeinern, das grobe Bild stimmt aber von Anfang an).
  data.groups.sort((a, b) => (b.best_similarity_percent ?? 0) - (a.best_similarity_percent ?? 0));
  photoGroupsCache = data.groups;
  renderPhotoGroups();

  await loadSimilarities(data.groups);
  data.groups.sort((a, b) => groupMaxSimilarity(b) - groupMaxSimilarity(a));
  photoGroupsCache = data.groups;
  renderPhotoGroups();
}

function groupMaxSimilarity(group) {
  const pairs = photoSimilarity.get(group.duplicate_id) || {};
  let max = 0;
  for (const inner of Object.values(pairs)) {
    for (const pct of Object.values(inner)) {
      if (pct > max) max = pct;
    }
  }
  // Fallback auf den billigen Backend-Wert, falls fuer diese Gruppe kein
  // Paar-Vergleich zustande kam (z.B. Netzwerkfehler, siehe loadSimilarities)
  // - sonst faellt eine an sich sehr aehnliche Gruppe faelschlich auf 0/ans Ende.
  return max || group.best_similarity_percent || 0;
}

// Nacheinander statt alle gleichzeitig: jede Gruppe bedeutet mehrere
// Bildabrufe, parallel wuerde das Immich unnoetig belasten.
async function loadSimilarities(groups) {
  for (const g of groups) {
    if (photoSimilarity.has(g.duplicate_id)) continue;
    try {
      const ids = g.assets.map(a => a.id).join(",");
      const s = await api(`/immich/duplicates/${g.duplicate_id}/similarity?asset_ids=${encodeURIComponent(ids)}`);
      photoSimilarity.set(g.duplicate_id, s.pairs);
    } catch (e) {
      photoSimilarity.set(g.duplicate_id, {});
    }
  }
}

// Beim Umwählen des zu behaltenden Bilds NUR die eine betroffene Gruppe
// aktualisieren - nicht renderPhotoGroups() (kompletter Neuaufbau aller 20
// sichtbaren Gruppen samt jedem einzelnen Bild) aufrufen. Das war der
// eigentliche Grund fuer "die ganze Seite laedt neu, aber es passiert
// nichts": ein einzelner Kartenklick liess bei jeder Betaetigung 40-100+
// Vorschaubilder gleichzeitig neu anfordern, was auf allen getesteten
// Browsern (iPhone/Mac Safari/Windows Firefox) als voller Seiten-Neuaufbau
// wahrgenommen wurde - der Zustand aendert sich dabei zwar korrekt, aber
// sichtbar wird davon in dem visuellen Chaos praktisch nichts.
// Aktualisiert nur die eine betroffene Gruppe (Kartenzustand, Papierkorb-
// Zaehler/-Knopf, Uebereinstimmungs-Plaketten) - kein renderPhotoGroups()
// (kompletter Neuaufbau aller sichtbaren Gruppen samt jedem Vorschaubild).
// Genau das war zuvor der Grund, warum ein einzelner Klick wie ein Neuladen
// der ganzen Seite wirkte.
function updateGroupSelectionUI(duplicateId) {
  const group = photoGroupsCache.find(g => g.duplicate_id === duplicateId);
  const groupEl = document.querySelector(`.photo-group[data-group="${CSS.escape(duplicateId)}"]`);
  if (!group || !groupEl) return;
  const trashSet = photoTrash.get(duplicateId) || new Set();

  groupEl.querySelectorAll(".photo-card").forEach(card => {
    const isTrash = trashSet.has(card.dataset.asset);
    card.classList.toggle("is-trash", isTrash);
    card.classList.toggle("is-keep", !isTrash);
    const badge = card.querySelector(".photo-badge");
    if (badge) badge.textContent = isTrash ? "Papierkorb" : "behalten";
  });

  const applyBtn = groupEl.querySelector("[data-apply]");
  if (applyBtn) {
    applyBtn.textContent = `${trashSet.size} in den Papierkorb`;
    applyBtn.classList.toggle("hidden", trashSet.size === 0);
  }

  updateSimilarityBadges(duplicateId);
}

function updateSimilarityBadges(duplicateId) {
  const groupEl = document.querySelector(`.photo-group[data-group="${CSS.escape(duplicateId)}"]`);
  if (!groupEl) return;
  // Fester Bezugspunkt (Immichs Vorschlag), unabhaengig von der aktuellen
  // Papierkorb-Auswahl - siehe Kommentar bei der Variable weiter oben.
  const refId = photoSuggestedKeep.get(duplicateId);
  const pairs = photoSimilarity.get(duplicateId) || {};
  groupEl.querySelectorAll(".photo-card").forEach(card => {
    const assetId = card.dataset.asset;
    const existing = card.querySelector(".photo-sim");
    if (assetId === refId) { existing?.remove(); return; }
    const pct = pairs[refId]?.[assetId];
    if (pct === undefined) { existing?.remove(); return; }
    const cls = pct >= 95 ? "sim-high" : pct >= 80 ? "sim-mid" : "sim-low";
    const title = pct >= 95 ? "praktisch identisch" : pct >= 80 ? "sehr ähnlich" : "nur ähnliche Aufnahme";
    if (existing) {
      existing.textContent = `${pct}%`;
      existing.className = `photo-sim ${cls}`;
      existing.title = title;
    } else {
      const span = document.createElement("span");
      span.className = `photo-sim ${cls}`;
      span.title = title;
      span.textContent = `${pct}%`;
      card.querySelector(".photo-badge")?.after(span);
    }
  });

  // Große Übereinstimmungsanzeige im Gruppentitel aktualisieren - die
  // Ähnlichkeit wird oft erst asynchron nachgeladen, nach dem ersten Rendern
  // der Gruppe. groupUniformPct() entscheidet, ob das bei dieser Gruppengröße
  // überhaupt eindeutig genug ist (siehe Kommentar dort).
  const group = photoGroupsCache.find(g => g.duplicate_id === duplicateId);
  const titleEl = groupEl.querySelector(".panel-title");
  if (group && titleEl) {
    titleEl.querySelector(".photo-sim-big")?.remove();
    const pct = groupUniformPct(group, refId);
    if (pct !== null) {
      const cls = pct >= 95 ? "sim-high" : pct >= 80 ? "sim-mid" : "sim-low";
      const span = document.createElement("span");
      span.className = `photo-sim-big ${cls}`;
      span.textContent = `${pct}% Übereinstimmung`;
      titleEl.appendChild(span);
    }
  }
}

// Bei genau zwei Aufnahmen ist die Übereinstimmung die zentrale Frage der
// ganzen Gruppe ("ist das wirklich dasselbe Foto?") - deshalb groß und direkt
// sichtbar statt nur als kleine Plakette an der Karte. Bei mehr als zwei
// Aufnahmen wäre eine einzelne Zahl mehrdeutig (welches Paar ist gemeint?) -
// AUSSER alle stimmen exakt zu 100% mit dem Vorschlag überein, dann ist die
// Aussage "das ist wirklich überall dasselbe Bild" trotzdem eindeutig.
function groupUniformPct(g, refId) {
  const others = g.assets.filter(a => a.id !== refId).map(a => a.id);
  if (!others.length) return null;
  const pairs = photoSimilarity.get(g.duplicate_id)?.[refId] || {};
  if (g.assets.length === 2) {
    const pct = pairs[others[0]];
    return (pct === undefined || pct === null) ? null : pct;
  }
  for (const id of others) {
    const pct = pairs[id];
    if (pct === undefined || pct === null || pct < 100) return null;
  }
  return 100;
}

function renderBigSimHtml(g, refId) {
  const pct = groupUniformPct(g, refId);
  if (pct === null) return "";
  const cls = pct >= 95 ? "sim-high" : pct >= 80 ? "sim-mid" : "sim-low";
  return `<span class="photo-sim-big ${cls}">${pct}% Übereinstimmung</span>`;
}

function videoBadgeHtml(type) {
  return type === "VIDEO" ? `<span class="photo-video-badge" title="Video">▶</span>` : "";
}

function renderPhotoGroups() {
  const wrap = document.getElementById("photos-groups");
  wrap.innerHTML = photoGroupsCache.map(g => {
    const trashSet = photoTrash.get(g.duplicate_id) || new Set();
    const refId = photoSuggestedKeep.get(g.duplicate_id);
    const cards = g.assets.map(a => {
      const isTrash = trashSet.has(a.id);
      const dims = a.width && a.height ? `${a.width}×${a.height}` : "";
      const meta = [dims, formatBytes(a.size_bytes)].filter(Boolean).join(" · ");
      // Übereinstimmung zu Immichs Vorschlag - beantwortet die Frage
      // "ist das wirklich dasselbe Foto oder nur eine ähnliche Aufnahme".
      const pct = a.id === refId ? null : photoSimilarity.get(g.duplicate_id)?.[refId]?.[a.id];
      const simBadge = pct === undefined || pct === null ? "" :
        `<span class="photo-sim ${pct >= 95 ? "sim-high" : pct >= 80 ? "sim-mid" : "sim-low"}"
           title="${pct >= 95 ? "praktisch identisch" : pct >= 80 ? "sehr ähnlich" : "nur ähnliche Aufnahme"}">${pct}%</span>`;
      const videoBadge = videoBadgeHtml(a.type);
      return `<button type="button" class="photo-card ${isTrash ? "is-trash" : "is-keep"}"
                data-group="${esc(g.duplicate_id)}" data-asset="${esc(a.id)}">
        <img loading="lazy" src="/api/immich/thumbnail/${esc(a.id)}" alt="">
        ${videoBadge}
        <span class="photo-zoom" data-zoom="${esc(a.id)}" data-caption="${esc(a.file_name || "")}"
              title="Vergrößern">🔍</span>
        <span class="photo-badge">${isTrash ? "Papierkorb" : "behalten"}</span>${simBadge}
        <span class="photo-meta">
          <span class="photo-name">${esc(a.file_name || "")}</span>
          ${meta ? `<span>${esc(meta)}</span>` : ""}
          ${a.created_at ? `<span>${fmtDate(a.created_at.slice(0, 10))}</span>` : ""}
        </span>
      </button>`;
    }).join("");

    // Gekürzt dargestellte Gruppe: dann darf nicht "in den Papierkorb"
    // angeboten werden, denn die nicht gezeigten Bilder wären mit betroffen,
    // ohne dass man sie je gesehen hat.
    const truncated = g.asset_count > g.assets.length;
    // Immer verfügbar (nicht nur bei bis zu 4 Bildern) und immer an erster
    // Stelle - bei mehr als 4 Aufnahmen vergleicht er nur die ersten 4. Sonst
    // rutschte an dieser Stelle bei größeren Gruppen "Sind keine Duplikate"
    // nach vorn, und Nutzer haben aus Gewohnheit an der ersten Position
    // geklickt und dabei echte Duplikatgruppen ausversehen verworfen.
    const compareBtn = g.assets.length >= 2
      ? `<button type="button" class="btn-ghost" data-compare="${esc(g.duplicate_id)}">🔍 ${g.assets.length > 4 ? "Erste 4 vergleichen" : "Nebeneinander vergleichen"}</button>`
      : "";
    // "Sind keine Duplikate" bewusst immer als LETZTER Button, nie an erster
    // Stelle - siehe Kommentar bei compareBtn oben.
    const actions = truncated
      ? `<button type="button" class="btn-ghost" data-dismiss="${esc(g.duplicate_id)}">Sind keine Duplikate</button>`
      : `${compareBtn}
         <button type="button" class="btn-ghost" data-select-all="${esc(g.duplicate_id)}">Alle Papierkorb</button>
         <button type="button" class="btn-ghost" data-select-none="${esc(g.duplicate_id)}">Alle behalten</button>
         <button type="button" class="btn-primary ${trashSet.size === 0 ? "hidden" : ""}" data-apply="${esc(g.duplicate_id)}">
           ${trashSet.size} in den Papierkorb
         </button>
         <button type="button" class="btn-ghost" data-dismiss="${esc(g.duplicate_id)}">Sind keine Duplikate</button>`;

    const bigSim = renderBigSimHtml(g, refId);

    return `<div class="panel photo-group" data-group="${esc(g.duplicate_id)}">
      <div class="photo-group-head">
        <h3 class="panel-title">${g.asset_count} ähnliche Aufnahmen${bigSim}</h3>
        <div class="photo-group-actions">${actions}</div>
      </div>
      ${truncated ? `<p class="photos-warn">Sehr große Gruppe – hier werden nur
        ${g.assets.length} von ${g.asset_count} Aufnahmen gezeigt. Bei dieser Menge sind das
        meist keine echten Duplikate (z.B. eine Serienaufnahme). Zum Aufräumen bitte direkt
        in Immich prüfen – hier wäre nicht sichtbar, was alles betroffen ist.</p>` : ""}
      <div class="photo-strip">${cards}</div>
    </div>`;
  }).join("");

  // Blätter-Schaltflächen
  const nav = [];
  if (photoPage.offset > 0) nav.push(`<button type="button" class="btn-ghost" data-page="${Math.max(0, photoPage.offset - 20)}">← Zurück</button>`);
  if (photoPage.hasMore) nav.push(`<button type="button" class="btn-primary" data-page="${photoPage.offset + 20}">Weitere 20 Gruppen →</button>`);
  if (nav.length) wrap.innerHTML += `<div class="photo-pager">${nav.join("")}</div>`;
}

// Klick auf ein Bild wählt es als das zu behaltende aus.
// ---------- Lupe: Bild vergrößert anzeigen ----------
// Baut 1 bis 4 Figuren dynamisch auf, statt fest verdrahteter 2 Slots -
// damit sich sowohl das einzelne Vergrößern als auch der Nebeneinander-
// Vergleich (jetzt bis zu 4 Aufnahmen) dieselbe Funktion teilen.
let lightboxAssetIds = [];
let lightboxGroupId = null;

function renderLightbox(items) {
  const box = document.getElementById("lightbox-images");
  box.innerHTML = items.map((it, i) => `<figure class="lightbox-figure">
      <img id="lightbox-img-${i}" alt="" src="/api/immich/thumbnail/${encodeURIComponent(it.id)}?size=preview">
      <figcaption class="lightbox-caption">${esc(it.caption || "")}</figcaption>
    </figure>`).join("");
  const isCompare = items.length > 1;
  document.getElementById("lightbox-box").classList.toggle("is-compare", isCompare);
  document.getElementById("lightbox-delete-all").classList.toggle("hidden", !isCompare);
  document.getElementById("photo-lightbox").classList.remove("hidden");
  lightboxAssetIds = items.map(it => it.id);
  document.getElementById("lightbox-ai-result").textContent = "";
}

function openLightbox(assetId, caption) {
  lightboxGroupId = null;
  renderLightbox([{ id: assetId, caption }]);
}

// Bei bis zu vier Aufnahmen lohnt sich ein direkter Nebeneinander-Vergleich
// besonders - bei mehr wäre die Übersicht zu unruhig, um noch zu erkennen,
// welche Details sich unterscheiden.
function openLightboxCompare(items, groupId = null) {
  lightboxGroupId = groupId;
  renderLightbox(items);
}

function closeLightbox() {
  document.getElementById("photo-lightbox").classList.add("hidden");
  document.getElementById("lightbox-images").innerHTML = "";
  lightboxAssetIds = [];
  lightboxGroupId = null;
}

document.getElementById("lightbox-delete-all").addEventListener("click", async () => {
  if (!lightboxAssetIds.length) return;
  if (!confirm(`${lightboxAssetIds.length} Aufnahme(n) in den Papierkorb verschieben?\n\nSie bleiben in Immich wiederherstellbar.`)) return;
  try {
    const res = await api("/immich/photos/trash", {
      method: "POST",
      body: JSON.stringify({ asset_ids: lightboxAssetIds }),
    });
    toast(`${res.trashed} Aufnahme(n) in den Papierkorb verschoben.`);
    const groupId = lightboxGroupId;
    closeLightbox();
    if (groupId) removePhotoGroupLocally(groupId);
  } catch (err) {
    toast("Fehler: " + err.message);
  }
});
document.getElementById("lightbox-close").addEventListener("click", closeLightbox);
document.getElementById("photo-lightbox").addEventListener("click", e => {
  if (e.target.id === "photo-lightbox") closeLightbox();
});

document.getElementById("lightbox-ai-btn").addEventListener("click", async () => {
  if (!lightboxAssetIds.length) return;
  const btn = document.getElementById("lightbox-ai-btn");
  const resultEl = document.getElementById("lightbox-ai-result");
  btn.disabled = true;
  resultEl.textContent = "Analysiere … (kann bei kleinen Modellen auf bescheidener Hardware einige Minuten dauern)";
  try {
    const res = await api("/immich/ai-suggestion", {
      method: "POST",
      body: JSON.stringify({ asset_ids: lightboxAssetIds }),
    });
    resultEl.textContent = res.error ? `Fehler: ${res.error}` : res.reason || "Keine Einschätzung erhalten.";
  } catch (err) {
    resultEl.textContent = "Fehler: " + err.message;
  } finally {
    btn.disabled = false;
  }
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeLightbox();
});

// Vor dem eigentlichen Auswahl-Klick abgefangen: ein Klick auf die Lupe soll
// das Bild vergrößern, nicht gleichzeitig als "behalten"/"auswählen" zählen.
function checkZoomClick(e) {
  const zoom = e.target.closest("[data-zoom]");
  if (!zoom) return false;
  openLightbox(zoom.dataset.zoom, zoom.dataset.caption);
  return true;
}

document.getElementById("photos-groups").addEventListener("click", async e => {
  if (checkZoomClick(e)) return;

  const compareId = e.target.closest("[data-compare]")?.dataset.compare;
  if (compareId) {
    const group = photoGroupsCache.find(g => g.duplicate_id === compareId);
    if (group) {
      // Nebeneinander passen nur bis zu 4 Bilder - bei mehr werden nur die
      // ersten 4 gezeigt (siehe Kommentar bei compareBtn oben).
      openLightboxCompare(group.assets.slice(0, 4).map(a => ({ id: a.id, caption: a.file_name })), compareId);
    }
    return;
  }

  const pageTo = e.target.closest("[data-page]")?.dataset.page;
  if (pageTo !== undefined) {
    await loadPhotosTab(parseInt(pageTo, 10));
    window.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }

  const card = e.target.closest(".photo-card");
  if (card) {
    const trashSet = photoTrash.get(card.dataset.group);
    // Unabhaengiges Umschalten NUR dieses einen Bilds - kein "genau eins
    // bleibt" mehr. Alle Bilder koennen einzeln in den Papierkorb, bis hin zu
    // allen oder keinem.
    trashSet.has(card.dataset.asset) ? trashSet.delete(card.dataset.asset) : trashSet.add(card.dataset.asset);
    updateGroupSelectionUI(card.dataset.group);
    return;
  }

  const selectAllId = e.target.closest("[data-select-all]")?.dataset.selectAll;
  if (selectAllId) {
    const group = photoGroupsCache.find(g => g.duplicate_id === selectAllId);
    photoTrash.set(selectAllId, new Set(group.assets.map(a => a.id)));
    updateGroupSelectionUI(selectAllId);
    // "Alle Papierkorb" heisst hier bewusst sofort anwenden, nicht nur
    // auswaehlen - wer den Knopf drueckt, hat die Entscheidung fuer die ganze
    // Gruppe schon getroffen und will nicht noch extra auf "Anwenden" klicken.
    await applyGroupTrash(selectAllId, true);
    return;
  }

  const selectNoneId = e.target.closest("[data-select-none]")?.dataset.selectNone;
  if (selectNoneId) {
    // "Alle behalten" heisst: mit dieser Gruppe gibt es nichts zu tun - genau
    // das drueckt Immichs Dismiss-Funktion aus (Gruppe nicht mehr als
    // Duplikat fuehren, nichts loeschen). Ohne das blieb die Gruppe nach
    // "alle behalten" einfach stehen, ohne dass es einen naechsten Schritt gab.
    await dismissGroup(selectNoneId);
    return;
  }

  const applyId = e.target.closest("[data-apply]")?.dataset.apply;
  if (applyId) {
    await applyGroupTrash(applyId);
    return;
  }

  const dismissId = e.target.closest("[data-dismiss]")?.dataset.dismiss;
  if (dismissId) {
    await dismissGroup(dismissId);
  }
});

// forceConfirm: "Alle Papierkorb" wirft die ganze Gruppe auf einmal weg und
// ist der Klick, bei dem Vertippen am teuersten ist (siehe Fehlklick-Fix oben)
// - dafür bleibt die Rückfrage IMMER bestehen, auch wenn "ohne Rückfrage"
// aktiviert ist. Die Einstellung gilt nur für bewusst manuell zusammengestellte
// Auswahl über die einzelnen Bild-Karten.
async function applyGroupTrash(duplicateId, forceConfirm = false) {
  const group = photoGroupsCache.find(g => g.duplicate_id === duplicateId);
  if (!group) return;
  const trashSet = photoTrash.get(duplicateId) || new Set();
  const trashIds = [...trashSet];
  const keepIds = group.assets.map(a => a.id).filter(id => !trashSet.has(id));
  if (!trashIds.length) return;
  const warnAll = keepIds.length === 0
    ? "\n\n⚠️ Es bleibt kein Bild dieser Gruppe übrig - alle wandern in den Papierkorb."
    : "";
  if ((forceConfirm || !immichSkipConfirm) &&
      !confirm(`${trashIds.length} Aufnahme(n) in den Papierkorb verschieben?${warnAll}\n\nSie bleiben in Immich wiederherstellbar.`)) return;
  try {
    const res = await api("/immich/duplicates/resolve", {
      method: "POST",
      body: JSON.stringify({ groups: [{ duplicate_id: duplicateId, keep_ids: keepIds, trash_ids: trashIds }] }),
    });
    toast(`${res.trashed_assets} Aufnahme(n) in den Papierkorb verschoben.`);
    removePhotoGroupLocally(duplicateId);
  } catch (err) {
    toast("Fehler: " + err.message);
  }
}

async function dismissGroup(duplicateId) {
  try {
    await api(`/immich/duplicates/${duplicateId}`, { method: "DELETE" });
    toast("Gruppe ausgeblendet, es wurde nichts gelöscht.");
    removePhotoGroupLocally(duplicateId);
  } catch (err) {
    toast("Fehler: " + err.message);
  }
}

// Entfernt eine erledigte Gruppe nur aus der aktuell angezeigten Seite, statt
// alle 20 Gruppen neu vom Server zu laden. Der Nutzer will bewusst auf dieser
// Seite bleiben, bis alle erledigt sind, und selbst entscheiden, wann er
// "Weitere laden" klickt - nicht nach jeder einzelnen Aktion einen kompletten
// Seiten-Neuaufbau erleben.
function removePhotoGroupLocally(duplicateId) {
  photoGroupsCache = photoGroupsCache.filter(g => g.duplicate_id !== duplicateId);
  photoTrash.delete(duplicateId);
  photoSuggestedKeep.delete(duplicateId);
  photoSimilarity.delete(duplicateId);
  document.querySelector(`.photo-group[data-group="${CSS.escape(duplicateId)}"]`)?.remove();

  const summary = document.getElementById("photos-summary");
  if (photoGroupsCache.length === 0) {
    summary.innerHTML = `Alle Gruppen dieser Seite sind erledigt. Auf "Weitere laden" klicken für mehr,
      oder <button type="button" class="link-btn" id="photos-reload-inline">neu laden</button>.`;
    document.getElementById("photos-reload-inline")?.addEventListener("click", () => loadPhotosTab(photoPage.offset));
  }
}

document.getElementById("photos-reload").addEventListener("click", () => loadPhotosTab());
document.getElementById("photos-goto-settings").addEventListener("click", () => {
  document.querySelector('.nav-btn[data-tab="settings"]').click();
});

// ---------- Alle Fotos (ungefiltert, nur Swipe-Modus) ----------
let allPhotosState = { offset: 0, hasMore: true, assets: [], trashEnabled: true };

async function loadAllPhotos(offset = 0) {
  let d;
  try {
    d = await api(`/immich/photos?offset=${offset}&limit=60&shuffle=true`);
  } catch (e) {
    toast("Fehler: " + e.message);
    allPhotosState = { ...allPhotosState, hasMore: false };
    return;
  }
  allPhotosState = { offset: d.offset, hasMore: d.has_more, assets: d.assets, trashEnabled: d.trash_enabled };
}

document.getElementById("photos-view-all").addEventListener("click", e => {
  if (checkZoomClick(e)) return;
  if (e.target.closest("[data-swipe-action]")) {
    commitSwipe("all", e.target.closest("[data-swipe-action]").dataset.swipeAction);
  }
});

// ---------- Screenshots ----------
const shotSelection = new Set();
let shotState = { months: 12, offset: 0, hasMore: false, assets: [], trashEnabled: true };

const SHOT_FILTERS = [
  { months: 0, label: "Alle" },
  { months: 6, label: "Älter als 6 Monate" },
  { months: 12, label: "Älter als 1 Jahr" },
  { months: 24, label: "Älter als 2 Jahre" },
];

document.getElementById("photos-subtabs").addEventListener("click", e => {
  const view = e.target.closest("[data-photos-view]")?.dataset.photosView;
  if (!view) return;
  document.querySelectorAll("#photos-subtabs .range-tab").forEach(b =>
    b.classList.toggle("active", b.dataset.photosView === view));
  document.getElementById("photos-view-duplicates").classList.toggle("hidden", view !== "duplicates");
  document.getElementById("photos-view-all").classList.toggle("hidden", view !== "all");
  document.getElementById("photos-view-screenshots").classList.toggle("hidden", view !== "screenshots");
  document.getElementById("photos-view-quality").classList.toggle("hidden", view !== "quality");
  document.getElementById("photos-view-people").classList.toggle("hidden", view !== "people");
  if (view === "screenshots" && !shotState.assets.length) loadScreenshots();
  if (view === "quality" && !qualityState.assets.length) loadQuality();
  if (view === "people" && !peopleCache.length) loadPeople();
  if (view === "all") {
    if (activeSwipeKind !== "all") enterSwipeMode("all");
  } else if (activeSwipeKind === "all") {
    activeSwipeKind = null;
  }
});

async function loadScreenshots(offset = 0) {
  const grid = document.getElementById("shots-grid");
  const summary = document.getElementById("shots-summary");
  grid.innerHTML = `<p class="page-sub">Suche Bildschirmfotos …</p>`;

  let d;
  try {
    d = await api(`/immich/screenshots?older_than_months=${shotState.months}&offset=${offset}&limit=60`);
  } catch (e) {
    grid.innerHTML = `<p class="page-sub">${esc(e.message)}</p>`;
    return;
  }

  shotState = { ...shotState, offset: d.offset, hasMore: d.has_more,
                assets: d.assets, trashEnabled: d.trash_enabled };
  // Auswahl beim Blättern/Filtern verwerfen - sonst würde man Bilder wegwerfen,
  // die man auf einer anderen Seite ausgewählt und längst vergessen hat.
  shotSelection.clear();

  document.getElementById("shot-filter").innerHTML = SHOT_FILTERS.map(f => {
    const n = f.months === 0 ? d.by_age.alle
      : (f.months === 6 ? d.by_age["6m"] : f.months === 12 ? d.by_age["1j"] : d.by_age["2j"]);
    return `<button type="button" class="range-tab ${f.months === shotState.months ? "active" : ""}"
             data-shot-months="${f.months}">${f.label} (${n})</button>`;
  }).join("");

  summary.classList.remove("hidden");
  const mb = (d.total_size_bytes / 1024 / 1024).toFixed(0);
  summary.innerHTML = d.total === 0
    ? `Keine Bildschirmfotos in diesem Zeitraum.`
    : `<strong>${d.total} Bildschirmfotos</strong> (${mb} MB) – angezeigt
       ${d.offset + 1}–${d.offset + d.assets.length}.
       ${d.trash_enabled
         ? `Ausgewählte wandern in Immichs Papierkorb, ${d.trash_days ? `${d.trash_days} Tage lang ` : ""}wiederherstellbar.`
         : `<span class="photos-warn">⚠️ Papierkorb in Immich abgeschaltet – Aufräumen ist gesperrt.</span>`}`;

  renderShots();
}

function renderShots() {
  const grid = document.getElementById("shots-grid");
  if (!shotState.assets.length) { grid.innerHTML = ""; document.getElementById("shots-pager").innerHTML = ""; return; }

  grid.innerHTML = shotState.assets.map(a => {
    const sel = shotSelection.has(a.id);
    return `<button type="button" class="shot-card ${sel ? "is-selected" : ""}" data-shot="${esc(a.id)}">
      <img loading="lazy" src="/api/immich/thumbnail/${esc(a.id)}" alt="">
      <span class="photo-zoom" data-zoom="${esc(a.id)}" data-caption="Bildschirmfoto" title="Vergrößern">🔍</span>
      <span class="shot-check">${sel ? "✓" : ""}</span>
      <span class="shot-meta">
        <span>${a.created_at ? fmtDate(a.created_at.slice(0, 10)) : ""}</span>
        <span>${formatBytes(a.size_bytes)}</span>
      </span>
    </button>`;
  }).join("");

  const selBytes = shotState.assets.filter(a => shotSelection.has(a.id))
    .reduce((s, a) => s + (a.size_bytes || 0), 0);
  const alleGewaehlt = shotSelection.size === shotState.assets.length;

  const pager = [];
  pager.push(`<button type="button" class="btn-ghost" data-shot-all="${alleGewaehlt ? "0" : "1"}">
    ${alleGewaehlt ? "Auswahl aufheben" : `Alle ${shotState.assets.length} auswählen`}</button>`);
  if (shotSelection.size && shotState.trashEnabled) {
    pager.push(`<button type="button" class="btn-primary" data-shot-trash="1">
      ${shotSelection.size} in den Papierkorb (${formatBytes(selBytes)})</button>`);
  }
  if (shotState.offset > 0) pager.push(`<button type="button" class="btn-ghost" data-shot-page="${Math.max(0, shotState.offset - 60)}">← Zurück</button>`);
  if (shotState.hasMore) pager.push(`<button type="button" class="btn-ghost" data-shot-page="${shotState.offset + 60}">Weitere →</button>`);
  document.getElementById("shots-pager").innerHTML = pager.join("");
}

document.getElementById("photos-view-screenshots").addEventListener("click", async e => {
  if (checkZoomClick(e)) return;
  if (e.target.closest("[data-swipe-toggle]")) {
    activeSwipeKind === "shot" ? exitSwipeMode("shot") : enterSwipeMode("shot");
    return;
  }
  if (e.target.closest("[data-swipe-action]")) {
    commitSwipe("shot", e.target.closest("[data-swipe-action]").dataset.swipeAction);
    return;
  }
  const months = e.target.closest("[data-shot-months]")?.dataset.shotMonths;
  if (months !== undefined) {
    shotState.months = parseInt(months, 10);
    await loadScreenshots(0);
    return;
  }
  const page = e.target.closest("[data-shot-page]")?.dataset.shotPage;
  if (page !== undefined) {
    await loadScreenshots(parseInt(page, 10));
    window.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  const card = e.target.closest("[data-shot]");
  if (card) {
    const id = card.dataset.shot;
    shotSelection.has(id) ? shotSelection.delete(id) : shotSelection.add(id);
    renderShots();
    return;
  }
  const all = e.target.closest("[data-shot-all]")?.dataset.shotAll;
  if (all !== undefined) {
    shotSelection.clear();
    if (all === "1") shotState.assets.forEach(a => shotSelection.add(a.id));
    renderShots();
    return;
  }
  if (e.target.closest("[data-shot-trash]")) {
    const ids = [...shotSelection];
    if (!immichSkipConfirm &&
        !confirm(`${ids.length} Bildschirmfoto(s) in den Papierkorb verschieben?\n\nSie bleiben in Immich wiederherstellbar.`)) return;
    try {
      const r = await api("/immich/screenshots/trash", {
        method: "POST", body: JSON.stringify({ asset_ids: ids }),
      });
      toast(`${r.trashed} verschoben, ${formatBytes(r.freed_bytes)} frei.`);
      await loadScreenshots(shotState.offset);
    } catch (err) {
      toast("Fehler: " + err.message);
    }
  }
});

// ---------- Unnötige Fotos (unscharf/leer) ----------
const qualitySelection = new Set();
let qualityState = { reason: "", offset: 0, hasMore: false, assets: [], trashEnabled: true, byReason: {} };

const QUALITY_FILTERS = [
  { reason: "", label: "Alle" },
  { reason: "blur", label: "Unscharf" },
  { reason: "blank", label: "Leer/einfarbig" },
];

async function loadQuality(offset = 0) {
  const grid = document.getElementById("quality-grid");
  const summary = document.getElementById("quality-summary");
  grid.innerHTML = `<p class="page-sub">Lade …</p>`;

  let d;
  try {
    d = await api(`/immich/quality?offset=${offset}&limit=60&reason=${encodeURIComponent(qualityState.reason)}`);
  } catch (e) {
    grid.innerHTML = `<p class="page-sub">${esc(e.message)}</p>`;
    return;
  }

  qualityState = { ...qualityState, offset: d.offset, hasMore: d.has_more,
                    assets: d.assets, trashEnabled: d.trash_enabled, byReason: d.by_reason };
  qualitySelection.clear();

  document.getElementById("quality-filter").innerHTML = QUALITY_FILTERS.map(f => {
    const n = f.reason === "" ? d.total : (d.by_reason[f.reason] || 0);
    return `<button type="button" class="range-tab ${f.reason === qualityState.reason ? "active" : ""}"
             data-quality-reason="${f.reason}">${f.label} (${n})</button>`;
  }).join("");

  summary.classList.remove("hidden");
  const mb = (d.total_size_bytes / 1024 / 1024).toFixed(0);
  summary.innerHTML = d.total === 0
    ? `Bisher keine unnötigen Fotos gefunden. Der Hintergrund-Scan hat die Bibliothek bis
       Seite ${d.scan_page} durchsucht und läuft alle paar Minuten weiter.`
    : `<strong>${d.total} unnötige Fotos</strong> (${mb} MB) – Scan-Fortschritt: Seite ${d.scan_page}.
       ${d.trash_enabled
         ? `Ausgewählte wandern in Immichs Papierkorb, ${d.trash_days ? `${d.trash_days} Tage lang ` : ""}wiederherstellbar.`
         : `<span class="photos-warn">⚠️ Papierkorb in Immich abgeschaltet – Aufräumen ist gesperrt.</span>`}`;

  renderQuality();
}

function renderQuality() {
  const grid = document.getElementById("quality-grid");
  if (!qualityState.assets.length) { grid.innerHTML = ""; document.getElementById("quality-pager").innerHTML = ""; return; }

  grid.innerHTML = qualityState.assets.map(a => {
    const sel = qualitySelection.has(a.id);
    const label = a.reason === "blur" ? "Unscharf" : "Leer";
    return `<button type="button" class="shot-card ${sel ? "is-selected" : ""}" data-quality="${esc(a.id)}">
      <img loading="lazy" src="/api/immich/thumbnail/${esc(a.id)}" alt="">
      ${videoBadgeHtml(a.type)}
      <span class="photo-zoom" data-zoom="${esc(a.id)}" data-caption="${esc(a.file_name || "")}" title="Vergrößern">🔍</span>
      <span class="shot-check">${sel ? "✓" : ""}</span>
      <span class="photo-badge" style="left:auto;right:8px;background:var(--warn)">${label}</span>
      <span class="shot-meta">
        <span>${a.created_at ? fmtDate(a.created_at.slice(0, 10)) : ""}</span>
        <span>${formatBytes(a.size_bytes)}</span>
      </span>
    </button>`;
  }).join("");

  const selBytes = qualityState.assets.filter(a => qualitySelection.has(a.id))
    .reduce((s, a) => s + (a.size_bytes || 0), 0);
  const alleGewaehlt = qualitySelection.size === qualityState.assets.length;

  const pager = [];
  pager.push(`<button type="button" class="btn-ghost" data-quality-all="${alleGewaehlt ? "0" : "1"}">
    ${alleGewaehlt ? "Auswahl aufheben" : `Alle ${qualityState.assets.length} auswählen`}</button>`);
  if (qualitySelection.size) {
    pager.push(`<button type="button" class="btn-ghost" data-quality-dismiss="1">
      ${qualitySelection.size} als okay behalten</button>`);
  }
  if (qualitySelection.size && qualityState.trashEnabled) {
    pager.push(`<button type="button" class="btn-primary" data-quality-trash="1">
      ${qualitySelection.size} in den Papierkorb (${formatBytes(selBytes)})</button>`);
  }
  if (qualityState.offset > 0) pager.push(`<button type="button" class="btn-ghost" data-quality-page="${Math.max(0, qualityState.offset - 60)}">← Zurück</button>`);
  if (qualityState.hasMore) pager.push(`<button type="button" class="btn-ghost" data-quality-page="${qualityState.offset + 60}">Weitere →</button>`);
  document.getElementById("quality-pager").innerHTML = pager.join("");
}

document.getElementById("photos-view-quality").addEventListener("click", async e => {
  if (checkZoomClick(e)) return;
  if (e.target.closest("[data-swipe-toggle]")) {
    activeSwipeKind === "quality" ? exitSwipeMode("quality") : enterSwipeMode("quality");
    return;
  }
  if (e.target.closest("[data-swipe-action]")) {
    commitSwipe("quality", e.target.closest("[data-swipe-action]").dataset.swipeAction);
    return;
  }

  const reason = e.target.closest("[data-quality-reason]")?.dataset.qualityReason;
  if (reason !== undefined) {
    qualityState.reason = reason;
    await loadQuality(0);
    return;
  }
  const page = e.target.closest("[data-quality-page]")?.dataset.qualityPage;
  if (page !== undefined) {
    await loadQuality(parseInt(page, 10));
    window.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  const card = e.target.closest("[data-quality]");
  if (card) {
    const id = card.dataset.quality;
    qualitySelection.has(id) ? qualitySelection.delete(id) : qualitySelection.add(id);
    renderQuality();
    return;
  }
  const all = e.target.closest("[data-quality-all]")?.dataset.qualityAll;
  if (all !== undefined) {
    qualitySelection.clear();
    if (all === "1") qualityState.assets.forEach(a => qualitySelection.add(a.id));
    renderQuality();
    return;
  }
  if (e.target.closest("[data-quality-dismiss]")) {
    const ids = [...qualitySelection];
    try {
      await Promise.all(ids.map(id => api(`/immich/quality/${id}`, { method: "DELETE" })));
      toast(`${ids.length} Foto(s) als okay markiert.`);
      await loadQuality(qualityState.offset);
    } catch (err) {
      toast("Fehler: " + err.message);
    }
    return;
  }
  if (e.target.closest("[data-quality-trash]")) {
    const ids = [...qualitySelection];
    if (!immichSkipConfirm &&
        !confirm(`${ids.length} Foto(s) in den Papierkorb verschieben?\n\nSie bleiben in Immich wiederherstellbar.`)) return;
    try {
      const r = await api("/immich/quality/trash", {
        method: "POST", body: JSON.stringify({ asset_ids: ids }),
      });
      toast(`${r.trashed} verschoben, ${formatBytes(r.freed_bytes)} frei.`);
      await loadQuality(qualityState.offset);
    } catch (err) {
      toast("Fehler: " + err.message);
    }
  }
});

// ---------- Swipe-Modus (Tinder-artig: rechts=behalten, links=Papierkorb) ----------
// Bewusst clientseitig auf der schon geladenen Seite (max. 60 Fotos) statt eigenem
// Backend-Endpunkt - Screenshots/Unnötige Fotos liefern ohnehin nur "Kandidat oder
// nicht", kein Rank-Algorithmus, den man serverseitig fortschreiben müsste.
const ICON_SWIPE = '<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16 3l4 4-4 4"/><path d="M20 7H4"/><path d="M8 21l-4-4 4-4"/><path d="M4 17h16"/></svg>';
const ICON_GRID = '<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="8" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/><rect x="13" y="13" width="8" height="8" rx="1.5"/></svg>';

const SWIPE_CONFIG = {
  shot: {
    containerId: "shot-swipe", gridId: "shots-grid", pagerId: "shots-pager",
    getState: () => shotState,
    loadPage: offset => loadScreenshots(offset),
    trashUrl: "/immich/screenshots/trash",
    keepOne: null, // "behalten" heisst hier nur: nicht anfassen, kein eigener Aufruf noetig
    caption: () => "Bildschirmfoto",
  },
  quality: {
    containerId: "quality-swipe", gridId: "quality-grid", pagerId: "quality-pager",
    getState: () => qualityState,
    loadPage: offset => loadQuality(offset),
    trashUrl: "/immich/quality/trash",
    keepOne: id => api(`/immich/quality/${id}`, { method: "DELETE" }),
    caption: a => (a.reason === "blur" ? "Unscharf" : "Leer/einfarbig"),
  },
  // Kein Grid/Pager - dieser Tab zeigt ausschliesslich den Swipe-Stack, ohne
  // Umschalt-Button (siehe photos-subtabs-Handler, der enterSwipeMode direkt
  // beim Reinklicken in den Tab aufruft statt erst auf einen Klick zu warten).
  all: {
    containerId: "all-swipe", gridId: null, pagerId: null,
    getState: () => allPhotosState,
    loadPage: offset => loadAllPhotos(offset),
    trashUrl: "/immich/photos/trash",
    keepOne: null,
    caption: () => "",
  },
};

let activeSwipeKind = null;
const swipeQueues = { shot: [], quality: [], all: [] };

function enterSwipeMode(kind) {
  activeSwipeKind = kind;
  const cfg = SWIPE_CONFIG[kind];
  swipeQueues[kind] = [...cfg.getState().assets];
  document.getElementById(cfg.gridId)?.classList.add("hidden");
  document.getElementById(cfg.pagerId)?.classList.add("hidden");
  document.getElementById(cfg.containerId).classList.remove("hidden");
  const toggleBtn = document.querySelector(`[data-swipe-toggle="${kind}"]`);
  if (toggleBtn) toggleBtn.innerHTML = ICON_GRID + " Rasteransicht";
  renderSwipeStack(kind);
}

function exitSwipeMode(kind) {
  activeSwipeKind = null;
  const cfg = SWIPE_CONFIG[kind];
  document.getElementById(cfg.gridId)?.classList.remove("hidden");
  document.getElementById(cfg.pagerId)?.classList.remove("hidden");
  document.getElementById(cfg.containerId).classList.add("hidden");
  const toggleBtn = document.querySelector(`[data-swipe-toggle="${kind}"]`);
  if (toggleBtn) toggleBtn.innerHTML = ICON_SWIPE + " Swipe-Modus";
}

function renderSwipeStack(kind) {
  const cfg = SWIPE_CONFIG[kind];
  const container = document.getElementById(cfg.containerId);
  const queue = swipeQueues[kind];

  if (!queue.length) {
    const st = cfg.getState();
    if (st.hasMore) {
      container.innerHTML = `<p class="swipe-done">Lade weitere …</p>`;
      cfg.loadPage(st.offset + 60).then(() => {
        if (activeSwipeKind !== kind) return;
        swipeQueues[kind] = [...cfg.getState().assets];
        renderSwipeStack(kind);
      });
      return;
    }
    container.innerHTML = `<p class="swipe-done">🎉 Alles durchgesehen.</p>`;
    return;
  }

  const top = queue[0];
  const next = queue[1];
  container.innerHTML = `
    <div class="swipe-progress">${queue.length} übrig</div>
    <div class="swipe-stack">
      ${next ? `<div class="swipe-card is-behind"><img src="/api/immich/thumbnail/${esc(next.id)}" alt="">${videoBadgeHtml(next.type)}</div>` : ""}
      <div class="swipe-card is-top" id="swipe-top-card" data-swipe-id="${esc(top.id)}">
        <span class="swipe-hint keep">Behalten</span>
        <span class="swipe-hint trash">Papierkorb</span>
        <img src="/api/immich/thumbnail/${esc(top.id)}" alt="" draggable="false">
        ${videoBadgeHtml(top.type)}
        <div class="swipe-card-meta">
          <span>${top.created_at ? fmtDate(top.created_at.slice(0, 10)) : ""}</span>
          <span>${cfg.caption(top)} · ${formatBytes(top.size_bytes)}</span>
        </div>
      </div>
    </div>
    <div class="swipe-actions">
      <button type="button" class="swipe-action-btn trash" data-swipe-action="trash" title="In den Papierkorb">✕</button>
      <button type="button" class="swipe-action-btn keep" data-swipe-action="keep" title="Behalten">✓</button>
    </div>`;

  attachSwipeDrag(kind);
}

function attachSwipeDrag(kind) {
  const card = document.getElementById("swipe-top-card");
  if (!card) return;
  const keepHint = card.querySelector(".swipe-hint.keep");
  const trashHint = card.querySelector(".swipe-hint.trash");
  let startX = 0, dx = 0, dragging = false;

  card.addEventListener("pointerdown", e => {
    dragging = true;
    dx = 0;
    card.classList.add("is-dragging");
    startX = e.clientX;
    card.setPointerCapture(e.pointerId);
  });
  card.addEventListener("pointermove", e => {
    if (!dragging) return;
    dx = e.clientX - startX;
    card.style.transform = `translateX(${dx}px) rotate(${dx / 18}deg)`;
    const strength = Math.min(Math.abs(dx) / 100, 1);
    keepHint.style.opacity = dx > 0 ? strength : 0;
    trashHint.style.opacity = dx < 0 ? strength : 0;
  });
  const release = () => {
    if (!dragging) return;
    dragging = false;
    card.classList.remove("is-dragging");
    if (Math.abs(dx) > 100) {
      commitSwipe(kind, dx > 0 ? "keep" : "trash");
    } else {
      card.classList.add("snap-back");
      card.style.transform = "";
      keepHint.style.opacity = 0;
      trashHint.style.opacity = 0;
    }
  };
  card.addEventListener("pointerup", release);
  card.addEventListener("pointercancel", release);
}

async function commitSwipe(kind, direction) {
  const cfg = SWIPE_CONFIG[kind];
  const card = document.getElementById("swipe-top-card");
  const id = card?.dataset.swipeId;
  if (!id) return;
  const flyX = direction === "keep" ? 700 : -700;
  card.classList.add("fly-out");
  card.style.transform = `translateX(${flyX}px) rotate(${direction === "keep" ? 20 : -20}deg)`;

  swipeQueues[kind].shift();
  setTimeout(() => { if (activeSwipeKind === kind) renderSwipeStack(kind); }, 220);

  try {
    if (direction === "trash") {
      await api(cfg.trashUrl, { method: "POST", body: JSON.stringify({ asset_ids: [id] }) });
    } else if (cfg.keepOne) {
      await cfg.keepOne(id);
    }
  } catch (err) {
    toast("Fehler: " + err.message);
  }
}

// ---------- Personen (Immichs Gesichtserkennung) ----------
let peopleCache = [];
let personSelection = new Set();
let personState = { id: null, name: "", page: 1, hasMore: false, assets: [], trashEnabled: true };

async function loadPeople() {
  const grid = document.getElementById("people-grid");
  grid.innerHTML = `<p class="page-sub">Lade Personen …</p>`;
  try {
    const d = await api("/immich/people");
    peopleCache = d.people;
  } catch (e) {
    grid.innerHTML = `<p class="page-sub">${esc(e.message)}</p>`;
    return;
  }
  if (!peopleCache.length) {
    grid.innerHTML = `<p class="page-sub">Immich hat noch keine benannten Personen erkannt.</p>`;
    return;
  }
  grid.innerHTML = peopleCache.map(p => `
    <button type="button" class="shot-card" data-person="${esc(p.id)}">
      <img loading="lazy" src="/api/immich/people/${esc(p.id)}/thumbnail" alt="">
      <span class="shot-meta">
        <span>${esc(p.name)}</span>
        <span>${p.asset_count} Fotos</span>
      </span>
    </button>`).join("");
}

async function loadPersonAssets(page = 1) {
  const grid = document.getElementById("person-grid");
  const summary = document.getElementById("person-summary");
  grid.innerHTML = `<p class="page-sub">Lade Fotos …</p>`;

  let d;
  try {
    d = await api(`/immich/people/${personState.id}/assets?page=${page}`);
  } catch (e) {
    grid.innerHTML = `<p class="page-sub">${esc(e.message)}</p>`;
    return;
  }
  personState = { ...personState, page: d.page, hasMore: d.has_more, assets: d.assets, trashEnabled: d.trash_enabled };
  personSelection.clear();
  summary.classList.remove("hidden");
  summary.innerHTML = `Seite ${d.page}.
    ${d.trash_enabled
      ? `Ausgewählte wandern in Immichs Papierkorb, wiederherstellbar.`
      : `<span class="photos-warn">⚠️ Papierkorb in Immich abgeschaltet – Aufräumen ist gesperrt.</span>`}`;
  renderPersonAssets();
}

function renderPersonAssets() {
  const grid = document.getElementById("person-grid");
  if (!personState.assets.length) { grid.innerHTML = `<p class="page-sub">Keine Fotos auf dieser Seite.</p>`; document.getElementById("person-pager").innerHTML = ""; return; }

  grid.innerHTML = personState.assets.map(a => {
    const sel = personSelection.has(a.id);
    return `<button type="button" class="shot-card ${sel ? "is-selected" : ""}" data-person-asset="${esc(a.id)}">
      <img loading="lazy" src="/api/immich/thumbnail/${esc(a.id)}" alt="">
      <span class="photo-zoom" data-zoom="${esc(a.id)}" data-caption="${esc(a.file_name || "")}" title="Vergrößern">🔍</span>
      <span class="shot-check">${sel ? "✓" : ""}</span>
      <span class="shot-meta">
        <span>${a.created_at ? fmtDate(a.created_at.slice(0, 10)) : ""}</span>
        <span>${formatBytes(a.size_bytes)}</span>
      </span>
    </button>`;
  }).join("");

  const pager = [];
  if (personSelection.size && personState.trashEnabled) {
    pager.push(`<button type="button" class="btn-primary" data-person-trash="1">
      ${personSelection.size} in den Papierkorb</button>`);
  }
  if (personState.page > 1) pager.push(`<button type="button" class="btn-ghost" data-person-page="${personState.page - 1}">← Zurück</button>`);
  if (personState.hasMore) pager.push(`<button type="button" class="btn-ghost" data-person-page="${personState.page + 1}">Weitere →</button>`);
  document.getElementById("person-pager").innerHTML = pager.join("");
}

document.getElementById("photos-view-people").addEventListener("click", async e => {
  if (checkZoomClick(e)) return;

  const personId = e.target.closest("[data-person]")?.dataset.person;
  if (personId) {
    const person = peopleCache.find(p => p.id === personId);
    personState = { id: personId, name: person?.name || "", page: 1, hasMore: false, assets: [], trashEnabled: true };
    document.getElementById("person-detail-title").textContent = `🙂 ${person?.name || ""}`;
    document.getElementById("person-detail").classList.remove("hidden");
    document.getElementById("people-grid").classList.add("hidden");
    await loadPersonAssets(1);
    return;
  }
  if (e.target.closest("#person-back")) {
    document.getElementById("person-detail").classList.add("hidden");
    document.getElementById("people-grid").classList.remove("hidden");
    return;
  }
  const page = e.target.closest("[data-person-page]")?.dataset.personPage;
  if (page !== undefined) {
    await loadPersonAssets(parseInt(page, 10));
    window.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  const card = e.target.closest("[data-person-asset]");
  if (card) {
    const id = card.dataset.personAsset;
    personSelection.has(id) ? personSelection.delete(id) : personSelection.add(id);
    renderPersonAssets();
    return;
  }
  if (e.target.closest("[data-person-trash]")) {
    const ids = [...personSelection];
    if (!immichSkipConfirm &&
        !confirm(`${ids.length} Foto(s) in den Papierkorb verschieben?\n\nSie bleiben in Immich wiederherstellbar.`)) return;
    try {
      const r = await api(`/immich/people/${personState.id}/trash`, {
        method: "POST", body: JSON.stringify({ asset_ids: ids }),
      });
      toast(`${r.trashed} verschoben, ${formatBytes(r.freed_bytes)} frei.`);
      await loadPersonAssets(personState.page);
    } catch (err) {
      toast("Fehler: " + err.message);
    }
  }
});


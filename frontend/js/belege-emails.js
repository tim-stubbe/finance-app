// ================= BELEGE AUS E-MAILS =================
async function loadMailSettings() {
  const s = await api("/settings/mail");
  document.getElementById("mail-host").value = s.host || "";
  document.getElementById("mail-port").value = s.port || 993;
  document.getElementById("mail-user").value = s.user || "";
  document.getElementById("mail-folder").value = s.folder || "INBOX";
  document.getElementById("mail-enabled").checked = s.enabled;
  document.getElementById("mail-remove").classList.toggle("hidden", !s.host);
  document.getElementById("mail-password").placeholder = s.password_set
    ? "gespeichert – leer lassen behält das bisherige"
    : "wird verschlüsselt gespeichert";
  if (s.last_sync_at) {
    document.getElementById("mail-status").textContent =
      "Zuletzt abgeholt: " + relativeTimeDe(new Date(s.last_sync_at));
  }
}

document.getElementById("mail-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const pw = document.getElementById("mail-password").value.trim();
  const body = {
    enabled: document.getElementById("mail-enabled").checked,
    host: document.getElementById("mail-host").value.trim(),
    port: parseInt(document.getElementById("mail-port").value, 10) || 993,
    user: document.getElementById("mail-user").value.trim(),
    folder: document.getElementById("mail-folder").value.trim() || "INBOX",
  };
  if (pw) body.password = pw;
  await api("/settings/mail", { method: "PUT", body: JSON.stringify(body) });
  document.getElementById("mail-password").value = "";
  toast("Postfach-Einstellungen gespeichert.");
  await loadMailSettings();
  refreshIntegrationBadge();
});

document.getElementById("mail-test").addEventListener("click", async () => {
  const el = document.getElementById("mail-status");
  el.textContent = "Teste Verbindung …";
  const r = await api("/mail/test", { method: "POST" });
  el.textContent = r.ok
    ? `✓ Verbunden – Ordner „${r.folder}" mit ${r.message_count} Nachrichten.`
    : `✗ ${r.error}`;
});

document.getElementById("mail-sync-now").addEventListener("click", async () => {
  const el = document.getElementById("mail-status");
  el.textContent = "Hole Anhänge … (kann bei vielen Mails dauern)";
  try {
    const r = await api("/mail/sync", { method: "POST" });
    el.textContent = `${r.new_attachments} neue Anhänge, davon ${r.auto_attached} automatisch zugeordnet. ${r.skipped} schon bekannt.`;
    toast(`${r.new_attachments} neue Belege geholt.`);
    await loadMailInbox();
  } catch (err) {
    el.textContent = "✗ " + err.message;
  }
});

document.getElementById("mail-remove").addEventListener("click", async () => {
  if (!confirm("Postfach-Verbindung entfernen?")) return;
  await api("/settings/mail", { method: "DELETE" });
  toast("Postfach-Verbindung entfernt.");
  await loadMailSettings();
  refreshIntegrationBadge();
});

async function loadCreditCardSettings() {
  if (!accountsCache.length) accountsCache = await api("/accounts");
  if (!debtsCache.length) debtsCache = await api("/debts");
  const select = document.getElementById("creditcard-account-select");
  select.innerHTML = '<option value="">– auswählen –</option>' +
    accountsCache.map(a => `<option value="acc:${a.id}">${esc(a.name)} (Konto)</option>`).join("") +
    debtsCache.map(d => `<option value="debt:${d.id}">${esc(d.name)} (Schuld)</option>`).join("");
  const s = await api("/settings/creditcard");
  document.getElementById("creditcard-mail-sender").value = s.mail_sender || "";
  select.value = s.account_id ? `acc:${s.account_id}` : s.debt_id ? `debt:${s.debt_id}` : "";
}

document.getElementById("creditcard-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const sel = document.getElementById("creditcard-account-select").value;
  const [kind, id] = sel ? sel.split(":") : [null, null];
  const body = {
    mail_sender: document.getElementById("creditcard-mail-sender").value.trim(),
    account_id: kind === "acc" ? parseInt(id, 10) : null,
    debt_id: kind === "debt" ? parseInt(id, 10) : null,
  };
  await api("/settings/creditcard", { method: "PUT", body: JSON.stringify(body) });
  toast("Kreditkarten-Einstellungen gespeichert.");
});

// ---------- Beleg-Eingang ----------
async function loadDuplicateTransactions() {
  const panel = document.getElementById("dup-tx-panel");
  let groups = [];
  try {
    groups = await api("/transactions/duplicates");
  } catch (e) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.toggle("hidden", groups.length === 0);
  document.getElementById("dup-tx-count").textContent = groups.length;
  if (!groups.length) return;

  document.getElementById("dup-tx-list").innerHTML = groups.map((g, i) => `
    <div class="mail-item">
      <div>
        <strong>${g.transaction_ids.length}× ${esc(g.description || "(ohne Beschreibung)")}</strong><br>
        <span class="page-sub">${esc(g.account_name)} · ${fmtDate(g.date)} · ${eur(g.amount)}</span>
      </div>
      <button type="button" class="btn-ghost" data-dup-resolve="${i}">
        ${g.transaction_ids.length - 1} überzählige löschen (behält eine)
      </button>
    </div>`).join("");

  document.querySelectorAll("[data-dup-resolve]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const g = groups[parseInt(btn.dataset.dupResolve, 10)];
      const toDelete = g.transaction_ids.slice(1);
      if (!confirm(`${toDelete.length} doppelte Buchung(en) löschen? Die erste bleibt erhalten.`)) return;
      btn.disabled = true;
      for (const id of toDelete) {
        try { await api(`/transactions/${id}`, { method: "DELETE" }); } catch { /* einzelne fehlgeschlagene Loeschung nicht die ganze Aktion abbrechen lassen */ }
      }
      toast(`${toDelete.length} doppelte Buchung(en) gelöscht.`);
      await loadDuplicateTransactions();
      await loadTransactions();
    });
  });
}

async function loadMailInbox() {
  const panel = document.getElementById("mail-inbox-panel");
  const list = document.getElementById("mail-inbox-list");
  let items = [];
  try {
    items = await api("/mail/attachments?status=pending");
  } catch (e) {
    panel.classList.add("hidden");
    return;
  }
  // Panel nur zeigen, wenn wirklich etwas offen ist - sonst nimmt es im
  // Buchungen-Tab dauerhaft Platz weg.
  panel.classList.toggle("hidden", items.length === 0);
  document.getElementById("mail-inbox-count").textContent = items.length;
  if (!items.length) return;

  // Absicherung gegen den seltenen Fall, dass der Beleg-Eingang gerendert
  // wird, bevor die Start-Ladung von Konten/Kategorien durch ist - sonst
  // stünden leere Auswahlfelder im "neue Buchung"-Formular.
  if (!accountsCache.length) accountsCache = await api("/accounts");
  if (!categoriesCache.length) categoriesCache = await api("/categories");

  const kontoOptions = accountsCache.map(k => `<option value="${k.id}">${esc(k.name)}</option>`).join("");
  const katOptions = categoriesCache.map(k => `<option value="${k.id}">${esc(k.name)}</option>`).join("");

  list.innerHTML = items.map(a => {
    const erkannt = a.parsed_date && a.parsed_amount
      ? `erkannt: ${fmtDate(a.parsed_date)} · ${eur(a.parsed_amount)}`
      : `<span class="mail-warn">nicht auslesbar${a.parse_error ? ` (${esc(a.parse_error)})` : ""}</span>`;
    const vorschlaege = a.suggestions.length
      ? a.suggestions.map(s => `<button type="button" class="btn-primary mail-suggest"
           data-attach="${a.id}" data-tx="${s.id}">An ${fmtDate(s.date)} · ${eur(s.amount)} anhängen</button>`).join("")
      : "";
    // Kein Treffer heisst nicht zwangsläufig "es gibt keine Buchung" - der
    // Kontoumsatz kann einfach noch nicht importiert sein. Dafür direkt hier
    // eine neue Buchung anlegen können, statt den Beleg erst wegzulegen und
    // später wiederzufinden.
    const neueBuchung = `
      <details class="mail-new-tx">
        <summary class="btn-ghost">${a.suggestions.length ? "Stattdessen neue Buchung" : "Keine passende Buchung – neu anlegen"}</summary>
        <form class="form-grid mail-new-tx-form" data-new-tx="${a.id}">
          <label>Datum <input type="date" name="date" value="${esc(a.parsed_date || "")}" required></label>
          <label>Betrag <input type="number" step="0.01" name="amount" value="${a.parsed_amount ?? ""}" required></label>
          <label>Konto <select name="account_id" required>${kontoOptions}</select></label>
          <label>Kategorie <select name="category_id"><option value="">–</option>${katOptions}</select></label>
          <label class="wide">Beschreibung <input type="text" name="description" value="${esc(a.subject || a.filename)}"></label>
          <div class="form-actions"><button type="submit" class="btn-primary">Buchung anlegen &amp; Beleg anhängen</button></div>
        </form>
      </details>`;
    return `<div class="mail-item">
      <div class="mail-item-main">
        <a href="/api/receipts/${esc(a.stored_filename)}" target="_blank" rel="noopener" class="mail-file">${esc(a.filename)}</a>
        <span class="mail-meta">${esc(a.sender || "")} · ${esc(a.subject || "")}</span>
        <span class="mail-meta">${erkannt}</span>
        ${neueBuchung}
      </div>
      <div class="mail-item-actions">
        ${vorschlaege}
        <button type="button" class="btn-ghost" data-ignore="${a.id}">Ablegen</button>
      </div>
    </div>`;
  }).join("");
}

document.getElementById("mail-inbox-list").addEventListener("submit", async e => {
  const form = e.target.closest("[data-new-tx]");
  if (!form) return;
  e.preventDefault();
  const fd = new FormData(form);
  const body = {
    account_id: parseInt(fd.get("account_id"), 10),
    category_id: fd.get("category_id") ? parseInt(fd.get("category_id"), 10) : null,
    date: fd.get("date"),
    amount: parseFloat(fd.get("amount")),
    description: fd.get("description") || null,
  };
  try {
    await api(`/mail/attachments/${form.dataset.newTx}/create-transaction`, {
      method: "POST", body: JSON.stringify(body),
    });
    toast("Buchung angelegt, Beleg angehängt.");
    await loadMailInbox();
    await loadTransactions();
  } catch (err) {
    toast("Fehler: " + err.message);
  }
});

document.getElementById("mail-inbox-list").addEventListener("click", async e => {
  const attach = e.target.closest("[data-attach]");
  if (attach) {
    await api(`/mail/attachments/${attach.dataset.attach}/attach`, {
      method: "POST", body: JSON.stringify({ transaction_id: parseInt(attach.dataset.tx, 10) }),
    });
    toast("Beleg an Buchung angehängt.");
    await loadMailInbox();
    await loadTransactions();
    return;
  }
  const ign = e.target.closest("[data-ignore]");
  if (ign) {
    await api(`/mail/attachments/${ign.dataset.ignore}/ignore`, { method: "POST" });
    toast("Beleg abgelegt.");
    await loadMailInbox();
  }
});

// ---------- Immich-Einstellungen ----------
// Global gemerkt, damit die Papierkorb-Handler im Fotos-Tab nicht bei jedem
// Klick erst die Einstellungen nachladen müssen.
let immichSkipConfirm = false;

async function loadImmichSettings() {
  const s = await api("/settings/immich");
  document.getElementById("immich-url").value = s.url || "";
  document.getElementById("immich-remove").classList.toggle("hidden", !s.url && !s.api_key_set);
  document.getElementById("immich-api-key").placeholder = s.api_key_set
    ? "gespeichert – leer lassen behält den bisherigen"
    : "wird verschlüsselt gespeichert";
  document.getElementById("immich-skip-confirm").checked = s.skip_confirm;
  immichSkipConfirm = s.skip_confirm;
}

document.getElementById("immich-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const url = document.getElementById("immich-url").value.trim();
  if (!url) return;
  const keyInput = document.getElementById("immich-api-key");
  const body = { url, skip_confirm: document.getElementById("immich-skip-confirm").checked };
  if (keyInput.value.trim()) body.api_key = keyInput.value.trim();
  await api("/settings/immich", { method: "PUT", body: JSON.stringify(body) });
  keyInput.value = "";
  toast("Immich-Einstellungen gespeichert.");
  await loadImmichSettings();
  refreshIntegrationBadge();
});

document.getElementById("immich-test").addEventListener("click", async () => {
  const statusEl = document.getElementById("immich-status");
  statusEl.textContent = "Teste Verbindung …";
  const r = await api("/immich/test", { method: "POST" });
  statusEl.textContent = r.ok
    ? `✓ Verbunden mit Immich ${r.version} – ${r.duplicate_groups} Duplikatgruppe(n) gefunden.`
    : `✗ ${r.error}`;
});

document.getElementById("immich-remove").addEventListener("click", async () => {
  if (!confirm("Immich-Verbindung entfernen?")) return;
  await api("/settings/immich", { method: "DELETE" });
  document.getElementById("immich-status").textContent = "";
  toast("Immich-Verbindung entfernt.");
  await loadImmichSettings();
  refreshIntegrationBadge();
});


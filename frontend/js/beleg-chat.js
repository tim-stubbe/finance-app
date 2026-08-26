// ================= BELEG-CHAT =================
let belegChatHistory = [];

function appendChatBubble(role, text, logId = "beleg-chat-log") {
  const log = document.getElementById(logId);
  const div = document.createElement("div");
  div.className = `chat-msg ${role}`;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function showChatTyping(logId = "beleg-chat-log") {
  const log = document.getElementById(logId);
  const div = document.createElement("div");
  div.className = "chat-typing";
  div.id = `${logId}-typing`;
  div.innerHTML = "<span></span><span></span><span></span>";
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function hideChatTyping(logId = "beleg-chat-log") {
  document.getElementById(`${logId}-typing`)?.remove();
}

function renderBelegProposal(proposal, attachmentFilename, attachmentBase64, logId = "beleg-chat-log") {
  const wrap = document.createElement("div");
  wrap.className = "beleg-proposal";

  if (proposal.type === "update_category" || proposal.type === "mark_transfer") {
    const match = proposal.resolved_transaction;
    if (!match) {
      wrap.innerHTML = `
        <h4>${proposal.type === "mark_transfer" ? "Vorschlag: Als Umbuchung markieren" : "Vorschlag: Kategorie setzen"}</h4>
        <p class="beleg-warning">⚠️ ${esc(proposal.resolution_error || "Buchung konnte nicht eindeutig zugeordnet werden.")}</p>`;
      const log = document.getElementById(logId);
      log.appendChild(wrap);
      log.scrollTop = log.scrollHeight;
      return;
    }
    const label = proposal.type === "mark_transfer"
      ? "als Umbuchung markieren (zählt dann nicht mehr als Einnahme/Ausgabe)"
      : `Kategorie auf „${esc(proposal.category ?? "")}“ setzen`;
    wrap.innerHTML = `
      <h4>${proposal.type === "mark_transfer" ? "Vorschlag: Als Umbuchung markieren" : "Vorschlag: Kategorie setzen"}</h4>
      <p class="goal-meta">${fmtDate(match.date)} · ${eur(match.amount)} · ${esc(match.description || "ohne Beschreibung")}</p>
      <p>${label}</p>
      <div class="form-actions">
        <button type="button" class="btn-primary" data-action="apply">Übernehmen</button>
        <button type="button" class="btn-ghost" data-action="discard">Verwerfen</button>
      </div>`;
    const log = document.getElementById(logId);
    log.appendChild(wrap);
    log.scrollTop = log.scrollHeight;
    wrap.querySelector('[data-action="discard"]').addEventListener("click", () => wrap.remove());
    wrap.querySelector('[data-action="apply"]').addEventListener("click", async () => {
      const body = {
        type: proposal.type,
        data: proposal.type === "mark_transfer"
          ? { transaction_id: match.id }
          : { transaction_id: match.id, category: proposal.category },
      };
      try {
        const result = await api("/ai/beleg-chat/apply", { method: "POST", body: JSON.stringify(body) });
        wrap.classList.add("applied");
        wrap.querySelectorAll("button").forEach(el => { el.disabled = true; });
        appendChatBubble("assistant", "✅ " + result.message, logId);
        await loadTransactions();
        await loadGlobalTopbar();
      } catch (e) {
        // api() zeigt den Fehler bereits per alert() an
      }
    });
    return;
  }

  if (proposal.type === "create_debt") {
    const accOptionsDebt = [`<option value="">– kein Konto –</option>`]
      .concat(accountsCache.map(a => `<option value="${a.id}" ${a.id === proposal.resolved_account_id ? "selected" : ""}>${a.name}</option>`))
      .join("");
    const payments = proposal.payments || [];
    const paymentRows = payments.map((p, i) => `
      <div class="beleg-proposal-payment" data-payment-row="${i}">
        <label>Datum <input type="date" data-pay-field="date" value="${p.date || ""}"></label>
        <label>Betrag (€) <input type="number" step="0.01" data-pay-field="total_amount" value="${p.total_amount ?? ""}"></label>
        <label>davon Zinsen (€) <input type="number" step="0.01" data-pay-field="interest_amount" value="${p.interest_amount ?? ""}" placeholder="automatisch"></label>
        <p class="goal-meta">${p.resolved_transaction_label
          ? "✅ verknüpft mit Buchung: " + esc(p.resolved_transaction_label)
          : "⚠️ keine passende Buchung gefunden – wird ohne Verknüpfung angelegt"}</p>
      </div>`).join("") || "<p class=\"goal-meta\">Keine bereits geleisteten Zahlungen.</p>";
    wrap.innerHTML = `
      <h4>Vorschlag: Schuld/Ratenkauf</h4>
      ${proposal.account_description && !proposal.resolved_account_id
        ? `<p class="beleg-warning">⚠️ Konto „${esc(proposal.account_description)}“ nicht eindeutig gefunden – bitte manuell wählen.</p>` : ""}
      <div class="form-grid">
        <label class="wide">Name <input type="text" data-field="name" value="${esc(proposal.name ?? "")}"></label>
        <label>Gläubiger <input type="text" data-field="lender" value="${esc(proposal.lender ?? "")}"></label>
        <label>Konto <select data-field="account_id">${accOptionsDebt}</select></label>
        <label>Finanzierter Betrag (€) <input type="number" step="0.01" data-field="original_amount" value="${proposal.original_amount ?? ""}"></label>
        <label>Zinssatz (% p.a.) <input type="number" step="0.01" data-field="interest_rate_percent" value="${proposal.interest_rate_percent ?? ""}"></label>
        <label>Monatliche Rate (€) <input type="number" step="0.01" data-field="monthly_payment" value="${proposal.monthly_payment ?? ""}"></label>
        <label>Start <input type="date" data-field="start_date" value="${proposal.start_date || ""}"></label>
        <label>Geplantes Ende <input type="date" data-field="planned_end_date" value="${proposal.planned_end_date || ""}"></label>
        <label class="wide">Notizen <input type="text" data-field="notes" value="${esc(proposal.notes ?? "")}"></label>
      </div>
      <h5>Bereits geleistete Zahlungen</h5>
      ${paymentRows}
      <div class="form-actions">
        <button type="button" class="btn-primary" data-action="apply">Schuld anlegen</button>
        <button type="button" class="btn-ghost" data-action="discard">Verwerfen</button>
      </div>`;
    const log = document.getElementById(logId);
    log.appendChild(wrap);
    log.scrollTop = log.scrollHeight;
    wrap.querySelector('[data-action="discard"]').addEventListener("click", () => wrap.remove());
    wrap.querySelector('[data-action="apply"]').addEventListener("click", async () => {
      const fields = {};
      wrap.querySelectorAll("[data-field]").forEach(el => { fields[el.dataset.field] = el.value; });
      const editedPayments = Array.from(wrap.querySelectorAll("[data-payment-row]")).map((row, i) => {
        const pf = {};
        row.querySelectorAll("[data-pay-field]").forEach(el => { pf[el.dataset.payField] = el.value; });
        return {
          date: pf.date, total_amount: pf.total_amount,
          interest_amount: pf.interest_amount || null,
          resolved_transaction_id: payments[i]?.resolved_transaction_id ?? null,
          notes: payments[i]?.notes ?? null,
        };
      });
      const body = {
        type: "create_debt",
        data: {
          ...fields,
          resolved_account_id: fields.account_id ? parseInt(fields.account_id) : null,
          payments: editedPayments,
        },
      };
      try {
        const result = await api("/ai/beleg-chat/apply", { method: "POST", body: JSON.stringify(body) });
        wrap.classList.add("applied");
        wrap.querySelectorAll("button, input, select").forEach(el => { el.disabled = true; });
        appendChatBubble("assistant", "✅ " + result.message, logId);
      } catch (e) {
        // api() zeigt den Fehler bereits per alert() an
      }
    });
    return;
  }

  if (proposal.type === "transaction") {
    const accOptions = accountsCache.map(a => `<option value="${a.id}">${a.name}</option>`).join("");
    const dupWarning = (proposal.duplicate_matches || []).length
      ? `<p class="beleg-warning">⚠️ Ähnliche Buchung bereits vorhanden: ${proposal.duplicate_matches.map(m =>
          `${fmtDate(m.date)}, ${eur(m.amount)}${m.description ? " – " + m.description : ""}`).join("; ")}</p>`
      : "";
    const receiptMatchBlock = (proposal.receipt_matches || []).length
      ? `<div class="beleg-receipt-match">
           <p>📎 Passt evtl. zu einer bestehenden Buchung ohne Beleg – statt einer neuen Buchung stattdessen nur den Beleg anhängen?</p>
           ${proposal.receipt_matches.map(m => `
             <button type="button" class="btn-ghost" data-action="attach-receipt" data-tx-id="${m.id}">
               An Buchung vom ${fmtDate(m.date)} über ${eur(m.amount)}${m.description ? " (" + m.description + ")" : ""} anhängen
             </button>`).join("")}
         </div>`
      : "";
    wrap.innerHTML = `
      <h4>Vorschlag: Buchung</h4>
      ${dupWarning}
      <div class="form-grid">
        <label>Datum <input type="date" data-field="date" value="${proposal.date || ""}"></label>
        <label>Betrag (€) <input type="number" step="0.01" data-field="amount" value="${proposal.amount ?? ""}"></label>
        <label class="wide">Beschreibung <input type="text" data-field="description" value="${proposal.description ?? ""}"></label>
        <label>Konto <select data-field="account_id">${accOptions}</select></label>
      </div>
      <div class="form-actions">
        <button type="button" class="btn-primary" data-action="apply">Als neue Buchung übernehmen</button>
        <button type="button" class="btn-ghost" data-action="discard">Verwerfen</button>
      </div>
      ${receiptMatchBlock}`;
  } else if (proposal.type === "holding_lot") {
    const assetTypes = ["aktie", "etf", "anleihe", "krypto", "sonstiges"];
    const assetOptions = assetTypes.map(a => `<option value="${a}" ${a === proposal.asset_type ? "selected" : ""}>${a}</option>`).join("");
    const lotOptions = Object.keys(LOT_TYPE_LABELS).map(t => `<option value="${t}" ${t === proposal.lot_type ? "selected" : ""}>${LOT_TYPE_LABELS[t]}</option>`).join("");
    wrap.innerHTML = `
      <h4>Vorschlag: Investment-Position</h4>
      <div class="form-grid">
        <label>Anlageklasse <select data-field="asset_type">${assetOptions}</select></label>
        <label>Typ <select data-field="lot_type">${lotOptions}</select></label>
        <label>Name <input type="text" data-field="name" value="${proposal.name ?? ""}"></label>
        <label>Symbol <input type="text" data-field="symbol" value="${proposal.symbol ?? ""}"></label>
        <label>Datum <input type="date" data-field="date" value="${proposal.date || ""}"></label>
        <label>Stückzahl <input type="number" step="0.00000001" data-field="quantity" value="${proposal.quantity ?? ""}"></label>
        <label>Preis/Stück (€) <input type="number" step="0.0001" data-field="price_per_unit" value="${proposal.price_per_unit ?? ""}"></label>
      </div>
      <div class="form-actions">
        <button type="button" class="btn-primary" data-action="apply">Übernehmen</button>
        <button type="button" class="btn-ghost" data-action="discard">Verwerfen</button>
      </div>`;
  } else {
    return;
  }

  const log = document.getElementById(logId);
  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;

  wrap.querySelector('[data-action="discard"]').addEventListener("click", () => wrap.remove());
  wrap.querySelector('[data-action="apply"]').addEventListener("click", async () => {
    const fields = {};
    wrap.querySelectorAll("[data-field]").forEach(el => { fields[el.dataset.field] = el.value; });
    const body = { type: proposal.type, data: fields };
    if (proposal.type === "transaction") {
      body.account_id = parseInt(fields.account_id);
      delete fields.account_id;
      body.attachment_filename = attachmentFilename || null;
      body.attachment_base64 = attachmentBase64 || null;
    }
    try {
      const result = await api("/ai/beleg-chat/apply", { method: "POST", body: JSON.stringify(body) });
      wrap.classList.add("applied");
      wrap.querySelectorAll("button, input, select").forEach(el => { el.disabled = true; });
      appendChatBubble("assistant", "✅ " + result.message, logId);
      if (proposal.type === "transaction") { await loadTransactions(); await loadGlobalTopbar(); }
      if (proposal.type === "holding_lot") await loadInvestmentsTab();
    } catch (e) {
      // api() zeigt den Fehler bereits per alert() an
    }
  });

  wrap.querySelectorAll('[data-action="attach-receipt"]').forEach(btn => {
    btn.addEventListener("click", async () => {
      const body = {
        type: "attach_receipt",
        data: { transaction_id: parseInt(btn.dataset.txId) },
        attachment_filename: attachmentFilename || null,
        attachment_base64: attachmentBase64 || null,
      };
      try {
        const result = await api("/ai/beleg-chat/apply", { method: "POST", body: JSON.stringify(body) });
        wrap.classList.add("applied");
        wrap.querySelectorAll("button, input, select").forEach(el => { el.disabled = true; });
        appendChatBubble("assistant", "✅ " + result.message, logId);
        await loadTransactions();
      } catch (e) {
        // api() zeigt den Fehler bereits per alert() an
      }
    });
  });
}

document.getElementById("beleg-chat-form").addEventListener("submit", async e => {
  e.preventDefault();
  const msgInput = document.getElementById("beleg-chat-message");
  const fileInput = document.getElementById("beleg-chat-file");
  const message = msgInput.value.trim();
  const file = fileInput.files[0];
  if (!message && !file) return;
  if (!accountsCache.length) await loadAccounts();

  appendChatBubble("user", message || `📎 ${file.name}`);
  const statusEl = document.getElementById("beleg-chat-status");
  const sendBtn = document.getElementById("beleg-chat-send");
  statusEl.textContent = "";
  sendBtn.disabled = true;
  showChatTyping("beleg-chat-log");

  const fd = new FormData();
  fd.append("message", message);
  fd.append("history", JSON.stringify(belegChatHistory));
  if (file) fd.append("file", file);

  try {
    const result = await api("/ai/beleg-chat", { method: "POST", body: fd });
    hideChatTyping("beleg-chat-log");
    if (result.error) {
      appendChatBubble("assistant", "Fehler: " + result.error);
    } else {
      appendChatBubble("assistant", result.reply);
      belegChatHistory.push({ role: "user", content: message || "(Anhang gesendet)" });
      belegChatHistory.push({ role: "assistant", content: result.reply });
      (result.proposals || []).forEach(p => {
        renderBelegProposal(p, result.attachment_filename, result.attachment_base64);
      });
    }
  } catch (e) {
    hideChatTyping("beleg-chat-log");
    // api() zeigt den Fehler bereits per alert() an
  }
  statusEl.textContent = "";
  sendBtn.disabled = false;
  msgInput.value = "";
  fileInput.value = "";
});

async function loadBelegChatModelSelect() {
  const sel = document.getElementById("beleg-chat-model");
  const s = await api("/settings/ollama");
  if (!s.url) return;
  try {
    const result = await api(`/ollama/models?url=${encodeURIComponent(s.url)}`);
    sel.innerHTML = '<option value="">Wie Standard-Modell</option>';
    result.models.forEach(m => {
      const opt = document.createElement("option");
      opt.value = m; opt.textContent = m;
      sel.appendChild(opt);
    });
    sel.value = s.beleg_chat_model || "";
  } catch (e) {
    // Ollama evtl. nicht erreichbar - Dropdown bleibt beim Default-Eintrag
  }
}

document.getElementById("beleg-chat-model").addEventListener("change", async e => {
  const s = await api("/settings/ollama");
  await api("/settings/ollama", { method: "PUT", body: JSON.stringify({ url: s.url, model: s.model, beleg_chat_model: e.target.value || null }) });
  toast(e.target.value ? `Bild-Modell: ${e.target.value}` : "Bild-Modell: wie Standard-Modell");
});


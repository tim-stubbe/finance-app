// ================= SETTINGS: ANMELDUNG & SICHERHEIT =================
// Session-Timeout, TOTP (2FA) und Passkey-Verwaltung im Einstellungen-Tab
// (siehe index.html "Anmeldung & Sicherheit"-Panel) - alle Endpunkte in
// backend/app/routers/auth_login.py. Logout ebenfalls hier verdrahtet.

async function loadAuthSettingsPanel() {
  let status;
  try {
    status = await api("/auth/status");
  } catch (e) {
    return;
  }
  document.getElementById("session-timeout-input").value = status.session_idle_timeout_minutes;

  document.getElementById("totp-status-off").classList.toggle("hidden", status.totp_enabled);
  document.getElementById("totp-status-on").classList.toggle("hidden", !status.totp_enabled);
  document.getElementById("totp-setup-flow").classList.add("hidden");
  document.getElementById("totp-recovery-display").classList.add("hidden");

  await loadPasskeyList();
  await loadUsersList();
}

// ---------- Personen (Multi-User) ----------
async function loadUsersList() {
  const list = document.getElementById("users-list");
  let users = [];
  try { users = await api("/auth/users"); } catch { return; }
  list.innerHTML = users.map(u => `
    <li>
      <span>${esc(u.name)}${u.is_self ? " (du)" : ""}
        <span class="page-sub">${u.totp_enabled ? "2FA · " : ""}${u.passkey_count} Passkey(s)</span></span>
      ${u.is_self ? "" : `<button type="button" class="btn-ghost btn-sm" data-user-del="${u.id}">Entfernen</button>`}
    </li>`).join("") || `<li class="page-sub" style="background:none;padding:0">–</li>`;
}

document.getElementById("users-list").addEventListener("click", async e => {
  const id = e.target.closest("[data-user-del]")?.dataset.userDel;
  if (!id) return;
  if (!confirm("Diese Person entfernen? Ihr Login und ihre Passkeys werden gelöscht (die geteilten Daten bleiben).")) return;
  try { await api(`/auth/users/${id}`, { method: "DELETE" }); toast("Person entfernt."); loadUsersList(); }
  catch (err) { toast(err.message || "Entfernen fehlgeschlagen."); }
});

document.getElementById("user-add-form").addEventListener("submit", async e => {
  e.preventDefault();
  setFormError("user-add-error", null);
  try {
    await api("/auth/users", {
      method: "POST",
      body: JSON.stringify({
        name: document.getElementById("user-add-name").value.trim(),
        password: document.getElementById("user-add-password").value,
      }),
    });
    e.target.reset();
    toast("Person hinzugefügt.");
    loadUsersList();
  } catch (err) {
    setFormError("user-add-error", err.message || "Konnte nicht angelegt werden.");
  }
});

document.getElementById("session-timeout-form").addEventListener("submit", async e => {
  e.preventDefault();
  const minutes = parseInt(document.getElementById("session-timeout-input").value, 10);
  await api("/auth/session-timeout", { method: "PUT", body: JSON.stringify({ session_idle_timeout_minutes: minutes }) });
  toast("Timeout gespeichert.");
});

document.getElementById("password-change-form").addEventListener("submit", async e => {
  e.preventDefault();
  // Kein eigenes Fehler-Handling hier - api() zeigt bei falschem aktuellem
  // Passwort (401) bereits eine erklärende Alert-Box, ein zweites Mal
  // inline anzuzeigen wäre nur doppelt (siehe restliche Formulare in dieser
  // Datei, z.B. session-timeout-form oben, gleiche Konvention).
  const current_password = document.getElementById("password-change-current").value;
  const new_password = document.getElementById("password-change-new").value;
  await api("/auth/password", { method: "PUT", body: JSON.stringify({ current_password, new_password }) });
  document.getElementById("password-change-form").reset();
  toast("Passwort geändert.");
});

// ---------- TOTP ----------
document.getElementById("totp-start-setup").addEventListener("click", async () => {
  const data = await api("/auth/totp/setup", { method: "POST" });
  document.getElementById("totp-qr-img").src = data.qr_code_data_uri;
  document.getElementById("totp-manual-secret").textContent = data.secret;
  document.getElementById("totp-confirm-code").value = "";
  setFormError("totp-setup-error", null);
  document.getElementById("totp-status-off").classList.add("hidden");
  document.getElementById("totp-setup-flow").classList.remove("hidden");
});

document.getElementById("totp-setup-cancel").addEventListener("click", async () => {
  // Kein eigener "Abbrechen"-Endpunkt nötig: ein nie bestätigtes Setup
  // (totp_enabled bleibt false) wird beim naechsten /totp/setup-Aufruf
  // ohnehin durch ein neues Secret ersetzt - hier reicht es, die
  // Oberflaeche zurueckzusetzen.
  document.getElementById("totp-setup-flow").classList.add("hidden");
  document.getElementById("totp-status-off").classList.remove("hidden");
});

document.getElementById("totp-confirm-form").addEventListener("submit", async e => {
  e.preventDefault();
  // try/catch nur, damit bei einem ungültigen Code (api() zeigt dafür
  // schon die Alert-Box) NICHT trotzdem die Setup-Ansicht ausgeblendet und
  // ein nie erzeugter Wiederherstellungscode angezeigt wird.
  const code = document.getElementById("totp-confirm-code").value.trim();
  let data;
  try {
    data = await api("/auth/totp/confirm", { method: "POST", body: JSON.stringify({ code }) });
  } catch (e) {
    return;
  }
  document.getElementById("totp-setup-flow").classList.add("hidden");
  document.getElementById("totp-recovery-code-text").textContent = data.recovery_code;
  document.getElementById("totp-recovery-display").classList.remove("hidden");
});

document.getElementById("totp-recovery-done").addEventListener("click", () => {
  document.getElementById("totp-recovery-display").classList.add("hidden");
  document.getElementById("totp-status-on").classList.remove("hidden");
});

document.getElementById("totp-disable-btn").addEventListener("click", async () => {
  const value = document.getElementById("totp-disable-confirm").value.trim();
  setFormError("totp-disable-error", null);
  if (!value) {
    setFormError("totp-disable-error", "Bitte Passwort oder aktuellen Code eingeben.");
    return;
  }
  // Heuristik statt zweier Felder: ein reiner 6-stelliger Code gilt als
  // TOTP-Code, alles andere als Passwort - beides prüft das Backend ohnehin
  // serverseitig, hier geht es nur darum, das richtige Feld zu befüllen.
  const isCode = /^\d{6}$/.test(value);
  await api("/auth/totp", {
    method: "DELETE",
    body: JSON.stringify(isCode ? { code: value } : { password: value }),
  });
  document.getElementById("totp-disable-confirm").value = "";
  document.getElementById("totp-status-on").classList.add("hidden");
  document.getElementById("totp-status-off").classList.remove("hidden");
  toast("Zwei-Faktor deaktiviert.");
});

// ---------- Passkeys ----------
async function loadPasskeyList() {
  const list = document.getElementById("passkey-list");
  let creds = [];
  try {
    creds = await api("/auth/webauthn/credentials");
  } catch (e) {
    return;
  }
  if (!creds.length) {
    list.innerHTML = `<li class="page-sub" style="background:none;padding:0">Noch keine Passkeys registriert.</li>`;
    return;
  }
  list.innerHTML = creds.map(c => `
    <li>
      <span>🔐 ${esc(c.name || "Passkey")}</span>
      <button type="button" class="btn-ghost btn-sm" data-delete-passkey="${c.id}">Entfernen</button>
    </li>`).join("");
}

document.getElementById("passkey-list").addEventListener("click", async e => {
  const btn = e.target.closest("[data-delete-passkey]");
  if (!btn) return;
  await api(`/auth/webauthn/credentials/${btn.dataset.deletePasskey}`, { method: "DELETE" });
  loadPasskeyList();
});

document.getElementById("passkey-add-btn").addEventListener("click", async () => {
  setFormError("passkey-error", null);
  if (!window.PublicKeyCredential) {
    setFormError("passkey-error", "Dieser Browser unterstützt keine Passkeys.");
    return;
  }
  const name = document.getElementById("passkey-new-name").value.trim() || "Passkey";
  try {
    await registerPasskey(name);
    document.getElementById("passkey-new-name").value = "";
    toast("Passkey hinzugefügt.");
    loadPasskeyList();
  } catch (e) {
    setFormError("passkey-error", "Passkey konnte nicht hinzugefügt werden (abgebrochen oder nicht unterstützt).");
  }
});

// ---------- Logout ----------
document.getElementById("logout-btn").addEventListener("click", logout);

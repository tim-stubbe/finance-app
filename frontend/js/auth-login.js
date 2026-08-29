// ================= WEB-LOGIN: BOOT-GATE + LOGIN-FORMULARE =================
// Letztes geladenes Skript (siehe index.html) - ruft am Ende bootAuthGate()
// auf, das GET /api/auth/status prüft und je nach Ergebnis Setup-/Login-/
// TOTP-Screen zeigt oder direkt startApp() (aus core.js) aufruft. Ersetzt
// die bisherige "keine Anmeldung" (siehe README.md/SECURITY.md).
//
// Gemeinsame Helfer (b64url-Konvertierung, logout(), registerPasskey(),
// setFormError()) leben in js/auth-helpers.js, das früh lädt (direkt nach
// core.js) - die braucht schon settings-auth.js (Einstellungen-Tab), lange
// bevor dieses Skript hier an der Reihe wäre.

// ---------- Boot-Gate ----------
async function bootAuthGate() {
  let status;
  // Ein Versuch, dann nach kurzer Pause noch einer - deckt den Fall ab, dass
  // die (Tailscale-)Verbindung beim Kaltstart der PWA noch nicht steht.
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const res = await fetch(API + "/auth/status", { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      status = await res.json();
      break;
    } catch (e) {
      if (attempt === 0) { await new Promise(r => setTimeout(r, 1500)); continue; }
      showLoginScreen({
        error: "Server nicht erreichbar. Ist die Verbindung (Tailscale) aktiv? "
          + "Prüfen: " + API + "/auth/status im Browser öffnen. Dann Seite neu laden.",
      });
      return;
    }
  }
  if (status.setup_required) {
    showSetupScreen();
  } else if (status.authenticated) {
    startApp();
  } else if (status.totp_required) {
    showTotpScreen();
  } else {
    showLoginScreen({ showPasskey: status.passkeys_enabled, showName: (status.users_count || 1) > 1 });
  }
}

function hideAllLoginForms() {
  ["setup-form", "login-form", "totp-form", "recovery-form"].forEach(id => {
    document.getElementById(id).classList.add("hidden");
  });
}

function showLoginScreen({ message, error, showPasskey, showName } = {}) {
  document.getElementById("login-screen").classList.remove("hidden");
  hideAllLoginForms();
  document.getElementById("login-form").classList.remove("hidden");
  document.getElementById("login-password").value = "";
  document.getElementById("login-name-label").classList.toggle("hidden", !showName);
  setFormMessage("login-message", message);
  setFormError("login-error", error);
  document.getElementById("login-passkey-btn").classList.toggle(
    "hidden", !(showPasskey && window.PublicKeyCredential),
  );
}

function showSetupScreen() {
  document.getElementById("login-screen").classList.remove("hidden");
  hideAllLoginForms();
  document.getElementById("setup-form").classList.remove("hidden");
}

function showTotpScreen() {
  document.getElementById("login-screen").classList.remove("hidden");
  hideAllLoginForms();
  document.getElementById("totp-form").classList.remove("hidden");
  document.getElementById("totp-code").value = "";
  document.getElementById("totp-code").focus();
}

function showRecoveryScreen() {
  hideAllLoginForms();
  document.getElementById("recovery-form").classList.remove("hidden");
}

// ---------- Setup ----------
document.getElementById("setup-form").addEventListener("submit", async e => {
  e.preventDefault();
  const password = document.getElementById("setup-password").value;
  const confirm = document.getElementById("setup-password-confirm").value;
  setFormError("setup-error", null);
  if (password.length < 10) {
    setFormError("setup-error", "Passwort muss mindestens 10 Zeichen lang sein.");
    return;
  }
  if (password !== confirm) {
    setFormError("setup-error", "Passwörter stimmen nicht überein.");
    return;
  }
  try {
    const res = await fetch(API + "/auth/setup", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password, display_name: document.getElementById("setup-name").value.trim() || null }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      setFormError("setup-error", formatApiErrorDetail(err.detail) || "Einrichtung fehlgeschlagen.");
      return;
    }
    document.getElementById("login-screen").classList.add("hidden");
    startApp();
  } catch (e) {
    setFormError("setup-error", "Server nicht erreichbar.");
  }
});

// ---------- Login (Passwort) ----------
document.getElementById("login-form").addEventListener("submit", async e => {
  e.preventDefault();
  const password = document.getElementById("login-password").value;
  const name = document.getElementById("login-name").value.trim();
  setFormError("login-error", null);
  try {
    const res = await fetch(API + "/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password, name: name || null }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setFormError("login-error", formatApiErrorDetail(data.detail) || "Anmeldung fehlgeschlagen.");
      return;
    }
    if (data.totp_required) {
      showTotpScreen();
      return;
    }
    document.getElementById("login-screen").classList.add("hidden");
    startApp();
  } catch (e) {
    setFormError("login-error", "Server nicht erreichbar.");
  }
});

// ---------- TOTP-Verifikation ----------
document.getElementById("totp-form").addEventListener("submit", async e => {
  e.preventDefault();
  const code = document.getElementById("totp-code").value.trim();
  setFormError("totp-error", null);
  try {
    const res = await fetch(API + "/auth/totp/verify", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setFormError("totp-error", formatApiErrorDetail(data.detail) || "Code ungültig.");
      return;
    }
    document.getElementById("login-screen").classList.add("hidden");
    startApp();
  } catch (e) {
    setFormError("totp-error", "Server nicht erreichbar.");
  }
});

document.getElementById("totp-recovery-link").addEventListener("click", () => {
  setFormError("totp-error", null);
  showRecoveryScreen();
});

// ---------- Wiederherstellungscode ----------
document.getElementById("recovery-form").addEventListener("submit", async e => {
  e.preventDefault();
  const recovery_code = document.getElementById("recovery-code").value.trim();
  setFormError("recovery-error", null);
  try {
    const res = await fetch(API + "/auth/recovery-login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recovery_code }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setFormError("recovery-error", formatApiErrorDetail(data.detail) || "Code ungültig.");
      return;
    }
    document.getElementById("login-screen").classList.add("hidden");
    startApp();
  } catch (e) {
    setFormError("recovery-error", "Server nicht erreichbar.");
  }
});

// ---------- Passkey-Login ----------
document.getElementById("login-passkey-btn").addEventListener("click", async () => {
  setFormError("login-error", null);
  try {
    const optionsRes = await fetch(API + "/auth/webauthn/login/options", { method: "POST" });
    const optionsData = await optionsRes.json().catch(() => ({}));
    if (!optionsRes.ok) {
      setFormError("login-error", formatApiErrorDetail(optionsData.detail) || "Passkey-Anmeldung nicht möglich.");
      return;
    }
    const publicKey = optionsData.publicKey;
    publicKey.challenge = b64urlToBuffer(publicKey.challenge);
    if (publicKey.allowCredentials) {
      publicKey.allowCredentials = publicKey.allowCredentials.map(c => ({ ...c, id: b64urlToBuffer(c.id) }));
    }
    const assertion = await navigator.credentials.get({ publicKey });
    const credentialJson = {
      id: assertion.id,
      rawId: bufferToB64url(assertion.rawId),
      type: assertion.type,
      response: {
        clientDataJSON: bufferToB64url(assertion.response.clientDataJSON),
        authenticatorData: bufferToB64url(assertion.response.authenticatorData),
        signature: bufferToB64url(assertion.response.signature),
        userHandle: assertion.response.userHandle ? bufferToB64url(assertion.response.userHandle) : null,
      },
    };
    const verifyRes = await fetch(API + "/auth/webauthn/login/verify", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ credential: credentialJson }),
    });
    const verifyData = await verifyRes.json().catch(() => ({}));
    if (!verifyRes.ok) {
      setFormError("login-error", formatApiErrorDetail(verifyData.detail) || "Passkey-Anmeldung fehlgeschlagen.");
      return;
    }
    document.getElementById("login-screen").classList.add("hidden");
    startApp();
  } catch (e) {
    // Abbruch durch den Nutzer (z.B. Face-ID-Dialog geschlossen) landet auch
    // hier - kein hartes Fehler-Alert, nur eine ruhige Zeile im Formular.
    setFormError("login-error", "Passkey-Anmeldung abgebrochen oder fehlgeschlagen.");
  }
});

bootAuthGate();

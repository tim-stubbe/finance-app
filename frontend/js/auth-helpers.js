// ================= WEB-LOGIN: GEMEINSAME HELFER =================
// Früh geladen (direkt nach core.js, siehe index.html) - anders als
// js/auth-login.js (Boot-Gate + Login-Formulare, muss als LETZTES Skript
// laden, siehe dort), werden diese Funktionen schon von settings-auth.js
// gebraucht (Logout-Button, Passkey-Hinzufügen im Einstellungen-Tab),
// lange bevor auth-login.js an der Reihe wäre. Reine Funktionsdefinitionen,
// kein Boot-Code hier.

// ---------- Base64url <-> ArrayBuffer (fürs WebAuthn-Browser-API) ----------
function b64urlToBuffer(b64url) {
  const pad = "=".repeat((4 - (b64url.length % 4)) % 4);
  const base64 = (b64url + pad).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const buf = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i);
  return buf.buffer;
}
function bufferToB64url(buf) {
  const bytes = new Uint8Array(buf);
  let str = "";
  for (const b of bytes) str += String.fromCharCode(b);
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function setFormError(elId, message) {
  const el = document.getElementById(elId);
  el.textContent = message || "";
  el.classList.toggle("hidden", !message);
}
function setFormMessage(elId, message) {
  const el = document.getElementById(elId);
  el.textContent = message || "";
  el.classList.toggle("hidden", !message);
}

// Von api() bei jeder 401-Antwort aufgerufen (core.js) - Sitzung ist weg
// (Timeout oder serverseitig invalidiert), zurück zum Login statt der
// generischen Fehler-Alert-Box. Die eigentliche Login-Screen-Anzeige lebt
// in auth-login.js (showLoginScreen) - hier nur der Einstiegspunkt, den
// core.js unabhängig von der Ladereihenfolge per typeof-Check aufruft.
function handleUnauthorized() {
  document.getElementById("app").classList.add("hidden");
  if (typeof showLoginScreen === "function") {
    showLoginScreen({ message: "Sitzung abgelaufen - bitte erneut anmelden." });
  }
}

// ---------- Logout (Einstellungen-Tab UND ggf. anderswo) ----------
async function logout() {
  try {
    await fetch(API + "/auth/logout", { method: "POST" });
  } catch (e) {
    // Server nicht erreichbar - trotzdem neu laden, es gibt ohnehin nichts
    // mehr zu tun außer zum Login-Screen zurückzukehren.
  }
  location.reload();
}

// ---------- Passkey-Registrierung (Einstellungen-Tab) ----------
async function registerPasskey(name) {
  const optionsData = await api("/auth/webauthn/register/options", { method: "POST" });
  const publicKey = optionsData.publicKey;
  publicKey.challenge = b64urlToBuffer(publicKey.challenge);
  publicKey.user.id = b64urlToBuffer(publicKey.user.id);
  if (publicKey.excludeCredentials) {
    publicKey.excludeCredentials = publicKey.excludeCredentials.map(c => ({ ...c, id: b64urlToBuffer(c.id) }));
  }
  const credential = await navigator.credentials.create({ publicKey });
  const credentialJson = {
    id: credential.id,
    rawId: bufferToB64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: bufferToB64url(credential.response.clientDataJSON),
      attestationObject: bufferToB64url(credential.response.attestationObject),
      transports: credential.response.getTransports ? credential.response.getTransports() : [],
    },
  };
  return api("/auth/webauthn/register/verify", {
    method: "POST", body: JSON.stringify({ credential: credentialJson, name }),
  });
}

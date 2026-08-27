// Minimaler Service Worker, nur damit die App als PWA installierbar ist und die
// Oberfläche (nicht die Daten!) auch bei wackliger Tailscale-Verbindung sofort
// lädt. Cacht bewusst NUR die statische App-Hülle - /api/-Antworten werden nie
// abgefangen, Finanzdaten müssen immer live vom Server kommen, nie aus dem Cache.
// v23: Web-Login ergaenzt (js/auth-login.js, siehe ROADMAP.md) - Bump der
// CACHE_NAME-Version erzwingt bei bestehenden Installationen den Wechsel,
// damit der Login-Screen nicht aus einem alten, ihn noch nicht kennenden
// Precache fehlt.
const CACHE_NAME = "finanztool-shell-v31";
const SHELL_ASSETS = [
  "/", "/index.html", "/style.css", "/manifest.json", "/alpen-bg.svg",
  "/js/core.js", "/js/auth-helpers.js", "/js/accounts.js", "/js/categories.js", "/js/investments.js",
  "/js/ki-assistent.js", "/js/ki-review-queue.js", "/js/beleg-chat.js",
  "/js/trips.js", "/js/projekte.js", "/js/leben.js", "/js/wunschliste.js",
  "/js/transactions.js", "/js/abos.js", "/js/profile.js", "/js/fotos.js",
  "/js/belege-emails.js", "/js/webhook-n8n.js", "/js/vermoegensvergleich.js",
  "/js/settings-auth.js", "/js/settings-budgets.js", "/js/settings-export-backup.js",
  "/js/settings-auto-backups.js", "/js/settings-auto-sync.js",
  "/js/eigene-regeln.js", "/js/settings-fints.js", "/js/settings-bitvavo.js",
  "/js/settings-paypal.js", "/js/settings-enablebanking.js", "/js/kalender.js",
  "/js/dashboard.js", "/js/geschaeftlich.js", "/js/schulden.js",
  "/js/schwebender-ki-assistent.js", "/js/ziele.js", "/js/init.js",
  "/js/command-palette.js", "/js/jahresrueckblick.js", "/js/notizen.js",
  "/js/auth-login.js", "/js/settings-assistent.js",
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL_ASSETS)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/api/") || event.request.method !== "GET") return;

  event.respondWith(
    fetch(event.request)
      .then(resp => {
        const copy = resp.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy)).catch(() => {});
        return resp;
      })
      .catch(() => caches.match(event.request))
  );
});

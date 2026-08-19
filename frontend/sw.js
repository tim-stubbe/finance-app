// Minimaler Service Worker, nur damit die App als PWA installierbar ist und die
// Oberfläche (nicht die Daten!) auch bei wackliger Tailscale-Verbindung sofort
// lädt. Cacht bewusst NUR die statische App-Hülle - /api/-Antworten werden nie
// abgefangen, Finanzdaten müssen immer live vom Server kommen, nie aus dem Cache.
const CACHE_NAME = "finanztool-shell-v6";
const SHELL_ASSETS = ["/", "/index.html", "/style.css", "/app.js", "/manifest.json", "/alpen-bg.svg"];

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

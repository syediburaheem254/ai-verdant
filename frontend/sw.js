/*
  AI Verdant — Service Worker
  Caches the app shell (HTML/CSS/JS) so the app opens instantly and
  still loads its interface with no signal. Live sensor data still
  requires a connection to the backend — this only makes the app
  itself installable and resilient, not the data offline-first.
*/

const CACHE_NAME = "ai-verdant-shell-v1";
const SHELL_FILES = [
  "index.html",
  "sensors.html",
  "trends.html",
  "strategy.html",
  "settings.html",
  "css/theme.css",
  "js/api.js",
  "js/ui.js",
  "manifest.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // Never cache API calls — always go to the network for live sensor data.
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/portal/")) {
    return;
  }
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});

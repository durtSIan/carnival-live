const CACHE_NAME = "carnival-live-v3";
const APP_SHELL = [
  "/static/offline.html",
  "/static/icon.svg",
  "/static/dashboard.css",
  "/static/final.css",
  "/static/chase.css",
  "/static/nav.css",
  "/static/forfeit.css",
  "/static/status.css",
  "/static/compact.css",
  "/static/display-mode.css",
  "/static/display-mode.js",
  "/static/batter-order.js",
  "/static/setup.css",
  "/static/pwa.js"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() => caches.match("/static/offline.html"))
    );
    return;
  }

  const url = new URL(request.url);
  if (url.origin === self.location.origin && url.pathname.startsWith("/static/")) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => caches.match(request))
    );
  }
});

/* Offline support. Everything is network-first, so a new deploy is picked up on the next open; when the
   network is unavailable the last cached copy is served (app shell and data/*.json alike). */
const VERSION = "stock-radar-v4";
const SHELL = ["./", "index.html", "styles.css", "app.js", "manifest.webmanifest",
  "icons/apple-touch-icon.png", "icons/icon-192.png", "icons/icon-512.png", "icons/favicon.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET" || new URL(req.url).origin !== self.location.origin) return;
  event.respondWith(fetch(req, { cache: "no-cache" }).then((res) => {
    if (res.ok) {
      const copy = res.clone();
      caches.open(VERSION).then((c) => c.put(req, copy));
    }
    return res;
  }).catch(() => caches.match(req, { ignoreSearch: true })));
});

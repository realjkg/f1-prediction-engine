// Pit Wall — minimal offline shell (Milestone 1).
//
// Contract: the APP SHELL is cache-first so the installed PWA opens offline;
// ENGINE DATA is network-only. Predictions, scores, and the ledger are never
// served from cache — a stale probability presented as live would break the
// evidence contract. With the engine unreachable, the shell opens and the
// screens show the typed engine-unreachable error with retry.

const SHELL_CACHE = "pitwall-shell-v1";
const SHELL_URLS = ["/", "/index.html", "/manifest.webmanifest", "/icons/icon.svg", "/icons/icon-maskable.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_URLS))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== SHELL_CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Engine data: always the network, never the cache.
  if (url.pathname.startsWith("/api/") || url.pathname === "/metrics") return;

  // Static assets are content-hashed by Vite — cache-first is safe.
  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ??
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
    return;
  }

  // Navigations: shell-first, with the cached index.html as the offline fallback.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() =>
        caches.match("/index.html").then(
          (hit) =>
            hit ??
            new Response("Pit Wall is offline — the app shell is unavailable.", {
              status: 503,
              headers: { "Content-Type": "text/plain" },
            }),
        ),
      ),
    );
  }
});

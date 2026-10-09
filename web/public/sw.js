// F1 Prediction Engine — minimal service worker (Milestone 1 scaffold).
// Installs and claims immediately; all requests pass through to the network.
// A real offline-shell caching strategy lands with the PWA task.
self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

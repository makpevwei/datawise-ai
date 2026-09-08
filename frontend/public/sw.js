/**
 * DataWise AI — Service Worker
 *
 * Strategy: network-first throughout. This is a data-analysis app whose
 * core value is live, grounded answers from the backend — stale cached
 * answers would be actively misleading, which is worse than no answer.
 *
 * What IS cached (shell + static assets):
 *   - The app shell (/, /dashboard, /ask, /login, etc.) — so the UI loads
 *     fast on repeat visits and shows a proper offline page instead of a
 *     browser "No connection" error when the network is down.
 *   - Next.js static chunks (/_next/static/**) — immutable, hashed
 *     filenames, safe to cache indefinitely.
 *   - Public assets (/icon-*.png, etc.)
 *
 * What is NEVER cached:
 *   - /api/** — all backend calls must be live. A cached 200 from last
 *     session shown as a fresh answer would silently bypass the entire
 *     grounding/verification system. Network failure → show error in UI,
 *     same as today.
 *
 * Offline fallback: /offline.html is pre-cached and served for any
 * navigation request that fails while offline (document requests only,
 * not API or asset requests).
 */

const CACHE_NAME = "datawise-shell-v1";

// App shell routes to pre-cache on install. These are the HTML documents
// for each route — Next.js renders them server-side, so we cache the
// response from the first network visit, not a static HTML file.
const SHELL_URLS = [
  "/",
  "/dashboard",
  "/ask",
  "/my-data",
  "/analyses",
  "/reports",
  "/insights",
  "/settings",
  "/login",
  "/offline",
];

// ─── Install ────────────────────────────────────────────────────────────────
// Pre-cache the offline fallback page immediately. The rest of the shell
// is cached on first visit (network-first fills the cache naturally).
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.add("/offline"))
      // Skip waiting so the new SW activates immediately on first install
      // rather than waiting for all existing tabs to close.
      .then(() => self.skipWaiting()),
  );
});

// ─── Activate ───────────────────────────────────────────────────────────────
// Delete any caches from previous SW versions so stale shell HTML
// doesn't accumulate. Cache names are versioned (CACHE_NAME), so a
// cache not matching the current name is from an old install.
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== CACHE_NAME)
            .map((key) => caches.delete(key)),
        ),
      )
      // Claim all open clients immediately so the new SW controls them
      // without requiring a page reload.
      .then(() => self.clients.claim()),
  );
});

// ─── Fetch ───────────────────────────────────────────────────────────────────
self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // 1. API calls: always network-only. A failed API call falls through to
  //    the browser's own error handling (the React UI shows an ErrorBanner).
  //    Never intercept — never return a cached answer as if it were live.
  if (url.pathname.startsWith("/api/")) {
    return; // let the browser handle it with no SW involvement
  }

  // 2. Next.js static chunks (/_next/static/**): immutable, content-hashed
  //    filenames. Cache-first: if the file is in cache, serve it instantly;
  //    if not, fetch and cache. These never change for a given deploy.
  if (url.pathname.startsWith("/_next/static/")) {
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ??
          fetch(request).then((response) => {
            // Only cache successful responses (2xx). Never cache errors.
            if (response.ok) {
              const clone = response.clone();
              caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
            }
            return response;
          }),
      ),
    );
    return;
  }

  // 3. Navigation requests (document fetches, i.e. page loads):
  //    Network-first — try the network, serve a fresh HTML response and
  //    update the cache. If offline, serve the cached version if available,
  //    or fall back to /offline if we have nothing cached for this URL.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          // Cache a copy of every successful page response so it's available
          // offline on next visit.
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        })
        .catch(() =>
          // Network failed: serve cached version of this specific URL, or
          // fall back to the offline page pre-cached during install.
          caches
            .match(request)
            .then((cached) => cached ?? caches.match("/offline")),
        ),
    );
    return;
  }

  // 4. Everything else (fonts, images, public assets): network-first,
  //    cache on success, serve cached on failure. No offline fallback
  //    for individual assets — a missing icon is not a broken experience.
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return response;
      })
      .catch(() => caches.match(request)),
  );
});

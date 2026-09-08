"use client";

import { useEffect } from "react";

/**
 * Registers the DataWise service worker (/sw.js) once, on first mount.
 *
 * Mounted in the root layout so it runs on every page. The registration
 * is idempotent — the browser de-duplicates SW registrations for the same
 * scope, so repeated renders don't re-register.
 *
 * Why a separate component rather than a script tag in layout.tsx:
 * layout.tsx is a Server Component; navigator.serviceWorker is client-only.
 * A "use client" component is the correct boundary for browser APIs in
 * the App Router.
 *
 * The SW itself (/public/sw.js) uses a network-first strategy throughout.
 * API calls (/api/**) are never intercepted — they always go directly to
 * the network so the grounding/verification system can never be bypassed
 * by a cached answer from a previous session.
 */
export function ServiceWorkerRegistration() {
  useEffect(() => {
    if (typeof window === "undefined" || !("serviceWorker" in navigator)) {
      return;
    }

    navigator.serviceWorker
      .register("/sw.js", {
        scope: "/",
        // updateViaCache: "none" forces the browser to always re-fetch sw.js
        // from the network to check for updates, ignoring the HTTP cache.
        // Without this, a stale SW can persist for up to 24 hours behind a
        // long-lived Cache-Control header.
        updateViaCache: "none",
      })
      .then((registration) => {
        // Check for a waiting SW (new version downloaded but not yet active)
        // and activate it immediately rather than waiting for all tabs to close.
        if (registration.waiting) {
          registration.waiting.postMessage({ type: "SKIP_WAITING" });
        }
        registration.addEventListener("updatefound", () => {
          const newWorker = registration.installing;
          if (newWorker) {
            newWorker.addEventListener("statechange", () => {
              if (
                newWorker.state === "installed" &&
                navigator.serviceWorker.controller
              ) {
                // A new SW is ready. Activate it so the shell cache refreshes
                // on the next navigation rather than lingering until the user
                // closes all tabs.
                newWorker.postMessage({ type: "SKIP_WAITING" });
              }
            });
          }
        });
      })
      .catch(() => {
        // SW registration failure is non-fatal — the app works identically
        // without a SW, just without the offline shell cache and fast repeat
        // loads. Silently swallow the error rather than surfacing it to the
        // user (it's a progressive enhancement, not a hard requirement).
      });
  }, []); // run once on mount, never again

  // Renders nothing — purely a side-effect component.
  return null;
}

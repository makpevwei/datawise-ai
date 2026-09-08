import type { MetadataRoute } from "next";

/**
 * Web App Manifest — served at /manifest.webmanifest by Next.js automatically.
 * Controls how the app appears when installed on Android (Add to Home Screen /
 * TWA) and iOS (Add to Home Screen). Colors match the design system's light-mode
 * brand tokens in globals.css.
 *
 * TWA note: when packaging with Bubblewrap for the Play Store, the
 * start_url, display, and theme_color here must match the TWA's
 * assetlinks.json configuration exactly.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "DataWise AI",
    short_name: "DataWise",
    description:
      "AI-powered business intelligence — ask questions about your data and get grounded, verifiable answers.",
    start_url: "/dashboard",
    // standalone: hides browser chrome so the installed app feels native.
    // Fullscreen is deliberately avoided — the browser's back gesture is
    // useful for a data-analysis app with multi-step flows.
    display: "standalone",
    // orientation: any — the dashboard is useful in landscape (wide charts)
    // and portrait (reading findings) so neither is forced.
    orientation: "any",
    // Brand teal from --brand in globals.css (light mode).
    theme_color: "#0f766e",
    // Off-white from --background in globals.css — matches the app shell
    // background seen during the splash screen before first paint.
    background_color: "#f9f9f7",
    categories: ["business", "productivity", "finance"],
    icons: [
      {
        // Standard icon — used for home screen, app switcher, splash screen.
        src: "/icon-192.png",
        sizes: "192x192",
        type: "image/png",
      },
      {
        // Large standard icon — used for high-DPI displays and splash screens.
        src: "/icon-512.png",
        sizes: "512x512",
        type: "image/png",
      },
      {
        // Maskable icon — Android adaptive icons apply a shape mask (circle,
        // squircle, etc.) over this. The lettermark sits within the 80% safe
        // zone so it is never clipped regardless of which mask shape Android
        // applies. Both sizes listed so the browser can pick the best fit.
        src: "/icon-512-maskable.png",
        sizes: "512x512",
        type: "image/png",
        // "maskable any" means this icon works both as a maskable adaptive
        // icon AND as a plain icon fallback — reduces the total icon count.
        purpose: "maskable",
      },
    ],
    // screenshots: intentionally omitted for now — required for the Play Store
    // "enhanced" listing but not for basic installability. Add before submitting
    // to the Play Store (Bubblewrap / TWA phase).
  };
}

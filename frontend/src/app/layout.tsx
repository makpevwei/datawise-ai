import type { Metadata, Viewport } from "next";
import { Manrope, Geist_Mono } from "next/font/google";
import { AuthProvider } from "@/lib/auth-context";
import { ServiceWorkerRegistration } from "@/components/ServiceWorkerRegistration";
import "./globals.css";

// Manrope -- warmer and rounder than the previous default (Geist Sans, a
// visible "Next.js starter" tell), while staying fully legible for dense
// finance-team tables. Chosen for a broad, non-technical audience (see
// globals.css's design-system comment) over a more clinical grotesque.
const appSans = Manrope({
  variable: "--font-app-sans",
  subsets: ["latin"],
});

// Kept for genuinely code-like content (calculations, column/table names,
// credentials) -- a monospace switch there aids scanning; it is not used
// as the app's default UI typeface.
const appMono = Geist_Mono({
  variable: "--font-app-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "DataWise AI",
  description: "AI-powered Business Intelligence and Data Analysis platform",
  // Trivial, deliberately visible marker for the CI-triggered-deploy
  // end-to-end test (push to main -> Vercel auto-deploys from its own
  // GitHub integration, no manual command run by anyone).
  other: { "x-deploy-pipeline": "verified-2026-08-30" },
  // manifest is served automatically by Next.js from src/app/manifest.ts
  // at /manifest.webmanifest.
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    // "yes" enables full-screen launch from iOS home screen (hides Safari
    // chrome), equivalent to display:standalone in the manifest.
    capable: true,
    title: "DataWise AI",
    // "black-translucent" lets the status bar overlay the app without a
    // white bar — keeps the brand teal header flush to the top on iOS.
    statusBarStyle: "black-translucent",
  },
};

// themeColor must be in a separate `viewport` export per Next.js App Router
// convention (themeColor in metadata triggers a build warning in this version).
// Matches manifest.theme_color (#0f766e, brand teal light mode).
export const viewport: Viewport = {
  themeColor: "#0f766e",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${appSans.variable} ${appMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <AuthProvider>{children}</AuthProvider>
        {/* SW registration: "use client" component, renders nothing,
            registers /sw.js once on first mount. Must be outside
            AuthProvider so it runs even on public routes (login, signup). */}
        <ServiceWorkerRegistration />
      </body>
    </html>
  );
}

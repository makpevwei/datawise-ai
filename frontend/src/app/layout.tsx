import type { Metadata } from "next";
import { Manrope, Geist_Mono } from "next/font/google";
import { AuthProvider } from "@/lib/auth-context";
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
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${appSans.variable} ${appMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}

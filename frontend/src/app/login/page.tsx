"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, useAuth } from "@/lib/auth-context";
import { Button, ErrorBanner, Spinner } from "@/components/ui";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("demo@datawise.ai");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(email, password);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen w-full items-center justify-center px-6 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-xl font-semibold tracking-tight text-[var(--text-primary)]">DataWise AI</h1>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">Your AI Business Analyst</p>
        </div>

        <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-1)] p-6">
          <h2 className="mb-5 text-base font-semibold text-[var(--text-primary)]">Sign in</h2>
          {error && (
            <div className="mb-4">
              <ErrorBanner message={error} />
            </div>
          )}
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium text-[var(--text-primary)]">Email</span>
              <input
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--series-1)]"
              />
            </label>
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium text-[var(--text-primary)]">Password</span>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  required
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 pr-10 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--series-1)]"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                >
                  {showPassword ? (
                    /* eye-off */
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                      <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                      <line x1="1" y1="1" x2="23" y2="23" />
                    </svg>
                  ) : (
                    /* eye */
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                  )}
                </button>
              </div>
            </label>
            <p className="text-xs text-[var(--text-muted)]">
              <Link href="/forgot-password" className="font-medium text-[var(--series-1)] hover:underline">
                Forgot your password?
              </Link>
            </p>
            <Button type="submit" disabled={loading}>
              {loading ? <Spinner /> : null} Sign In
            </Button>
          </form>
        </div>

        {/* Demo access note — clearly visible to new evaluators */}
        <div className="mt-4 rounded-xl border border-[var(--series-1)]/30 bg-[var(--series-1)]/5 px-4 py-3">
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--series-1)]">Demo Access</p>
          <p className="mb-2 text-xs text-[var(--text-secondary)]">Use these credentials to explore DataWise AI.</p>
          <div className="flex flex-col gap-1 text-xs text-[var(--text-primary)]">
            <div className="flex gap-2">
              <span className="w-16 shrink-0 text-[var(--text-muted)]">Email</span>
              <span className="font-mono font-medium">demo@datawise.ai</span>
            </div>
            <div className="flex gap-2">
              <span className="w-16 shrink-0 text-[var(--text-muted)]">Password</span>
              <span className="font-mono font-medium">password</span>
            </div>
          </div>
        </div>

        <p className="mt-5 text-center text-sm text-[var(--text-secondary)]">
          Don&apos;t have an account?{" "}
          <Link href="/signup" className="font-medium text-[var(--series-1)] hover:underline">
            Create one
          </Link>
        </p>
      </div>
    </div>
  );
}

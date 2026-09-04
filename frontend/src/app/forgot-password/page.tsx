"use client";

import { useState } from "react";
import Link from "next/link";
import { ApiError } from "@/lib/auth-context";
import { forgotPassword } from "@/lib/api";
import { Button, ErrorBanner, Spinner } from "@/components/ui";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await forgotPassword({ email });
      // Always shows the same success state, whether or not the email is
      // actually registered -- matches the backend's generic response, so
      // this page never reveals which emails have accounts.
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
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
          {submitted ? (
            <>
              <h2 className="mb-2 text-base font-semibold text-[var(--text-primary)]">Check your email</h2>
              <p className="text-sm text-[var(--text-secondary)]">
                If an account exists for <span className="font-medium text-[var(--text-primary)]">{email}</span>, a
                password reset link is on its way — it may take a minute, and it&apos;s worth checking your spam
                folder too. The link expires in 1 hour.
              </p>
            </>
          ) : (
            <>
              <h2 className="mb-1 text-base font-semibold text-[var(--text-primary)]">Reset your password</h2>
              <p className="mb-5 text-sm text-[var(--text-secondary)]">
                Enter your account email and we&apos;ll send you a link to set a new password.
              </p>
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
                    className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--brand)]"
                  />
                </label>
                <Button type="submit" disabled={loading}>
                  {loading ? <Spinner /> : null} Send reset link
                </Button>
              </form>
            </>
          )}
        </div>

        <p className="mt-5 text-center text-sm text-[var(--text-secondary)]">
          <Link href="/login" className="font-medium text-[var(--brand)] hover:underline">
            Back to sign in
          </Link>
        </p>
      </div>
    </div>
  );
}

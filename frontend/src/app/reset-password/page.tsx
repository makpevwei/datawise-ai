"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError } from "@/lib/auth-context";
import { resetPassword } from "@/lib/api";
import { Button, ErrorBanner, Spinner } from "@/components/ui";

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      await resetPassword({ token, new_password: password });
      setDone(true);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "This reset link is invalid or has expired. Request a new one."
      );
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
          {done ? (
            <>
              <h2 className="mb-2 text-base font-semibold text-[var(--text-primary)]">Password updated</h2>
              <p className="mb-5 text-sm text-[var(--text-secondary)]">
                You can now sign in with your new password.
              </p>
              <Button onClick={() => router.push("/login")}>Go to sign in</Button>
            </>
          ) : !token ? (
            <>
              <h2 className="mb-2 text-base font-semibold text-[var(--text-primary)]">Invalid link</h2>
              <p className="text-sm text-[var(--text-secondary)]">
                This reset link is missing its token. Request a new one from the{" "}
                <Link href="/forgot-password" className="font-medium text-[var(--brand)] hover:underline">
                  forgot password
                </Link>{" "}
                page.
              </p>
            </>
          ) : (
            <>
              <h2 className="mb-1 text-base font-semibold text-[var(--text-primary)]">Set a new password</h2>
              <p className="mb-5 text-sm text-[var(--text-secondary)]">Choose a new password for your account.</p>
              {error && (
                <div className="mb-4">
                  <ErrorBanner message={error} />
                </div>
              )}
              <form onSubmit={handleSubmit} className="flex flex-col gap-4">
                <label className="flex flex-col gap-1.5 text-sm">
                  <span className="font-medium text-[var(--text-primary)]">New password</span>
                  <input
                    type="password"
                    required
                    autoComplete="new-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--brand)]"
                  />
                </label>
                <label className="flex flex-col gap-1.5 text-sm">
                  <span className="font-medium text-[var(--text-primary)]">Confirm new password</span>
                  <input
                    type="password"
                    required
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--brand)]"
                  />
                </label>
                <Button type="submit" disabled={loading}>
                  {loading ? <Spinner /> : null} Update password
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

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordForm />
    </Suspense>
  );
}

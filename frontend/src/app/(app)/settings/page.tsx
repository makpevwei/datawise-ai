"use client";

import { useState } from "react";
import { ApiError, updateUserSettings, type CurrencyCode } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { Button, Card, ErrorBanner, SectionHeading } from "@/components/ui";

const CURRENCY_OPTIONS: { code: CurrencyCode; label: string }[] = [
  { code: "NGN", label: "₦ Nigerian Naira" },
  { code: "USD", label: "$ US Dollar" },
  { code: "EUR", label: "€ Euro" },
  { code: "GBP", label: "£ British Pound" },
  { code: "JPY", label: "¥ Japanese Yen" },
  { code: "INR", label: "₹ Indian Rupee" },
  { code: "CAD", label: "C$ Canadian Dollar" },
  { code: "AUD", label: "A$ Australian Dollar" },
];

const DECIMAL_OPTIONS = [0, 1, 2, 3, 4];

export default function SettingsPage() {
  const { user, setUser } = useAuth();
  const [currency, setCurrency] = useState<CurrencyCode>(user?.currency ?? "USD");
  const [decimalPlaces, setDecimalPlaces] = useState<number>(user?.decimal_places ?? 2);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  if (!user) return null;

  const dirty = currency !== user.currency || decimalPlaces !== user.decimal_places;

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await updateUserSettings({ currency, decimal_places: decimalPlaces });
      setUser(updated);
      setSaved(true);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "We couldn't save your settings. Please try again.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <SectionHeading title="Settings" subtitle="Your profile and how DataWise displays numbers." />

      <Card>
        <SectionHeading title="Profile" />
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="text-xs font-medium text-[var(--text-secondary)]">Full Name</label>
            <p className="mt-1 text-sm text-[var(--text-primary)]">{user.full_name}</p>
          </div>
          <div>
            <label className="text-xs font-medium text-[var(--text-secondary)]">Email</label>
            <p className="mt-1 text-sm text-[var(--text-primary)]">{user.email}</p>
          </div>
        </div>
      </Card>

      <Card>
        <SectionHeading
          title="Preferences"
          subtitle="Currency and decimal formatting are display-only -- they never change the underlying calculated values."
        />

        {error && <ErrorBanner message={error} />}
        {saved && <p className="mb-4 text-sm text-[var(--status-good)]">Settings saved.</p>}

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <label htmlFor="settings-currency" className="text-xs font-medium text-[var(--text-secondary)]">
              Currency
            </label>
            <select
              id="settings-currency"
              value={currency}
              onChange={(e) => {
                setCurrency(e.target.value as CurrencyCode);
                setSaved(false);
              }}
              className="rounded-lg border border-[var(--border)] bg-[var(--surface-1)] px-3 py-1.5 text-sm text-[var(--text-primary)]"
            >
              {CURRENCY_OPTIONS.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label htmlFor="settings-decimal-places" className="text-xs font-medium text-[var(--text-secondary)]">
              Decimal Places
            </label>
            <select
              id="settings-decimal-places"
              value={decimalPlaces}
              onChange={(e) => {
                setDecimalPlaces(Number(e.target.value));
                setSaved(false);
              }}
              className="rounded-lg border border-[var(--border)] bg-[var(--surface-1)] px-3 py-1.5 text-sm text-[var(--text-primary)]"
            >
              {DECIMAL_OPTIONS.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="mt-4">
          <Button onClick={handleSave} disabled={saving || !dirty}>
            {saving ? "Saving…" : "Save Settings"}
          </Button>
        </div>
      </Card>
    </div>
  );
}

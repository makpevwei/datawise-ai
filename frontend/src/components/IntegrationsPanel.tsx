"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  browseIntegration,
  disconnectIntegration,
  listIntegrationItems,
  listIntegrations,
  selectIntegrationItems,
  startGoogleConnect,
  syncIntegration,
  type BrowseFile,
  type ConnectedItemSummary,
  type IntegrationSummary,
} from "@/lib/api";
import { Button, Card, EmptyState, ErrorBanner, SectionHeading, Spinner } from "@/components/ui";

const SYNC_STATUS_STYLES: Record<string, string> = {
  synced: "bg-[var(--status-good)]/15 text-[var(--status-good)]",
  syncing: "bg-[var(--status-warning)]/20 text-[var(--status-warning)]",
  pending: "bg-[var(--status-warning)]/20 text-[var(--status-warning)]",
  error: "bg-[var(--status-critical)]/15 text-[var(--status-critical)]",
};

function SyncStatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${SYNC_STATUS_STYLES[status] ?? SYNC_STATUS_STYLES.pending}`}
    >
      {status}
    </span>
  );
}

/** Settings > Integrations tab: connect Google Drive/Sheets (read-only
 * OAuth), pick which files/sheets to sync, and see + manage what's
 * connected. Requesting only drive.readonly/spreadsheets.readonly is
 * enforced on the backend (app/integrations/oauth.py); this panel never
 * offers any write/edit action against a connected source. */
export function IntegrationsPanel({ banner }: { banner?: { kind: "success" | "error"; message: string } | null }) {
  const [integrations, setIntegrations] = useState<IntegrationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);

  // No synchronous setLoading(true) here -- `loading` already starts true
  // (see useState(true) above), covering the initial mount fetch below.
  // Later calls (after sync/select/disconnect, via onChanged) intentionally
  // don't re-flash the loading state over an already-rendered list; only
  // this call's own eventual setIntegrations/setLoading(false) run, and
  // only after the async gap, which is what react-hooks/set-state-in-effect
  // requires of anything invoked directly from a useEffect body.
  const refresh = useCallback(() => {
    listIntegrations()
      .then(setIntegrations)
      .catch(() => setError("Couldn't load your connected sources. Please try again."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleConnect() {
    setConnecting(true);
    setError(null);
    try {
      const { authorization_url } = await startGoogleConnect();
      window.location.href = authorization_url;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't start the Google connection. Please try again.");
      setConnecting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {banner && (
        <div
          className={`rounded-lg border px-4 py-3 text-sm ${
            banner.kind === "success"
              ? "border-[var(--status-good)]/30 bg-[var(--status-good)]/10 text-[var(--status-good)]"
              : "border-[var(--status-critical)]/30 bg-[var(--status-critical)]/10 text-[var(--status-critical)]"
          }`}
        >
          {banner.message}
        </div>
      )}
      {error && <ErrorBanner message={error} />}

      <Card>
        <div className="mb-4 flex items-center justify-between gap-3">
          <SectionHeading
            title="Connected Sources"
            subtitle="Read-only access to data that already lives elsewhere. DataWise never edits, deletes, or writes back to a connected source — see the Security note below."
          />
          <Button onClick={handleConnect} disabled={connecting}>
            {connecting ? <Spinner /> : null} {connecting ? "Redirecting…" : "+ Connect Google Drive / Sheets"}
          </Button>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 py-4 text-sm text-[var(--text-secondary)]">
            <Spinner /> Loading connected sources…
          </div>
        ) : integrations.length === 0 ? (
          <EmptyState
            title="No connected sources yet"
            description="Connect a Google account to bring in Sheets and Drive files, read-only. DataWise requests only drive.readonly and spreadsheets.readonly — it can never create, edit, or delete anything in your Google account."
          />
        ) : (
          <div className="flex flex-col gap-4">
            {integrations.map((integration) => (
              <IntegrationCard key={integration.id} integration={integration} onChanged={refresh} />
            ))}
          </div>
        )}
      </Card>

      <Card>
        <SectionHeading title="Security" />
        <ul className="list-disc space-y-1.5 pl-5 text-sm text-[var(--text-secondary)]">
          <li>Only two scopes are ever requested: <code className="text-xs">drive.readonly</code> and <code className="text-xs">spreadsheets.readonly</code> — no scope that can create, edit, or delete anything is requested, so Google itself rejects any write attempt before it reaches DataWise.</li>
          <li>Independently, DataWise&apos;s own code that talks to Google only ever calls read endpoints — enforced by an automated test, not just a promise.</li>
          <li>Your connected files are private to your account. No other DataWise user can see them.</li>
          <li>Disconnecting revokes DataWise&apos;s access with Google immediately. Data already synced stays in your workspace until you delete it, exactly like an uploaded file.</li>
        </ul>
      </Card>
    </div>
  );
}

function IntegrationCard({ integration, onChanged }: { integration: IntegrationSummary; onChanged: () => void }) {
  const [items, setItems] = useState<ConnectedItemSummary[]>([]);
  const [itemsLoading, setItemsLoading] = useState(true);
  const [browsing, setBrowsing] = useState(false);
  const [browseFiles, setBrowseFiles] = useState<BrowseFile[]>([]);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseError, setBrowseError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [adding, setAdding] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);

  // Same reasoning as IntegrationsPanel's own refresh() above: itemsLoading
  // already starts true, so no synchronous setState is needed here for the
  // mount-effect call below to satisfy react-hooks/set-state-in-effect.
  const refreshItems = useCallback(() => {
    listIntegrationItems(integration.id)
      .then(setItems)
      .catch(() => {})
      .finally(() => setItemsLoading(false));
  }, [integration.id]);

  useEffect(() => {
    refreshItems();
  }, [refreshItems]);

  const connectedIds = new Set(items.map((i) => i.external_id));

  async function handleBrowse() {
    setBrowsing((v) => !v);
    if (browsing) return; // was open, just close it
    setBrowseLoading(true);
    setBrowseError(null);
    try {
      const page = await browseIntegration(integration.id);
      setBrowseFiles(page.files);
    } catch {
      setBrowseError("Couldn't list files from Google. Please try again.");
    } finally {
      setBrowseLoading(false);
    }
  }

  function toggleSelected(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleAddSelected() {
    const chosen = browseFiles.filter((f) => selected.has(f.id));
    if (chosen.length === 0) return;
    setAdding(true);
    try {
      await selectIntegrationItems(integration.id, chosen);
      setSelected(new Set());
      setBrowsing(false);
      refreshItems();
      onChanged();
    } catch {
      setBrowseError("Couldn't add the selected files. Please try again.");
    } finally {
      setAdding(false);
    }
  }

  async function handleSync() {
    setSyncing(true);
    try {
      const updated = await syncIntegration(integration.id);
      setItems(updated);
      onChanged();
    } catch {
      // Individual item errors surface via each item's own sync_status/last_error.
    } finally {
      setSyncing(false);
    }
  }

  async function handleDisconnect() {
    setDisconnecting(true);
    try {
      await disconnectIntegration(integration.id);
      onChanged();
    } catch {
      setDisconnecting(false);
      setConfirmDisconnect(false);
    }
  }

  return (
    <div className="rounded-xl border border-[var(--border)] p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-[var(--text-primary)]">Google Drive &amp; Sheets</p>
          <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
            Connected {new Date(integration.connected_at).toLocaleDateString()}
            {integration.last_synced_at ? ` · last synced ${new Date(integration.last_synced_at).toLocaleString()}` : ""}
            {" · "}
            {integration.item_count} item{integration.item_count === 1 ? "" : "s"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={handleBrowse}>
            {browsing ? "Close" : "Browse & Select"}
          </Button>
          <Button variant="secondary" onClick={handleSync} disabled={syncing || items.length === 0}>
            {syncing ? <Spinner /> : null} {syncing ? "Syncing…" : "Sync Now"}
          </Button>
          {confirmDisconnect ? (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-[var(--text-muted)]">Disconnect?</span>
              <button
                onClick={handleDisconnect}
                disabled={disconnecting}
                className="font-medium text-[var(--status-critical)] hover:underline disabled:opacity-40"
              >
                {disconnecting ? "Disconnecting…" : "Yes"}
              </button>
              <button onClick={() => setConfirmDisconnect(false)} className="font-medium text-[var(--text-secondary)] hover:underline">
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirmDisconnect(true)}
              className="text-xs font-medium text-[var(--status-critical)] hover:underline"
            >
              Disconnect
            </button>
          )}
        </div>
      </div>

      {browsing && (
        <div className="mt-4 rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
          {browseError && <ErrorBanner message={browseError} />}
          {browseLoading ? (
            <div className="flex items-center gap-2 py-3 text-sm text-[var(--text-secondary)]"><Spinner /> Listing your Drive files…</div>
          ) : browseFiles.length === 0 ? (
            <p className="py-2 text-sm text-[var(--text-secondary)]">No files found in this Google account.</p>
          ) : (
            <>
              <div className="max-h-64 overflow-y-auto">
                {browseFiles.map((f) => {
                  const alreadyConnected = connectedIds.has(f.id);
                  return (
                    <label
                      key={f.id}
                      className={`flex items-center gap-2 rounded px-2 py-1.5 text-sm ${alreadyConnected ? "opacity-40" : "hover:bg-[var(--surface-1)]"}`}
                    >
                      <input
                        type="checkbox"
                        checked={selected.has(f.id) || alreadyConnected}
                        disabled={alreadyConnected}
                        onChange={() => toggleSelected(f.id)}
                        className="h-4 w-4 rounded border-[var(--border)]"
                      />
                      <span className="flex-1 truncate text-[var(--text-primary)]">{f.name}</span>
                      <span className="shrink-0 text-xs uppercase text-[var(--text-muted)]">
                        {f.external_kind === "sheet" ? "Sheet" : "File"}
                      </span>
                      {alreadyConnected && <span className="shrink-0 text-xs text-[var(--text-muted)]">Added</span>}
                    </label>
                  );
                })}
              </div>
              <div className="mt-3 flex justify-end">
                <Button onClick={handleAddSelected} disabled={selected.size === 0 || adding}>
                  {adding ? "Adding…" : `Add ${selected.size || ""} Selected`.trim()}
                </Button>
              </div>
            </>
          )}
        </div>
      )}

      {!itemsLoading && items.length > 0 && (
        <div className="mt-4 flex flex-col divide-y divide-[var(--border)]">
          {items.map((item) => (
            <div key={item.id} className="flex items-center justify-between gap-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm text-[var(--text-primary)]">{item.display_name}</p>
                {item.last_error && <p className="mt-0.5 truncate text-xs text-[var(--status-critical)]">{item.last_error}</p>}
              </div>
              <SyncStatusBadge status={item.sync_status} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

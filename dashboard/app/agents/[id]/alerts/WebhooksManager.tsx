"use client";

/**
 * WebhooksManager — Sprint UX-5.10-6.
 *
 * Client component. Adds + lists + removes webhook endpoints for one
 * agent. Mirrors AnchorsManager's pattern: never imports `@/lib/api`
 * (server-only via next/headers); instead fetches our own Next route
 * handlers at `/api/agents/[id]/webhooks/*`.
 *
 * After a successful create, we show the plaintext secret in a
 * dismissible banner. The user MUST copy it before navigating away —
 * we only store the hash, so a lost secret means deleting + recreating.
 */
import { useState } from "react";

interface WebhookRow {
  id: string;
  url: string;
  is_active: boolean;
  last_delivery_at: string | null;
  last_delivery_status: number | null;
  last_delivery_error: string | null;
  created_at: string | null;
}

interface Props {
  agentId: string;
  initialWebhooks: WebhookRow[];
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || `${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

function formatLastDelivery(row: WebhookRow): string {
  if (!row.last_delivery_at) return "Never fired";
  const date = new Date(row.last_delivery_at);
  const ago = Math.max(0, Date.now() - date.getTime());
  const mins = Math.floor(ago / 60000);
  const when =
    mins < 1
      ? "just now"
      : mins < 60
        ? `${mins}m ago`
        : `${Math.floor(mins / 60)}h ago`;
  if (row.last_delivery_status && row.last_delivery_status >= 200 && row.last_delivery_status < 300) {
    return `${when} · ${row.last_delivery_status} OK`;
  }
  if (row.last_delivery_status) {
    return `${when} · HTTP ${row.last_delivery_status}`;
  }
  return `${when} · ${row.last_delivery_error ?? "error"}`;
}

export function WebhooksManager({ agentId, initialWebhooks }: Props) {
  const [webhooks, setWebhooks] = useState<WebhookRow[]>(initialWebhooks);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revealedSecret, setRevealedSecret] = useState<{
    webhookId: string;
    secret: string;
  } | null>(null);

  async function handleAdd() {
    if (!url.trim()) return;
    setError(null);
    setBusy(true);
    try {
      const res = await fetch(
        `/api/agents/${encodeURIComponent(agentId)}/webhooks`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: url.trim() }),
        },
      );
      const data = await jsonOrThrow<{
        webhook: WebhookRow;
        secret: string;
      }>(res);
      setWebhooks((prev) => [data.webhook, ...prev]);
      setRevealedSecret({
        webhookId: data.webhook.id,
        secret: data.secret,
      });
      setUrl("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(webhookId: string) {
    setError(null);
    setBusy(true);
    try {
      const res = await fetch(
        `/api/agents/${encodeURIComponent(agentId)}/webhooks/${encodeURIComponent(webhookId)}`,
        { method: "DELETE" },
      );
      if (!res.ok && res.status !== 204) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || `${res.status} ${res.statusText}`);
      }
      setWebhooks((prev) => prev.filter((w) => w.id !== webhookId));
      if (revealedSecret?.webhookId === webhookId) setRevealedSecret(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Reveal-once secret banner */}
      {revealedSecret && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/[0.06] p-4">
          <div className="text-sm font-medium">
            Save this secret now — it&apos;s shown only once.
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            Use it to validate <code>X-Metalins-Signature</code> on
            every delivery. If you lose it, delete this webhook and
            create a new one.
          </p>
          <pre className="mt-2 overflow-x-auto rounded bg-background p-3 text-xs">
            <code>{revealedSecret.secret}</code>
          </pre>
          <div className="mt-2 text-right">
            <button
              type="button"
              onClick={() => setRevealedSecret(null)}
              className="text-xs text-muted-foreground hover:underline"
            >
              I&apos;ve saved it · dismiss
            </button>
          </div>
        </div>
      )}

      {/* Add form */}
      <section className="rounded-lg border bg-card p-6">
        <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Add webhook endpoint
        </div>
        <p className="text-sm text-muted-foreground">
          Paste any HTTPS URL we can POST to. We&apos;ll send a JSON
          body and sign it with HMAC-SHA256. Use any endpoint that {/* metalins:internal-allowed — outgoing-webhook signature spec; customer needs the algorithm name to implement verification on their endpoint */}
          accepts POST — your own ingest, a relay service, an
          internal alert bus.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <input
            type="url"
            placeholder="https://hooks.example.com/metalins"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="min-w-0 flex-1 rounded-md border bg-background px-3 py-2 text-sm"
          />
          <button
            type="button"
            onClick={handleAdd}
            disabled={busy || !url.trim()}
            className="rounded-md bg-foreground px-3 py-2 text-sm font-medium text-background disabled:opacity-50"
          >
            {busy ? "Adding…" : "Add webhook"}
          </button>
        </div>
      </section>

      {/* Existing list — Sprint UX-5.11 R1 / Diana history closer.
          Renamed from "Active webhooks" to "Endpoints & recent activity"
          so the list reads as the activity log it is: each row's
          "last delivery" line IS the most recent fire on that endpoint.
          Full per-endpoint history (multiple events) ships with the
          email provider; for V1 the last-fire snapshot covers Diana's
          buy-decision case. See /docs/reference/webhooks for
          the payload shape. */}
      <section className="rounded-lg border bg-card p-6">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Endpoints &amp; recent activity
          </div>
          <a
            href="/drift-engine/docs/reference/webhooks"
            className="text-xs text-muted-foreground hover:text-foreground hover:underline"
          >
            Payload reference →
          </a>
        </div>
        <p className="mb-3 text-xs text-muted-foreground">
          Each row shows the most recent fire on that endpoint (status,
          timestamp, error if any). Full per-endpoint history ships with
          the email provider.
        </p>
        {webhooks.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No endpoints yet. Add one above to receive state-change alerts.
          </p>
        ) : (
          <ul className="space-y-2">
            {webhooks.map((w) => (
              <li
                key={w.id}
                className="flex items-start justify-between gap-3 rounded-md border bg-background/60 p-3 text-sm"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate font-mono text-xs">
                    {w.url}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {formatLastDelivery(w)}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => handleDelete(w.id)}
                  disabled={busy}
                  className="shrink-0 text-xs text-destructive hover:underline disabled:opacity-50"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

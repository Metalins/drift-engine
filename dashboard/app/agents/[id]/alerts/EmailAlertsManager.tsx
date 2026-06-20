"use client";

/**
 * EmailAlertsManager — Sprint UX-5.11 / Diana round 0 (bug-diana-1).
 *
 * Client component. Lets the customer set a single recipient email per
 * agent. The recipient is stored on the agent's `metadata.alert_email`
 * so no schema migration is needed — the backend already accepts
 * arbitrary JSON metadata. Sending the actual email is wired in once
 * the magic-link email provider lands; until then, this UI saves the
 * recipient + shows a "pending provider" hint so the customer knows
 * the address is stored but no mail will go out yet.
 *
 * Hits the existing PATCH /v1/agents/{id} via the proxy route — the
 * same path AgentSettings uses for name/model/framework edits.
 */
import { useState } from "react";

interface Props {
  agentId: string;
  initialEmail: string | null;
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || `${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function EmailAlertsManager({ agentId, initialEmail }: Props) {
  const [email, setEmail] = useState(initialEmail ?? "");
  const [savedEmail, setSavedEmail] = useState<string | null>(initialEmail);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const trimmed = email.trim();
  const looksValid = trimmed === "" || EMAIL_RE.test(trimmed);
  const dirty = trimmed !== (savedEmail ?? "");

  async function patchMetadataEmail(nextEmail: string | null) {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      // The PATCH endpoint merges metadata, so we only send the field
      // we want to change. Sending null explicitly clears it.
      const body: Record<string, unknown> = {
        metadata: { alert_email: nextEmail },
      };
      const res = await fetch(
        `/api/agents/${encodeURIComponent(agentId)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      );
      await jsonOrThrow(res);
      setSavedEmail(nextEmail);
      setNotice(
        nextEmail
          ? "Recipient saved. Email delivery turns on once our email provider lands; until then this address is stored but no mail goes out yet."
          : "Recipient cleared. We won't email anyone for this agent.",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleSave() {
    if (!looksValid) {
      setError("That doesn't look like a valid email address.");
      return;
    }
    await patchMetadataEmail(trimmed || null);
  }

  async function handleClear() {
    setEmail("");
    await patchMetadataEmail(null);
  }

  return (
    <section className="rounded-lg border bg-card p-6">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Email alerts
      </div>
      <p className="text-sm text-muted-foreground">
        One recipient address for state-change alerts on this agent.
        We&apos;ll email when the verification state shifts to{" "}
        <em>caution</em> or <em>action</em>. Email delivery is wiring
        up — your address is stored today, mail starts going out the
        moment the provider is live.
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        <input
          type="email"
          inputMode="email"
          placeholder="oncall@yourteam.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={busy}
          className="min-w-0 flex-1 rounded-md border bg-background px-3 py-2 text-sm disabled:opacity-50"
        />
        <button
          type="button"
          onClick={handleSave}
          disabled={busy || !dirty || !looksValid}
          className="rounded-md bg-foreground px-3 py-2 text-sm font-medium text-background disabled:opacity-50"
        >
          {busy ? "Saving…" : savedEmail ? "Update" : "Save"}
        </button>
        {savedEmail && (
          <button
            type="button"
            onClick={handleClear}
            disabled={busy}
            className="rounded-md border px-3 py-2 text-sm hover:bg-accent disabled:opacity-50"
          >
            Clear
          </button>
        )}
      </div>

      {!looksValid && (
        <p className="mt-2 text-xs text-destructive">
          Enter a valid email address.
        </p>
      )}

      {error && (
        <p className="mt-2 text-xs text-destructive">{error}</p>
      )}

      {notice && (
        <p className="mt-2 text-xs text-muted-foreground">{notice}</p>
      )}

      {savedEmail && !error && !notice && (
        <p className="mt-3 text-xs text-muted-foreground">
          Currently alerting:{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">
            {savedEmail}
          </code>
        </p>
      )}
    </section>
  );
}

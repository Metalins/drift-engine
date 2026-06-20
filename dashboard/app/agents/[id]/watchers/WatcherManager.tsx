"use client";

/**
 * WatcherManager — Client Component for the 2-step wizard + list.
 *
 * Step 1: pick a platform (only enabled ones from `supported_platforms` are
 *         clickable; others render as "soon" tiles).
 * Step 2: paste bot token + optional display name; submit → POST to API.
 *
 * Below the wizard, render the existing watchers with state badges and
 * pause/resume/delete actions.
 *
 * Type-only imports from `@/lib/api` to keep this client bundle free of
 * server-only modules (next/headers, supabase server client, etc.).
 * All mutations go through the Next.js proxy routes under /api/.
 *
 * NOTE: this component is page-agnostic. Wizard-specific chrome
 * (progress breadcrumb, "Continue to verify" CTA) lives in the
 * dedicated wizard page at `/watchers/setup`, which renders this
 * component unchanged. Same pattern as `/mcp` + `/mcp/setup`.
 */
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { WatcherPlatform, WatcherSummary } from "@/lib/api";
import { displayWatcherState } from "@/lib/display-messages";

interface Props {
  agentId: string;
  initialWatchers: WatcherSummary[];
  supportedPlatforms: string[];
}

const PLATFORMS: {
  id: WatcherPlatform;
  label: string;
  helper: string;
  tokenHint: string;
}[] = [
  {
    id: "telegram",
    label: "Telegram",
    helper: "Bot from @BotFather — paste the API token.",
    tokenHint: "e.g. 1234567890:AAFxxxxxxxxxxxxxxxxxxxxxxxxxx",
  },
  {
    id: "discord",
    label: "Discord",
    helper: "Bot Token from the Developer Portal — coming soon.",
    tokenHint: "Bot xxxxxxxx.xxxxxx.xxxxxxxxxxxx",
  },
  {
    id: "slack",
    label: "Slack",
    helper: "Bot User OAuth Token — coming soon.",
    tokenHint: "xoxb-...",
  },
  {
    id: "x",
    label: "X (Twitter)",
    helper: "API v2 Bearer — coming soon (paid tier required).",
    tokenHint: "Bearer xxxxxxxx",
  },
];

async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

async function apiDelete(path: string): Promise<void> {
  const res = await fetch(path, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? `HTTP ${res.status}`);
  }
}

export function WatcherManager({
  agentId,
  initialWatchers,
  supportedPlatforms,
}: Props) {
  const router = useRouter();
  const [, startTransition] = useTransition();
  const [watchers, setWatchers] = useState(initialWatchers);

  // Wizard state.
  const [step, setStep] = useState<"closed" | "platform" | "creds">("closed");
  const [chosen, setChosen] = useState<WatcherPlatform | null>(null);
  const [token, setToken] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Sprint 6.5 — type-the-name disconnect confirmation (replaces the
  // browser confirm() that was here originally). The user must type the
  // watcher's display name (or platform label fallback) to enable the
  // destructive action. Same pattern as MCP / revoke.
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [disconnectError, setDisconnectError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const isSupported = (p: WatcherPlatform) => supportedPlatforms.includes(p);

  const openWizard = () => {
    setStep("platform");
    setChosen(null);
    setToken("");
    setDisplayName("");
    setError(null);
  };

  const closeWizard = () => setStep("closed");

  const submit = async () => {
    if (!chosen) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await apiPost<{ watcher: WatcherSummary }>(
        `/api/agents/${encodeURIComponent(agentId)}/watchers`,
        {
          platform: chosen,
          token: token.trim(),
          display_name: displayName.trim() || undefined,
        },
      );
      setWatchers((cur) => [res.watcher, ...cur]);
      closeWizard();
      startTransition(() => router.refresh());
    } catch (e: unknown) {
      const msg =
        e instanceof Error
          ? e.message
          : "Could not connect bot. Check the token and try again.";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const onAction = async (
    id: string,
    action: "pause" | "resume" | "delete" | "retry",
  ) => {
    try {
      if (action === "pause") {
        const w = await apiPost<WatcherSummary>(
          `/api/watchers/${encodeURIComponent(id)}/pause`,
        );
        setWatchers((cur) => cur.map((x) => (x.id === id ? w : x)));
      } else if (action === "resume") {
        const w = await apiPost<WatcherSummary>(
          `/api/watchers/${encodeURIComponent(id)}/resume`,
        );
        setWatchers((cur) => cur.map((x) => (x.id === id ? w : x)));
      } else if (action === "retry") {
        // Sprint UX-5.10-8 — force an immediate poll. Backend runs the
        // same routine the scheduler runs, returns the updated row.
        const w = await apiPost<WatcherSummary>(
          `/api/watchers/${encodeURIComponent(id)}/retry`,
        );
        setWatchers((cur) => cur.map((x) => (x.id === id ? w : x)));
      } else {
        await apiDelete(`/api/watchers/${encodeURIComponent(id)}`);
        setWatchers((cur) => cur.filter((x) => x.id !== id));
      }
      startTransition(() => router.refresh());
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : `Could not ${action}.`;
      alert(msg);
    }
  };

  // Sprint 4.14 — one agent, one bot. Hide the "Connect" button if there's
  // already any watcher in the list. Customer must disconnect first to swap.
  const hasWatcher = watchers.length > 0;

  return (
    <div className="space-y-6">
      {/* ----- Wizard launcher --------------------------------------- */}
      {step === "closed" && !hasWatcher && (
        <button
          onClick={openWizard}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          + Connect a bot
        </button>
      )}
      {step === "closed" && hasWatcher && (
        <div className="rounded-md border bg-muted/30 p-4 text-sm text-muted-foreground">
          One agent, one bot. To connect a different one, disconnect the
          current bot below — or create a new agent for the second bot.
        </div>
      )}

      {/* ----- Step 1: pick platform --------------------------------- */}
      {step === "platform" && (
        <div className="space-y-4 rounded-xl border bg-card p-6">
          <div className="flex items-center justify-between">
            <h3 className="font-medium">Choose a platform</h3>
            <button
              onClick={closeWizard}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              Cancel
            </button>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {PLATFORMS.map((p) => {
              const enabled = isSupported(p.id);
              return (
                <button
                  key={p.id}
                  disabled={!enabled}
                  onClick={() => {
                    setChosen(p.id);
                    setStep("creds");
                  }}
                  className={`rounded-lg border p-4 text-left transition-colors ${
                    enabled
                      ? "bg-card hover:border-foreground/40"
                      : "cursor-not-allowed bg-muted/20 opacity-60"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{p.label}</span>
                    {!enabled && (
                      <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium uppercase text-muted-foreground">
                        Soon
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {p.helper}
                  </p>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* ----- Step 2: token + name ---------------------------------- */}
      {step === "creds" && chosen && (
        <div className="space-y-4 rounded-xl border bg-card p-6">
          <div className="flex items-center justify-between">
            <h3 className="font-medium">
              Connect {PLATFORMS.find((p) => p.id === chosen)?.label}
            </h3>
            <button
              onClick={() => setStep("platform")}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              ← Change platform
            </button>
          </div>

          <div className="space-y-3">
            <label className="block">
              <span className="text-sm font-medium">Bot token</span>
              <input
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder={PLATFORMS.find((p) => p.id === chosen)?.tokenHint}
                className="mt-1 block w-full rounded-md border bg-background px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
              <span className="mt-1 block text-xs text-muted-foreground">
                Encrypted at rest with AES-256-GCM. We never log, never echo back.
              </span>
            </label>

            <label className="block">
              <span className="text-sm font-medium">
                Display name <span className="text-muted-foreground">(optional)</span>
              </span>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="e.g. @mybot — production"
                maxLength={200}
                className="mt-1 block w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </label>
          </div>

          {error && (
            <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <button
              onClick={closeWizard}
              disabled={submitting}
              className="rounded-md border px-3 py-1.5 text-sm hover:bg-accent"
            >
              Cancel
            </button>
            <button
              onClick={submit}
              disabled={submitting || token.trim().length < 10}
              className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
            >
              {submitting ? "Connecting..." : "Connect"}
            </button>
          </div>
        </div>
      )}

      {/* ----- Watcher (singular, V1 = 1 bot per agent) -------------- */}
      <div className="space-y-2">
        <h3 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          Bot connection
        </h3>
        {watchers.length === 0 && step === "closed" && (
          <div className="rounded-md border bg-card p-6 text-sm text-muted-foreground">
            No bot connected yet. Click <em>+ Connect a bot</em> to add one.
            The first poll runs within 60 seconds; identity score appears
            after ~10 messages.
          </div>
        )}
        <ul className="space-y-2">
          {watchers.map((w) => (
            <li
              key={w.id}
              className="rounded-lg border bg-card p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">
                      {w.display_name || PLATFORMS.find((p) => p.id === w.platform)?.label}
                    </span>
                    <StateBadge state={w.state} />
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    <span className="uppercase">{w.platform}</span>{" "}
                    · {w.events_logged} events logged
                    {w.last_polled_at && (
                      <> · last poll {new Date(w.last_polled_at).toLocaleTimeString()}</>
                    )}
                  </div>
                  {w.state === "pending" && (
                    <div className="mt-2 rounded border bg-muted/40 p-2 text-xs text-muted-foreground">
                      <strong className="text-foreground">Waiting for first poll.</strong>{" "}
                      The batch runs every 60s. If your server just deployed, the
                      first run can take a minute or two. Send a message to your
                      bot to give it something to log.
                    </div>
                  )}
                  {w.error_message && (
                    <div className="mt-2 rounded border border-destructive/30 bg-destructive/5 p-2 text-xs">
                      <div className="font-medium text-destructive">
                        {humanizeWatcherError(w.error_message)}
                      </div>
                      <div className="mt-1 text-muted-foreground/80">
                        <span className="font-mono">{w.error_message}</span>
                      </div>
                      {w.state === "error" && (
                        <button
                          type="button"
                          onClick={() => onAction(w.id, "retry")}
                          className="mt-2 rounded-md border border-destructive/40 px-2 py-1 text-[11px] font-medium text-destructive hover:bg-destructive/10"
                        >
                          Retry now
                        </button>
                      )}
                    </div>
                  )}
                </div>
                <div className="flex shrink-0 gap-2">
                  {w.state === "paused" ? (
                    <button
                      onClick={() => onAction(w.id, "resume")}
                      className="rounded-md border px-2 py-1 text-xs hover:bg-accent"
                    >
                      Resume
                    </button>
                  ) : (
                    <button
                      onClick={() => onAction(w.id, "pause")}
                      className="rounded-md border px-2 py-1 text-xs hover:bg-accent"
                    >
                      Pause
                    </button>
                  )}
                  <button
                    onClick={() => {
                      setConfirmingId(w.id);
                      setConfirmText("");
                      setDisconnectError(null);
                    }}
                    className="rounded-md border border-destructive/40 px-2 py-1 text-xs text-destructive hover:bg-destructive/10"
                  >
                    Disconnect
                  </button>
                </div>
              </div>

              {confirmingId === w.id && (
                <DisconnectConfirm
                  watcherLabel={
                    w.display_name ||
                    PLATFORMS.find((p) => p.id === w.platform)?.label ||
                    w.platform
                  }
                  confirmText={confirmText}
                  setConfirmText={setConfirmText}
                  error={disconnectError}
                  onCancel={() => {
                    setConfirmingId(null);
                    setConfirmText("");
                    setDisconnectError(null);
                  }}
                  onConfirm={async () => {
                    try {
                      await onAction(w.id, "delete");
                      setConfirmingId(null);
                      setConfirmText("");
                    } catch (err) {
                      setDisconnectError(
                        err instanceof Error ? err.message : "Unknown error",
                      );
                    }
                  }}
                />
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

// Sprint UX-5.10-8 — translate raw adapter errors into something a
// human can act on. Keep the keys conservative: anything we don't
// recognise still surfaces the raw message below so a power user can
// diagnose it themselves.
function humanizeWatcherError(raw: string): string {
  const m = raw.toLowerCase();
  if (m.includes("unauthorized") || m.includes(" 401")) {
    return "Telegram rejected the bot token. It may have been revoked or regenerated — disconnect and reconnect with a fresh token.";
  }
  if (m.includes("connection reset") || m.includes("connectionresetbyperr")) {
    return "Telegram's API was briefly unreachable. We'll retry automatically; click 'Retry now' for an immediate attempt.";
  }
  if (m.includes("timeout") || m.includes("timed out")) {
    return "Telegram took too long to respond. Click 'Retry now' to try again — if it keeps failing for >15 minutes their API may be degraded.";
  }
  if (m.includes("network") || m.includes("urlerror") || m.includes("dns")) {
    return "Network error reaching Telegram. Click 'Retry now'. If it persists, check the Telegram API status page.";
  }
  if (m.includes("telegram_not_ok")) {
    return "Telegram returned an error. The token may not have the right permissions, or the bot may be blocked.";
  }
  if (m.includes("rate") || m.includes(" 429")) {
    return "We hit Telegram's rate limit. The watcher will resume automatically once the limit window resets.";
  }
  return "The watcher couldn't complete its last poll. Click 'Retry now' to try again.";
}

function DisconnectConfirm({
  watcherLabel,
  confirmText,
  setConfirmText,
  error,
  onCancel,
  onConfirm,
}: {
  watcherLabel: string;
  confirmText: string;
  setConfirmText: (v: string) => void;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const canDisconnect = confirmText === watcherLabel;
  return (
    <div className="mt-3 space-y-3 rounded-md border border-destructive/40 bg-background p-3">
      <p className="text-xs text-muted-foreground">
        Disconnect this bot? Events already logged stay. To confirm, type{" "}
        <code className="rounded bg-muted px-1 py-0.5 text-[11px] font-medium text-foreground">
          {watcherLabel}
        </code>{" "}
        below.
      </p>
      <input
        type="text"
        value={confirmText}
        onChange={(e) => setConfirmText(e.target.value)}
        placeholder={watcherLabel}
        autoFocus
        className="block w-full rounded-md border bg-background px-3 py-1.5 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-destructive"
      />
      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
          {error}
        </div>
      )}
      <div className="flex justify-end gap-2">
        <button
          onClick={onCancel}
          className="rounded-md border px-2.5 py-1 text-xs hover:bg-accent"
        >
          Cancel
        </button>
        <button
          onClick={onConfirm}
          disabled={!canDisconnect}
          className="rounded-md bg-destructive px-2.5 py-1 text-xs font-medium text-destructive-foreground hover:bg-destructive/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Disconnect bot
        </button>
      </div>
    </div>
  );
}

function StateBadge({ state }: { state: WatcherSummary["state"] }) {
  const styles =
    state === "active"
      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
      : state === "pending"
        ? "bg-sky-500/10 text-sky-700 dark:text-sky-300"
        : state === "error"
          ? "bg-destructive/10 text-destructive"
          : "bg-muted text-muted-foreground";
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium uppercase ${styles}`}>
      {displayWatcherState(state)}
    </span>
  );
}

"use client";

/**
 * ReissueSecretPanel — UX-5.17 #505.
 *
 * Lives in the agent's danger zone (rendered by AgentSettings). A full
 * re-key: the agent gets a brand-new agent_secret and its cryptographic
 * verification restarts from a fresh genesis. The hash chain is rooted
 * in the secret, so a new secret unavoidably means a new chain — past
 * verification history is cleared and the tier resets. The agent keeps
 * its id / name / slug / keys / anchors / connected bots.
 *
 * Recovery flow: a customer who created an agent in the dashboard and
 * lost the one-time secret (or never copied it) uses this to get a
 * fresh one for the SDK / HTTP API round-trip path.
 *
 * Confirm-by-name guard, same as revoke / reset-baseline. Amber, not
 * destructive-red: re-keying is recoverable in spirit (the agent lives
 * on), unlike the permanent delete below it.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { KeyRound } from "lucide-react";
import { SecretReveal } from "./SecretReveal";

type Status =
  | { kind: "idle" }
  | { kind: "working" }
  | { kind: "error"; message: string }
  | { kind: "done"; secret: string };

export function ReissueSecretPanel({
  agentId,
  agentName,
}: {
  agentId: string;
  agentName: string;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  const canSubmit = confirmText === agentName && status.kind !== "working";

  async function handleReissue() {
    if (confirmText !== agentName) return;
    setStatus({ kind: "working" });
    try {
      const res = await fetch(
        `/api/agents/${encodeURIComponent(agentId)}/reissue-secret`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirmation_name: confirmText }),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      const body = await res.json();
      setStatus({ kind: "done", secret: body.agent_secret as string });
      // The tier / verification history just reset — refresh the rest
      // of the page. This panel keeps its own state (client component),
      // so the revealed secret stays put.
      router.refresh();
    } catch (err) {
      setStatus({
        kind: "error",
        message: err instanceof Error ? err.message : "Unknown error",
      });
    }
  }

  return (
    <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-6">
      <div className="flex items-start gap-3">
        <KeyRound size={20} className="mt-0.5 shrink-0 text-amber-600" />
        <div className="flex-1 space-y-2">
          <h2 className="font-medium text-foreground">Re-issue agent secret</h2>
          <p className="text-sm text-muted-foreground">
            Lost the secret, or never copied it? Re-issuing gives the
            agent a <strong>brand-new secret</strong> for the SDK / HTTP
            API. Because verification is built on that secret, the
            agent&apos;s <strong>verification history is cleared</strong>{" "}
            and its tier resets — it re-earns trust from scratch. Its
            id, name, verify link, API keys and connected bot stay
            untouched.
          </p>

          {status.kind === "done" ? (
            <div className="space-y-3 pt-1">
              <SecretReveal
                secret={status.secret}
                caption="Your new agent secret. Store it now — we can't show it again. The old secret no longer works."
              />
              <p className="text-xs text-muted-foreground">
                Update anywhere the old secret was used, then verify
                from your code to start rebuilding the history.
              </p>
            </div>
          ) : !open ? (
            <button
              type="button"
              onClick={() => setOpen(true)}
              className="mt-2 rounded-md border border-amber-500/50 px-3 py-1.5 text-sm font-medium text-amber-700 hover:bg-amber-500/10 dark:text-amber-400"
            >
              Re-issue secret
            </button>
          ) : (
            <div className="mt-3 space-y-3 rounded-md border border-amber-500/40 bg-background p-4">
              <p className="text-sm">
                To confirm, type{" "}
                <code className="rounded bg-muted px-1 py-0.5 text-xs font-medium text-foreground">
                  {agentName}
                </code>{" "}
                below.
              </p>
              <input
                type="text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder={agentName}
                autoFocus
                className="block w-full rounded-md border bg-background px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-amber-500"
              />
              {status.kind === "error" && (
                <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
                  {status.message}
                </div>
              )}
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setOpen(false);
                    setConfirmText("");
                    setStatus({ kind: "idle" });
                  }}
                  disabled={status.kind === "working"}
                  className="rounded-md border px-3 py-1.5 text-sm hover:bg-accent"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleReissue}
                  disabled={!canSubmit}
                  className="rounded-md bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-600/90 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {status.kind === "working"
                    ? "Re-issuing…"
                    : "Re-issue secret"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

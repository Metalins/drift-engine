"use client";

/**
 * SecretReveal — UX-5.17 #931 / #505.
 *
 * Shared one-time-secret display. The agent secret is the credential
 * the SDK / HTTP API uses to answer verification checks; the server
 * stores it but never returns it again after it's first handed out.
 * This component is the single place that surfaces it: at agent
 * creation (/agents/new) and after a re-issue (agent settings danger
 * zone). Copy button + a clear "we can't show this again" caption so
 * the customer saves it before navigating away.
 */
import { useState } from "react";
import { Check, Copy, KeyRound } from "lucide-react";

export function SecretReveal({
  secret,
  caption,
}: {
  secret: string;
  /** Override the default "store this, shown once" caption. */
  caption?: string;
}) {
  const [copied, setCopied] = useState(false);

  return (
    <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-4">
      <div className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-amber-700 dark:text-amber-400">
        <KeyRound size={13} />
        Agent secret — shown once
      </div>
      <div className="mt-2 flex items-stretch gap-2">
        <code className="flex-1 overflow-x-auto whitespace-nowrap rounded bg-background px-3 py-2 font-mono text-xs">
          {secret}
        </code>
        <button
          type="button"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(secret);
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1800);
            } catch {
              /* ignore — older browsers without a secure context */
            }
          }}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md border bg-background px-2.5 py-1 text-xs font-medium hover:bg-accent"
        >
          {copied ? (
            <>
              <Check size={12} className="text-emerald-600" />
              Copied
            </>
          ) : (
            <>
              <Copy size={12} />
              Copy
            </>
          )}
        </button>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        {caption ??
          "Store this in a password manager or your app's secret store now — we can't show it again. Lost it? Re-issue a new one from the agent's settings."}
      </p>
    </div>
  );
}

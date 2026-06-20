/**
 * ApiKeyOnboarding — prominent API-key surface at the top of /dashboard.
 *
 * ux-1 (2026-06-04): the fastest path to first event is getting the API
 * key into the SDK. Until now the key lived behind /settings → /keys,
 * which a brand-new user has no reason to find. This card brings it to
 * the fold:
 *
 *   • No active key  → a primary onboarding card. One click mints a
 *     customer-wide key and reveals the secret + a ready-to-paste SDK
 *     snippet, copyable in one click. (QA: visible in <30s, copyable.)
 *   • Has active key → a slim reassurance strip linking to /keys, with a
 *     "generate a new key" affordance for when the secret is needed again
 *     (secrets are shown once and never retrievable — we don't pretend to
 *     re-display an existing one).
 *
 * Client component: the create flow needs state for the one-time secret,
 * mirroring CustomerKeysManager. Talks to the same
 * /api/customers/me/api-keys proxy.
 */
"use client";

import Link from "next/link";
import { useState } from "react";
import { KeyRound, Copy, Check, ChevronRight } from "lucide-react";
import type { CustomerKeyCreated } from "@/lib/api";

interface Props {
  /** The customer's most relevant active key, or null if they have none. */
  activeKey: { name: string | null; created_at: string | null } | null;
}

type CreateState =
  | { kind: "idle" }
  | { kind: "creating" }
  | { kind: "created"; key: CustomerKeyCreated }
  | { kind: "error"; message: string };

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        } catch {
          /* clipboard blocked — the value is still visible to select */
        }
      }}
      className="inline-flex shrink-0 items-center gap-1.5 rounded-md border bg-background px-2.5 py-1.5 text-xs font-medium hover:bg-accent"
      aria-label={label}
    >
      {copied ? (
        <>
          <Check size={13} aria-hidden /> Copied
        </>
      ) : (
        <>
          <Copy size={13} aria-hidden /> Copy
        </>
      )}
    </button>
  );
}

/** The revealed-secret panel, shared by both states after a key is minted. */
function CreatedKeyPanel({ created }: { created: CustomerKeyCreated }) {
  const snippet = `from metalins_drift import MetalinsClient\n\nclient = MetalinsClient(api_key="${created.secret}")`;
  return (
    <div className="mt-4 space-y-3">
      <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3">
        <div className="text-sm font-medium">
          Copy your API key now — you won&apos;t see it again
        </div>
        <div className="mt-2 flex items-center gap-2">
          <code className="flex-1 truncate rounded bg-muted px-2 py-1.5 text-xs">
            {created.secret}
          </code>
          <CopyButton value={created.secret} label="Copy API key" />
        </div>
      </div>

      <div>
        <div className="mb-1 text-xs font-medium text-muted-foreground">
          Paste it into the SDK
        </div>
        <div className="flex items-start gap-2">
          <pre className="flex-1 overflow-x-auto rounded-md border bg-muted/60 p-3 text-xs leading-relaxed">
            {snippet}
          </pre>
          <CopyButton value={snippet} label="Copy SDK snippet" />
        </div>
      </div>

      <Link
        href="/keys"
        className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
      >
        Manage your keys <ChevronRight size={12} aria-hidden />
      </Link>
    </div>
  );
}

export function ApiKeyOnboarding({ activeKey }: Props) {
  const [state, setState] = useState<CreateState>({ kind: "idle" });

  async function generate() {
    setState({ kind: "creating" });
    try {
      const res = await fetch("/api/customers/me/api-keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: "Dashboard quickstart key",
          description: "Generated from the dashboard onboarding card.",
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      const key = (await res.json()) as CustomerKeyCreated;
      setState({ kind: "created", key });
    } catch (err) {
      setState({
        kind: "error",
        message: err instanceof Error ? err.message : "Unknown error",
      });
    }
  }

  // --- Has an active key: slim reassurance strip --------------------------- //
  if (activeKey) {
    return (
      <section className="rounded-xl border bg-card p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
              <KeyRound size={18} aria-hidden />
            </div>
            <div className="min-w-0">
              <div className="text-sm font-medium">
                API key active
                {activeKey.name ? (
                  <span className="text-muted-foreground">
                    {" "}
                    · {activeKey.name}
                  </span>
                ) : null}
              </div>
              <p className="text-xs text-muted-foreground">
                Use it in the SDK as{" "}
                <code className="rounded bg-muted px-1 py-0.5">
                  api_key=&quot;ml_live_…&quot;
                </code>
                . Secrets are shown once — generate a new one if you need to
                copy it again.
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {state.kind !== "created" && (
              <button
                type="button"
                onClick={generate}
                disabled={state.kind === "creating"}
                className="rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50"
              >
                {state.kind === "creating" ? "Generating…" : "Generate new key"}
              </button>
            )}
            <Link
              href="/keys"
              className="rounded-md bg-foreground px-3 py-1.5 text-xs font-medium text-background hover:bg-foreground/90"
            >
              Manage keys
            </Link>
          </div>
        </div>
        {state.kind === "created" && <CreatedKeyPanel created={state.key} />}
        {state.kind === "error" && (
          <p className="mt-3 text-xs text-destructive">{state.message}</p>
        )}
      </section>
    );
  }

  // --- No active key: prominent onboarding card ---------------------------- //
  return (
    <section className="rounded-2xl border border-primary/30 bg-primary/[0.04] p-6 md:p-8">
      <div className="flex items-start gap-4">
        <div className="mt-0.5 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
          <KeyRound size={22} aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-xl font-semibold tracking-tight md:text-2xl">
            Get your API key to start monitoring your agents
          </h2>
          <p className="mt-1.5 max-w-2xl text-sm text-muted-foreground">
            Your API key is what the SDK uses to send signed events. Generate
            one now and you&apos;re a copy-paste away from your first event.
          </p>

          {state.kind !== "created" && (
            <div className="mt-5 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={generate}
                disabled={state.kind === "creating"}
                className="inline-flex items-center gap-2 rounded-md bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                <KeyRound size={16} aria-hidden />
                {state.kind === "creating" ? "Generating…" : "Generate API key"}
              </button>
              <Link
                href="/keys"
                className="text-xs font-medium text-muted-foreground hover:text-foreground hover:underline"
              >
                Or manage keys manually
              </Link>
            </div>
          )}

          {state.kind === "created" && <CreatedKeyPanel created={state.key} />}
          {state.kind === "error" && (
            <p className="mt-3 text-sm text-destructive">{state.message}</p>
          )}
        </div>
      </div>
    </section>
  );
}

/**
 * ApiSetup — UX-5.17.API3 client body for /agents/[id]/api/setup,
 * reworked for the V2 SDK in UX-5.17.8 (#913).
 *
 * The SDK and the raw HTTP API are one integration — "SDK/API" — so
 * this page presents them together and lets the developer pick.
 *
 * UX-5.17 (shared snippets): the snippet code is NOT defined here. It
 * comes from the shared `lib/api-snippets` builders — the same source
 * the public docs render from — so the setup page and the docs never
 * drift apart. This page stays the thin per-agent action layer (mint a
 * key, copy a snippet with the real key + agent id inlined); the
 * conceptual detail lives in the docs, linked from each step.
 *
 * Two sections, no multi-step wizard (the API path has no client
 * config to edit):
 *   1. Mint / pick an API key.
 *   2. Connect from code — the `Agent.attach` snippet (key inlined,
 *      agent id pre-filled), with the raw HTTP call below it.
 *
 * The agent already exists (created in the dashboard), so the snippet
 * uses `Agent.attach(...)` — it adopts THIS agent rather than
 * registering a new one. `attach` needs the agent secret shown once at
 * creation (#931); if it was lost, the customer re-issues it from the
 * agent's settings (#505).
 */
"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, BookText } from "lucide-react";
import { KeyManager, type CreatedKey } from "../../keys/KeyManager";
import { ConfigBlock } from "../../mcp/ConfigBlock";
import type { ApiKeySummary } from "@/lib/api";
import {
  KEY_PLACEHOLDER,
  AGENT_SECRET_PLACEHOLDER,
  sdkAttachSnippet,
  eventCurlSnippet,
} from "@/lib/api-snippets";

/** The canonical API reference — every step links here for detail. */
const DOCS_API = "/drift-engine/docs/reference/developer-api";

interface Props {
  agentId: string;
  agentName: string;
  initialKeys: ApiKeySummary[];
  isWizard: boolean;
}

export function ApiSetup({
  agentId,
  agentName,
  initialKeys,
  isWizard,
}: Props) {
  const [mintedSecret, setMintedSecret] = useState<string | null>(null);

  const keyForSnippets = mintedSecret ?? KEY_PLACEHOLDER;
  const hasRealKey = mintedSecret != null;

  return (
    <div className="space-y-6">
      {/* ---- Step 1: API key ------------------------------------------ */}
      <section className="rounded-lg border bg-card p-6">
        <h2 className="text-base font-semibold tracking-tight">
          Step 1 — Create an API key
        </h2>
        <p className="mt-2 mb-4 text-sm text-muted-foreground">
          The API authenticates with a bearer token — one key works
          across every agent in your account. We&apos;ll keep the
          plaintext in memory only to inline it into the snippets below.{" "}
          <Link href={DOCS_API} className="font-medium text-foreground underline underline-offset-2">
            How auth and the event model work →
          </Link>
        </p>
        <KeyManager
          agentId={agentId}
          initialKeys={initialKeys}
          onKeyMinted={(k: CreatedKey) => setMintedSecret(k.secret)}
        />
        {mintedSecret && (
          <div className="mt-5 flex items-center justify-between rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs">
            <span>
              The plaintext key is held in memory and inlined in the
              snippets below. Click hide to clear it.
            </span>
            <button
              type="button"
              onClick={() => setMintedSecret(null)}
              className="rounded-md border bg-background px-2.5 py-1 text-xs font-medium hover:bg-accent"
            >
              Hide key
            </button>
          </div>
        )}
      </section>

      {/* ---- Step 2: Connect from code -------------------------------- */}
      <section className="rounded-lg border bg-card p-6">
        <h2 className="text-base font-semibold tracking-tight">
          Step 2 — Connect from your code
        </h2>
        <p className="mt-2 mb-4 text-sm text-muted-foreground">
          One block at startup, one call per turn — the SDK reports each
          interaction <em>and</em> answers verification checks for you.
          The snippet below has your key and agent id filled in.{" "}
          <Link href={DOCS_API} className="font-medium text-foreground underline underline-offset-2">
            SDK &amp; API reference →
          </Link>
        </p>

        <ConfigBlock
          title="Python SDK"
          description="Run pip install metalins-drift, then connect this agent:"
          code={sdkAttachSnippet({
            apiKey: keyForSnippets,
            agentId,
            agentSecret: AGENT_SECRET_PLACEHOLDER,
            name: agentName,
          })}
          copyLabel="Copy snippet"
          hasRealKey={hasRealKey}
        />

        {/* The agent secret is never recoverable from here — it was
            shown once at creation. Point the customer at re-issue. */}
        <div className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs">
          Replace{" "}
          <code className="rounded bg-muted px-1 py-0.5 font-medium text-foreground">
            {AGENT_SECRET_PLACEHOLDER}
          </code>{" "}
          with the agent secret shown once when you created this agent.
          Lost it?{" "}
          <Link
            href={`/agents/${encodeURIComponent(agentId)}`}
            className="underline"
          >
            Re-issue a new one
          </Link>{" "}
          from the agent&apos;s settings.
        </div>

        <details className="mt-5 rounded-md border bg-muted/30 p-4">
          <summary className="cursor-pointer text-sm font-medium hover:text-foreground">
            Any other language — call the HTTP API directly
          </summary>
          <div className="mt-3 space-y-3">
            <p className="text-xs text-muted-foreground">
              Every SDK call is a plain HTTPS request. This logs one
              interaction; on its own it covers event reporting. To also
              answer verification checks from another language,
              implement the check round-trip described in the{" "}
              <Link href={DOCS_API} className="underline">
                API reference
              </Link>
              .
            </p>
            <ConfigBlock
              title="curl"
              description={`POST an event to ${agentId}.`}
              code={eventCurlSnippet({ apiKey: keyForSnippets, agentId })}
              copyLabel="Copy command"
              hasRealKey={hasRealKey}
            />
          </div>
        </details>
      </section>

      {/* ---- Footer: docs + done -------------------------------------- */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link
          href={DOCS_API}
          className="inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-1.5 text-sm font-medium hover:bg-accent"
        >
          <BookText size={14} />
          Full API reference
        </Link>
        <Link
          href={`/agents/${encodeURIComponent(agentId)}${isWizard ? "?new=1" : ""}`}
          className="inline-flex items-center gap-1.5 rounded-md bg-foreground px-3.5 py-1.5 text-sm font-medium text-background hover:bg-foreground/90"
        >
          Go to your agent
          <ArrowRight size={14} />
        </Link>
      </div>
    </div>
  );
}

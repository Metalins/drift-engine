/**
 * /keys — customer-level API keys management.
 *
 * Sprint UX-5.11 / bug-andrea-3 (2026-05-17). Andrea v2.1 minted a key
 * via /agents/[id]/keys (which defaults to customer-wide, Sprint 6),
 * traffic flowed through it, but the agent-scoped listing showed
 * "0 keys" — a trust-breaking inconsistency she flagged as "as a user
 * I'd be nervous I can't rotate or revoke later." This page surfaces
 * BOTH customer-wide and agent-scoped keys side-by-side with explicit
 * scope badges so the listing matches reality.
 *
 * Server Component for the initial fetch; the create/revoke flow lives
 * in CustomerKeysManager (client) because it needs state for the
 * one-time secret display.
 */
import Link from "next/link";
import { ApiError, listCustomerKeys } from "@/lib/api";
import { CustomerKeysManager } from "./CustomerKeysManager";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "API keys",
};

export default async function KeysPage() {
  let initialKeys: Awaited<ReturnType<typeof listCustomerKeys>>["keys"] = [];
  let loadError: string | null = null;
  try {
    const res = await listCustomerKeys({ includeRevoked: true });
    initialKeys = res.keys;
  } catch (err) {
    loadError =
      err instanceof ApiError
        ? `${err.status} — ${err.message}`
        : err instanceof Error
          ? err.message
          : "Unknown error";
  }

  return (
    <main className="space-y-6">
      <div>
        <Link
          href="/dashboard"
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← Back to dashboard
        </Link>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">API keys</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          All keys for your account. Customer-wide keys can act on any of your
          agents (the right default for MCP clients that juggle several). Agent-scoped
          keys are locked to one agent and live under that agent&apos;s page too.
        </p>
      </div>

      {loadError && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          Could not load keys: {loadError}
        </div>
      )}

      <CustomerKeysManager initialKeys={initialKeys} />
    </main>
  );
}

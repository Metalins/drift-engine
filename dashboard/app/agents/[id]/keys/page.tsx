/**
 * /agents/[id]/keys — manage API keys scoped to one agent.
 *
 * Lists existing keys (metadata only, no secrets), with a button to create
 * a new one and a revoke button per row. Creating a key returns the raw
 * secret once — that one-time display lives in a Client Component
 * (see KeyManager) because we need state to track the just-minted key.
 */
import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError, getAgent, listAgentKeys } from "@/lib/api";
import { KeyManager } from "./KeyManager";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "API keys",
};

interface PageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ new?: string }>;
}

export default async function AgentKeysPage({ params, searchParams }: PageProps) {
  const [{ id }, sp] = await Promise.all([params, searchParams]);
  const agentId = decodeURIComponent(id);

  let agentName = agentId;
  try {
    const agent = await getAgent(agentId);
    agentName = agent.name;
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    // Fall through with default name if the agent fetch fails for another reason.
  }

  let initialKeys = [] as Awaited<ReturnType<typeof listAgentKeys>>["keys"];
  let loadError: string | null = null;
  try {
    const res = await listAgentKeys(agentId, { includeRevoked: true });
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
          href={`/agents/${encodeURIComponent(agentId)}`}
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← Back to agent
        </Link>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">
          API keys for {agentName}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Keys here are scoped to this agent only. Create one, copy the secret
          immediately — we don&apos;t store it in plaintext.
        </p>
      </div>

      {/* HIDE: MCP — banner pointed users at customer-wide keys minted from
          the MCP setup wizard. Not relevant for the SDK-first (Diana) flow.
          Hidden, not deleted, per dashboard_audit_2026-06-05 (#47).
      <div className="rounded-md border border-blue-500/40 bg-blue-500/10 p-3 text-sm">
        <span className="font-medium">Looking for a key you minted from the MCP setup?</span>{" "}
        Most MCP keys are created customer-wide so they work across all your agents. Find them at{" "}
        <Link
          href="/keys"
          className="font-medium underline underline-offset-2"
        >
          /keys
        </Link>
        .
      </div>
      */}

      {sp.new === "1" && (
        <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm">
          Agent created. Create a key below to use with the SDK or HTTP API.
        </div>
      )}

      {loadError && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          Could not load keys: {loadError}
        </div>
      )}

      <KeyManager agentId={agentId} initialKeys={initialKeys} />
    </main>
  );
}

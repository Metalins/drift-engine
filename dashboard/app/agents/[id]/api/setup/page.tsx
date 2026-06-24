/**
 * /agents/[id]/api/setup — UX-5.17.API3 HTTP API / SDK setup.
 *
 * The third connect path, parallel to /mcp/setup and /watchers/setup.
 * Deliberately thin (Jose, API3 decision): the API path has no
 * client-config file to edit and no system-prompt block to paste —
 * you mint a key and you write code. So this page is two sections:
 *
 *   1. Mint / pick an API key (the same KeyManager the MCP wizard uses).
 *   2. A concrete, copy-paste curl + Python snippet that streams an
 *      event to *this* agent, key inlined.
 *
 * The full endpoint catalog (register, status, proofs, revoke, the
 * SDK quickstart) lives at /docs/reference/developer-api — this page
 * links there rather than duplicating it.
 *
 * Framing is API-first (Jose, API3 decision): the HTTP API is the
 * product surface; the Python SDK is an ergonomic wrapper.
 */
import Link from "next/link";
import { notFound } from "next/navigation";
import { Code2 } from "lucide-react";
import { ApiError, getAgent, listAgentKeys } from "@/lib/api";
import { WizardProgress } from "@/components/WizardProgress";
import { ApiSetup } from "./ApiSetup";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Set up the HTTP API",
};

interface PageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ new?: string }>;
}

export default async function ApiSetupPage({
  params,
  searchParams,
}: PageProps) {
  const [{ id }, sp] = await Promise.all([params, searchParams]);
  const agentId = decodeURIComponent(id);
  const isWizard = sp.new === "1";

  let agentName = agentId;
  try {
    const agent = await getAgent(agentId);
    agentName = agent.name;
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
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
      {isWizard && (
        <div className="pt-2">
          <WizardProgress currentStep={2} />
        </div>
      )}

      <div>
        <Link
          href={
            isWizard
              ? `/agents/${encodeURIComponent(agentId)}/connect?new=1`
              : `/agents/${encodeURIComponent(agentId)}`
          }
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← {isWizard ? "Back to connection options" : "Back to agent"}
        </Link>
        <div className="mt-2 flex items-center gap-2">
          <Code2 size={26} />
          <h1 className="text-3xl font-semibold tracking-tight">
            HTTP API / SDK — {agentName}
          </h1>
        </div>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          Stream events to this agent from your own code. Mint a key,
          then call the API directly — or through the Python SDK, which
          wraps the same endpoints.
        </p>
      </div>

      {loadError && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          Could not load keys: {loadError}
        </div>
      )}

      <ApiSetup
        agentId={agentId}
        agentName={agentName}
        initialKeys={initialKeys}
        isWizard={isWizard}
      />
    </main>
  );
}

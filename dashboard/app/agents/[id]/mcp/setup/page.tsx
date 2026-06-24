/**
 * /agents/[id]/mcp/setup — UX-5.15.T sequential MCP wizard.
 *
 * The dense `/agents/[id]/mcp` page packs the entire setup (mint key,
 * paste client config, paste system prompt) into one screen — fine
 * for revisits, overwhelming for first-time onboarding. This route
 * walks the customer through the same steps one at a time, with a
 * polling verify step at the end that flips to success the moment
 * the first event arrives.
 *
 * Shared components: this page renders the same building blocks the
 * dense page uses (`KeyManager`, `ConfigBlock`, snippet builders from
 * `lib/mcp-snippets`). Editing snippet shape or copy in one place
 * updates both surfaces.
 *
 * URL state:
 *   ?step=key       → mint API key (default)
 *   ?step=configure → paste client config (Claude Code / Cursor / Desktop)
 *   ?step=prompt    → paste system prompt block
 *   ?step=verify    → poll for first event + manual refresh
 *   ?new=1          → render the wizard breadcrumb at the top
 *
 * After verify success, redirect to `/agents/[id]?new=1` so the
 * existing post-create detail experience takes over.
 */
import Link from "next/link";
import { notFound } from "next/navigation";
import { Terminal } from "lucide-react";
import { ApiError, getAgent, listAgentKeys } from "@/lib/api";
import { WizardProgress } from "@/components/WizardProgress";
import { SetupWizard, type SetupStep } from "./SetupWizard";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Set up MCP",
};

const STEPS: SetupStep[] = ["key", "configure", "prompt", "verify"];

function parseStep(raw: string | undefined): SetupStep {
  if (raw && (STEPS as string[]).includes(raw)) return raw as SetupStep;
  return "key";
}

interface PageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ step?: string; new?: string }>;
}

export default async function McpSetupWizardPage({
  params,
  searchParams,
}: PageProps) {
  const [{ id }, sp] = await Promise.all([params, searchParams]);
  const agentId = decodeURIComponent(id);
  const isWizard = sp.new === "1";
  const step = parseStep(sp.step);

  let agentName = agentId;
  let initialEventCount = 0;
  try {
    const agent = await getAgent(agentId);
    agentName = agent.name;
    initialEventCount =
      typeof (agent as { event_count?: number }).event_count === "number"
        ? (agent as { event_count: number }).event_count
        : 0;
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
          <Terminal size={26} />
          <h1 className="text-3xl font-semibold tracking-tight">
            Set up MCP — {agentName}
          </h1>
        </div>
      </div>

      {loadError && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          Could not load keys: {loadError}
        </div>
      )}

      <SetupWizard
        agentId={agentId}
        agentName={agentName}
        initialKeys={initialKeys}
        initialEventCount={initialEventCount}
        step={step}
        isWizard={isWizard}
      />
    </main>
  );
}

/**
 * /agents/[id]/mcp — MCP setup page (Sprint 5).
 *
 * V1 product is **watcher + MCP**, NOT SDK (see CHECKPOINT.md). This page is
 * the canonical entry point for the MCP integration path. It bundles:
 *
 *   1. A brief explainer (what MCP is + why you'd use it here).
 *   2. The API-key generation flow (re-uses /agents/[id]/keys's KeyManager) —
 *      MCP needs a Bearer token to call api.metalins.ai, so key creation lives
 *      INSIDE the MCP page rather than as a standalone primary action.
 *   3. Copy-paste config snippets for Claude Code CLI, Cursor and Claude
 *      Desktop, with the user's MCP URL + a placeholder for the key.
 *
 * Old `/keys` page still exists at /agents/[id]/keys for power users who want
 * raw key management UX (revoke, list, etc.) without the MCP scaffolding.
 */
import Link from "next/link";
import { notFound } from "next/navigation";
import { Terminal } from "lucide-react";
import { ApiError, getAgent, listAgentKeys } from "@/lib/api";
import { McpDisconnectButton } from "./McpDisconnectButton";
import { McpQuickStart } from "./McpQuickStart";
import { WizardProgress } from "@/components/WizardProgress";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Connect MCP",
};

interface PageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ new?: string }>;
}

export default async function AgentMcpPage({ params, searchParams }: PageProps) {
  const [{ id }, sp] = await Promise.all([params, searchParams]);
  const agentId = decodeURIComponent(id);
  const isWizard = sp.new === "1";

  let agentName = agentId;
  let mcpDisconnected = false;
  try {
    const agent = await getAgent(agentId);
    agentName = agent.name;
    mcpDisconnected = agent.integration?.mcp_disabled_at != null;
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
    <main className="space-y-8">
      {isWizard && (
        <div className="pt-2">
          <WizardProgress currentStep={3} />
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
            Connect MCP — {agentName}
          </h1>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          Setting up identity tracking is <strong>two parts</strong>:
          (1) add Metalins as an MCP server in your client (Claude
          Code, Cursor or Claude Desktop), and (2) paste a short block
          into your agent&apos;s system prompt so the LLM actually
          calls{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">
            metalins_log_event
          </code>{" "}
          after every meaningful action. Both are required for
          continuous coverage.
        </p>
      </div>

      {/* Sprint UX-5.15.S — limitations card lifted to the top so the
          customer reads the gotchas BEFORE minting a key. Carlos /
          Diana looked at this page and started copying snippets
          before understanding the LLM-compliance dependency. */}
      <section className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-5">
        <h2 className="text-sm font-semibold tracking-tight text-foreground">
          Before you start — what MCP can and can&apos;t do
        </h2>
        <ul className="mt-3 space-y-2 text-sm text-muted-foreground">
          <li className="flex gap-2">
            <span aria-hidden="true" className="mt-1 text-amber-600">▸</span>
            <span>
              Events fire <strong>only when the LLM calls a tool</strong>.
              Chat-only conversation, edits without tool calls, or model
              responses without action → no events. We fix that with the
              system-prompt block in part 2 below.
            </span>
          </li>
          <li className="flex gap-2">
            <span aria-hidden="true" className="mt-1 text-amber-600">▸</span>
            <span>
              Coverage depends on the LLM <strong>following instructions</strong>.
              Most modern models comply, but some skip the call under load
              or after a long conversation.
            </span>
          </li>
          <li className="flex gap-2">
            <span aria-hidden="true" className="mt-1 text-amber-600">▸</span>
            <span>
              You&apos;ll need to <strong>edit your client&apos;s MCP
              config</strong> (or the in-app connector UI for Claude
              Desktop) and keep the API key around.
            </span>
          </li>
          <li className="flex gap-2">
            <span aria-hidden="true" className="mt-1 text-amber-600">▸</span>
            <span>
              If your agent runs in <strong>backend code</strong>
              {" "}(LangChain, your own loop) you don&apos;t need MCP — call{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                metalins_log_event
              </code>{" "}
              directly, or wait for the Python SDK wrapper coming in MVP2.
            </span>
          </li>
        </ul>
      </section>

      {/* Sprint UX-5.15.M — dropped the "STEP 1/2/3/4" body labels
          that collided with the top-level wizard breadcrumb (NAME →
          CONNECT → SETUP → VERIFY). Andrea got confused not knowing
          whether "Step 3" referred to the wizard or the page's
          internal flow. Now the body uses plain headings instead.

          UX-5.15.R: the explainer now spells out the two-part setup
          so customers don't think the MCP install alone is enough. */}
      <section className="rounded-lg border bg-card p-6">
        <h2 className="text-sm font-semibold tracking-tight text-foreground">
          What is MCP, and why the system prompt too?
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          MCP (Model Context Protocol) is how AI clients like Claude
          Code, Cursor and Claude Desktop call external tools. Adding
          Metalins as an MCP server gives the LLM <em>the ability</em>
          {" "}to log events to your agent &mdash; but most clients
          only call tools when the LLM decides to. The system-prompt
          block below tells your LLM to actually use it after every
          meaningful action, so your event stream is continuous
          instead of bursty.
        </p>
      </section>

      {loadError && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          Could not load keys: {loadError}
        </div>
      )}
      <McpQuickStart
        agentId={agentId}
        agentName={agentName}
        initialKeys={initialKeys}
      />

      {/* Verify panel — uses the friendly agent NAME instead of the
          raw `agt_…` ID (Andrea fix F3 — Sprint UX-5.15.M). UX-5.15.R
          tweaks the copy to remind the customer that both halves
          have to land before the event counter ticks. */}
      <section className="rounded-lg border bg-card p-6">
        <h2 className="text-sm font-semibold tracking-tight text-foreground">
          Verify it works
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          After completing both parts above (MCP server config + system
          prompt block), restart your client and have a short
          conversation. Within a few seconds the event count on this
          page should tick up. If it doesn&apos;t, double-check the
          system prompt block landed in the right slot — most quiet
          agents are a forgotten system prompt, not a broken MCP.
        </p>
      </section>

      {/* Disconnect / reconnect — Sprint 6.4 / #575. Lives at the bottom so
          the danger affordance doesn't dominate the onboarding flow above. */}
      <McpDisconnectButton
        agentId={agentId}
        agentName={agentName}
        isDisconnected={mcpDisconnected}
      />
    </main>
  );
}

/**
 * /agents/[id]/watchers — Sprint 4.4
 *
 * Dense "manage from agent detail" page. Lists existing watchers and
 * lets the user connect a bot if there isn't one yet. This is what
 * the "Manage bot" button in the agent header links to.
 *
 * UX-5.15.AA (2026-05-19): wizard-mode plumbing (`?new=1`,
 * WizardProgress, "back to connection options" link) moved out of
 * this page into a dedicated `/watchers/setup` page, mirroring the
 * `/mcp` (dense) + `/mcp/setup` (wizard) split. Both surfaces reuse
 * the same `WatcherManager` Client Component — so any change to the
 * connect-bot UX updates both places without drift. This page is now
 * only ever the post-setup management surface.
 *
 * Server Component loads initial state; the WatcherManager Client
 * Component handles the connect-bot wizard and live actions.
 */
import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError, getAgent, listWatchers } from "@/lib/api";
import { WatcherManager } from "./WatcherManager";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Manage bot",
};

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function AgentWatchersPage({ params }: PageProps) {
  const { id } = await params;
  const agentId = decodeURIComponent(id);

  let agentName = agentId;
  try {
    const agent = await getAgent(agentId);
    agentName = agent.name;
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
  }

  let initial = {
    watchers: [] as Awaited<ReturnType<typeof listWatchers>>["watchers"],
    supported_platforms: [] as string[],
  };
  let loadError: string | null = null;
  try {
    initial = await listWatchers(agentId);
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
          Bot — {agentName}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Zero-code integration. Paste your bot&apos;s API token below and
          we&apos;ll watch its public activity, hash it locally, and update
          this agent&apos;s identity score continuously.{" "}
          <strong className="text-foreground">
            We never see message content — only hashes leave your watcher.
          </strong>
        </p>
      </div>

      {loadError && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          Could not load watchers: {loadError}
        </div>
      )}

      <WatcherManager
        agentId={agentId}
        initialWatchers={initial.watchers}
        supportedPlatforms={initial.supported_platforms}
      />
    </main>
  );
}

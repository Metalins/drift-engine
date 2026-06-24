/**
 * /agents/[id]/watchers/setup — Sprint UX-5.15.AA (2026-05-19).
 *
 * Dedicated bot-setup wizard page, parallel to `/mcp/setup`. Mirror
 * of the pattern Jose cemented for MCP: the dense "manage" surface
 * stays at `/watchers` (called from the agent-detail header), while
 * the wizard-only flow lives here. Both reuse the same
 * `WatcherManager` Client Component — no special prop, no isWizard
 * branching inside the component. The wizard chrome (progress
 * breadcrumb, back-to-connect link, "Continue to verify" CTA once
 * the bot is connected) lives on this page only.
 *
 * Flow:
 *   /agents/[id]/connect?new=1
 *     → click "Connect a bot" card
 *     → /agents/[id]/watchers/setup     (THIS page)
 *     → user pastes token, watcher mounts active/pending
 *     → server-rendered "Continue to verify" CTA appears
 *     → /agents/[id]?new=1              (detail / verify step)
 *
 * Server Component. Loads the watcher list to decide whether the
 * "Continue" CTA should render and to seed `WatcherManager`.
 */
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { ApiError, getAgent, listWatchers } from "@/lib/api";
import { WatcherManager } from "../WatcherManager";
import { WizardProgress } from "@/components/WizardProgress";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Connect bot — setup",
};

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function WatcherSetupWizardPage({ params }: PageProps) {
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

  // "Bot connected" means at least one watcher exists in `active`
  // (running) or `pending` (just registered, first poll pending)
  // state. We explicitly exclude `paused` and `error` — those aren't
  // success states, the user needs to fix them before moving on.
  // After a successful submit, WatcherManager calls router.refresh()
  // which re-runs this server component, so the CTA appears without
  // a manual reload.
  const watcherReady = initial.watchers.some(
    (w) => w.state === "active" || w.state === "pending",
  );

  return (
    <main className="space-y-6">
      <div className="pt-2">
        <WizardProgress currentStep={2} />
      </div>

      <div>
        <Link
          href={`/agents/${encodeURIComponent(agentId)}/connect?new=1`}
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← Back to connection options
        </Link>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">
          Connect a bot to {agentName}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Paste your bot&apos;s API token below and we&apos;ll watch its
          public activity, hash it locally, and start identity-tracking
          continuously.{" "}
          <strong className="text-foreground">
            We never see message content — only hashes leave your watcher.
          </strong>
        </p>
      </div>

      {watcherReady && (
        <Link
          href={`/agents/${encodeURIComponent(agentId)}?new=1`}
          className="group flex items-center justify-between gap-4 rounded-lg border-2 border-emerald-500/40 bg-emerald-500/5 p-4 transition-colors hover:bg-emerald-500/10"
        >
          <div>
            <div className="text-sm font-semibold text-emerald-700 dark:text-emerald-400">
              Bot connected ✓
            </div>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Continue to verify your bot is logging events. Identity
              tracking starts on the next screen.
            </p>
          </div>
          <span className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white group-hover:bg-emerald-700">
            Continue
            <ArrowRight
              size={14}
              className="transition-transform group-hover:translate-x-0.5"
            />
          </span>
        </Link>
      )}

      {loadError && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          Could not load watchers: {loadError}
        </div>
      )}

      {/* Reuse the same component that lives on the dense /watchers
          page so any change to the connect-bot UX updates both
          surfaces without drift. */}
      <WatcherManager
        agentId={agentId}
        initialWatchers={initial.watchers}
        supportedPlatforms={initial.supported_platforms}
      />
    </main>
  );
}

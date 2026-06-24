/**
 * /agents/[id]/anchors — Sprint UX-5.9-G.
 *
 * Manage external identity anchors for one agent. V1 supports the
 * GitHub-gist flow; the page is structured so DNS, X, etc. can drop in
 * as additional cards without restructuring.
 *
 * Server Component loads the agent name + initial anchors list and hands
 * them to the Client Component that drives the start/verify state.
 */
import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError, getAgent, listAnchors } from "@/lib/api";
import { AnchorsManager } from "./AnchorsManager";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "External anchors",
};

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function AgentAnchorsPage({ params }: PageProps) {
  const { id } = await params;
  const agentId = decodeURIComponent(id);

  let agentName = agentId;
  let agentSlug: string | null = null;
  try {
    const agent = await getAgent(agentId);
    agentName = agent.name;
    // Sprint UX-5.11 R2 / R2.3e — pass the current slug so the
    // verified-anchors list knows which row (if any) is the active
    // source of the agent's /v/<slug> URL.
    agentSlug = agent.public_slug ?? null;
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
  }

  let initial = [] as Awaited<ReturnType<typeof listAnchors>>["anchors"];
  let loadError: string | null = null;
  try {
    const res = await listAnchors(agentId);
    initial = res.anchors;
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
          External anchors — {agentName}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          <strong className="text-foreground">Optional but recommended
          if you plan to share your verify link.</strong>{" "}
          You can skip this and the agent still works.
        </p>
      </div>

      {/* What is an anchor — explainer card so first-time visitors
          understand the feature before they engage. Sprint UX-5.11 R2
          per persona feedback: "I don't know what an anchor is." */}
      <section className="rounded-lg border bg-card p-5">
        <h2 className="text-base font-medium">What&apos;s an anchor?</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          An anchor is another identity you already control — your
          GitHub user, your DNS domain, or your Telegram bot
          @username — that you publicly link to this agent. You prove
          you control it once (we give you a challenge to post), and
          from then on{" "}
          <strong className="text-foreground">
            anyone visiting your verify page can cross-check the anchor
            on the other platform themselves
          </strong>
          .
        </p>
        <p className="mt-3 text-sm text-muted-foreground">
          <strong className="text-foreground">Why it matters:</strong>{" "}
          without an anchor, a visitor seeing your verify page only
          learns that the agent is registered in this instance — they have
          to trust it. With an anchor, they don&apos;t need to trust it
          at all: they open Telegram (or GitHub, or check DNS), see the
          same handle you claim, and decide based on the platforms they
          already know.
        </p>
        <p className="mt-3 text-sm text-muted-foreground">
          That&apos;s the point: the more places independently confirm
          who runs this agent, the less you depend on any single source
          (this instance included).
        </p>
      </section>

      {loadError && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          Could not load anchors: {loadError}
        </div>
      )}

      <AnchorsManager
        agentId={agentId}
        initialAnchors={initial}
        initialSlug={agentSlug}
      />
    </main>
  );
}

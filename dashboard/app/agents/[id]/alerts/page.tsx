/**
 * /agents/[id]/webhooks — Sprint UX-5.10-6 + Sprint UX-5.11 / Diana
 * round 0 fixes (bug-diana-1, -2, -3).
 *
 * Diana's promised feature: alert plumbing wired to whatever channel
 * her team monitors. Two MVP channels: email + webhook. Email
 * recipient is stored on the agent's `metadata.alert_email`; sending
 * hooks in when the magic-link email provider lands. Webhook is
 * already wired end-to-end.
 *
 * Sprint UX-5.11 (Diana round 0): the URL stays /webhooks for
 * backwards compatibility with existing bookmarks, but the page-level
 * label is now "Alerts" — Diana hunted for /alerts and 404'd here.
 * The header link in the agent detail also says "Alerts".
 */
import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError, getAgent, listWebhooks } from "@/lib/api";
import { WebhooksManager } from "./WebhooksManager";
import { EmailAlertsManager } from "./EmailAlertsManager";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Alerts",
};

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function AgentAlertsPage({ params }: PageProps) {
  const { id } = await params;
  const agentId = decodeURIComponent(id);

  let agentName = agentId;
  let initialEmail: string | null = null;
  try {
    const agent = await getAgent(agentId);
    agentName = agent.name;
    const md = agent.metadata as Record<string, unknown> | null | undefined;
    const candidate = md && typeof md["alert_email"] === "string"
      ? (md["alert_email"] as string)
      : null;
    initialEmail = candidate && candidate.trim() ? candidate : null;
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
  }

  let initial = [] as Awaited<ReturnType<typeof listWebhooks>>["webhooks"];
  let loadError: string | null = null;
  try {
    const res = await listWebhooks(agentId);
    initial = res.webhooks;
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
          Alerts — {agentName}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Two ways to know when this agent&apos;s verification state
          shifts to <em>caution</em> or <em>action</em>: an email to
          whoever&apos;s on call, or a signed POST to your team&apos;s
          ingest endpoint. Configure either or both.
        </p>
      </div>

      <EmailAlertsManager
        agentId={agentId}
        initialEmail={initialEmail}
      />

      {loadError && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          Could not load webhooks: {loadError}
        </div>
      )}

      <WebhooksManager agentId={agentId} initialWebhooks={initial} />
    </main>
  );
}

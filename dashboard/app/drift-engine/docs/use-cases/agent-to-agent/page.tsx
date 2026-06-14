/**
 * /docs/use-cases/agent-to-agent — A2A trust.
 *
 * Sprint UX-5.15.F (task #846). Carved from old /docs#agent-to-agent
 * use-case section. Content preserved verbatim.
 */
import Link from "next/link";

export const metadata = {
  title: "Agent-to-agent — Drift Engine docs",
  description:
    "When your agent calls another agent, trust has to be cryptographic. A single public, unauthenticated endpoint lets either side verify the other in milliseconds.",
  alternates: { canonical: "/drift-engine/docs/use-cases/agent-to-agent" },
};

const HOW_IT_WORKS = [
  "Agent A asks Drift Engine for a verifiable identity claim — a short-lived signed JWT asserting 'I am agent X owned by customer Y, as of timestamp T'.",
  "A presents the identity claim to agent B (over any channel: HTTP header, message body, or tool call).",
  "B (the receiving side) calls POST https://api.metalins.ai/v1/verify-proof with the claim. The endpoint is public, no auth, free.",
  "Drift Engine checks the signature against its JWKS, checks the revocation list, checks the issuing agent is still active — and returns valid: true / false plus the agent's current cryptographic state.",
  "Works across customers: A and B can belong to different Drift Engine accounts. The trust is mediated by Drift Engine's public key, not by any shared secret.",
];

export default function AgentToAgentUseCasePage() {
  return (
    <main className="space-y-10">
      <header className="space-y-3 border-b pb-6">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-block rounded-full bg-muted px-3 py-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Agent-to-agent
          </span>
        </div>
        <h1 className="text-3xl font-semibold leading-tight tracking-tight md:text-4xl">
          When your agent calls another agent, trust has to be
          cryptographic.
        </h1>
        <p className="max-w-3xl text-lg text-muted-foreground">
          Your agent delegates a task. Or accepts work from another
          agent &mdash; even one owned by a different customer. Before
          passing context, let alone credentials or money, you ask
          Drift Engine to confirm who&apos;s really on the other side.
          One public, unauthenticated endpoint &mdash; free, signed,
          milliseconds.
        </p>
        <p className="text-sm">
          <span className="font-medium">For:</span>{" "}
          <span className="text-muted-foreground">
            Engineering teams building multi-agent systems.
          </span>
        </p>
      </header>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold tracking-tight">
          The problem
        </h2>
        <p className="max-w-3xl text-muted-foreground">
          Agent-to-agent protocols (agent orchestration systems and
          multi-agent pipelines) are arriving fast. The thing missing: a way for
          one agent to verify another agent&apos;s identity across
          organizations. Today, agents trust the URL they were given.
          That&apos;s the equivalent of websites trusting whoever
          claims to be a CA.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold tracking-tight">
          How Drift Engine solves it
        </h2>
        <ol className="space-y-3">
          {HOW_IT_WORKS.map((step, i) => (
            <li
              key={i}
              className="flex gap-4 rounded-lg border bg-card p-4"
            >
              <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-sm font-medium text-muted-foreground">
                {i + 1}
              </span>
              <p className="text-sm text-muted-foreground">{step}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border bg-card p-5">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Integration
          </h3>
          <p className="mt-2 text-sm text-muted-foreground">
            One endpoint, live today:{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">
              POST /v1/verify-proof
            </code>
            . Public, unauthenticated, free. The verifying agent sends
            the claim; the response is{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">
              {`{ valid, agent_id, scope, ... }`}
            </code>
            . See the{" "}
            <Link
              href="/drift-engine/docs/reference/verify-proof"
              className="font-medium text-foreground hover:underline"
            >
              verify-proof reference
            </Link>{" "}
            for the full shape. The agent that issues the claim does so
            through its own dashboard or the SDK.
          </p>
        </div>
        <div className="rounded-lg border bg-card p-5">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Who else benefits
          </h3>
          <p className="mt-2 text-sm text-muted-foreground">
            Agent marketplaces, multi-agent gateways, autonomous
            workflow platforms.
          </p>
        </div>
      </section>

      <section className="rounded-lg border bg-card/60 p-5 text-sm text-muted-foreground">
        See the{" "}
        <Link
          href="/drift-engine/docs/reference/verify-proof"
          className="font-medium text-foreground hover:underline"
        >
          verify-proof reference
        </Link>{" "}
        for the full request/response shape and a curl example.
      </section>
    </main>
  );
}

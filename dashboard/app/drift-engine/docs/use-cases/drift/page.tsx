/**
 * /docs/use-cases/drift — Drift & clone detection (marketing voice).
 *
 * Sprint UX-5.15.F (task #846). Carved from old /docs#drift-detection
 * use-case section. Content preserved verbatim. The reference half
 * lives at /docs/concepts/drift-detection.
 */
export const metadata = {
  title: "Drift detection — Drift Engine docs",
  description:
    "Two-layer signal — cryptographic identity from day one, and a behavior pattern that earns the right to call drift once your agent has been running long enough.",
  alternates: { canonical: "/drift-engine/docs/use-cases/drift" },
};

const HOW_IT_WORKS = [
  "Wire Drift Engine into your agent with 3 lines of Python. Events are logged automatically as your agent processes requests — no changes to your business logic.",
  "Every event your agent processes is hashed before it ever leaves your machine. We see hashes, never the content.",
  "From the first event, the cryptographic layer is active: signature failures, revoked keys and history-integrity breaks all fire immediately as caution / not-trusted states.",
  "Once your agent has been running long enough for its pattern to settle, divergence from that pattern surfaces as a drift signal — webhook + dashboard alert before the support queue starts moving.",
  "We will tell you when the behavior layer is still learning your baseline. We don't fabricate a drift call on a four-day-old agent — that would be sampling noise, not signal.",
];

export default function DriftUseCasePage() {
  return (
    <main className="space-y-10">
      <header className="space-y-3 border-b pb-6">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-block rounded-full bg-muted px-3 py-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Drift &amp; clone detection
          </span>
        </div>
        <h1 className="text-3xl font-semibold leading-tight tracking-tight md:text-4xl">
          Your agent in production isn&apos;t behaving like itself.
        </h1>
        <p className="max-w-3xl text-lg text-muted-foreground">
          Models swap silently. Prompts get injected. Deploys regress.
          Drift Engine gives you a two-layer signal &mdash; cryptographic
          identity from day one, and a behavior pattern that earns
          the right to call drift once your agent has been running
          long enough.
        </p>
        <p className="text-sm">
          <span className="font-medium">For:</span>{" "}
          <span className="text-muted-foreground">
            Engineering teams shipping AI agents to real users.
          </span>
        </p>
      </header>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold tracking-tight">
          The problem
        </h2>
        <p className="max-w-3xl text-muted-foreground">
          An agent in production is a moving target. The underlying
          model gets updated by the provider. A prompt-injection attack
          changes its behavior. A bad deploy ships a different system
          prompt. None of this triggers alerts in your standard
          observability stack &mdash; your agent still returns 200s. By
          the time a user complains, hundreds of bad responses are
          already out.
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
            Three lines of Python in your agent and every action
            becomes identity-tracked. The setup page in your
            agent&apos;s dashboard walks you through it step by step.
          </p>
        </div>
        <div className="rounded-lg border bg-card p-5">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Who else benefits
          </h3>
          <p className="mt-2 text-sm text-muted-foreground">
            Anyone running an agent where &lsquo;wrong but
            plausible&rsquo; answers cost real money &mdash; fintech,
            healthcare, support, code.
          </p>
        </div>
      </section>
    </main>
  );
}

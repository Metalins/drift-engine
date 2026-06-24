/**
 * /docs/concepts/drift-detection — drift signal explainer.
 *
 * Sprint UX-5.15.F (task #846). Carved from old
 * /docs#drift-detection-reference. Reference half of the drift
 * surface; the use-case marketing block lives at /docs/use-cases/drift.
 * Sprint UX-5.15.G (task #847) refined density.
 * Sprint UX-5.15.I (task #849) — IP protection refactor: default view
 * is outcome + guarantees, the rest is collapsible. References to
 * "established fingerprint" replaced with "settled pattern".
 */
export const metadata = {
  title: "Drift signals — Drift Engine docs",
  description:
    "What a drift signal means, when it fires, and what it deliberately does not claim.",
  alternates: { canonical: "/drift-engine/docs/concepts/drift-detection" },
};

export default function DriftDetectionConceptPage() {
  return (
    <main className="space-y-10">
      <header className="space-y-3 border-b pb-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Concept
        </p>
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
          What a drift signal means (and what it doesn&apos;t)
        </h1>
      </header>

      {/* Default view — promise + guarantees. */}
      <section className="space-y-5">
        <p className="max-w-3xl text-muted-foreground">
          A drift signal fires when an agent at the highest tier
          starts producing activity that no longer matches its
          settled pattern. By the time the signal fires, we have
          enough confidence that the divergence is meaningful, not
          noise.
        </p>

        <div className="rounded-lg border-l-4 border-emerald-500 bg-emerald-500/5 p-5">
          <h3 className="text-sm font-semibold text-foreground">
            What this guarantees
          </h3>
          <ul className="mt-2 space-y-3 text-sm text-muted-foreground">
            <li>
              The webhook and the dashboard both fire on the same
              transition. You will not silently miss the signal
              &mdash; the alert page surfaces it and (if configured)
              your endpoint receives a signed payload.
            </li>
            <li>
              The first diverging window is timestamped and
              preserved in your timeline. You can walk back from the
              alert to the exact window where the agent stopped
              matching its pattern.
            </li>
            <li>
              Drift signals only fire at the highest tier. Earlier
              tiers never raise drift, even if internal signals
              would suggest it &mdash; the pattern is not settled
              enough yet for the call to be reliable.
            </li>
          </ul>
        </div>
      </section>

      {/* Progressive disclosure: how it works. */}
      <details className="group rounded-lg border bg-card p-5">
        <summary className="cursor-pointer list-none text-sm font-semibold text-foreground">
          <span className="mr-2 inline-block transition-transform group-open:rotate-90">
            ›
          </span>
          Learn how this works
        </summary>
        <div className="mt-4 space-y-3 text-sm text-muted-foreground">
          <p>
            We watch the shape of your agent&apos;s activity. When
            that shape stops matching what we learned during normal
            usage, we flag it. Privacy: we work entirely from
            hashes; we never see your prompts or responses.
          </p>
          <p>
            Detection is statistical. We wait until we have enough
            activity to be confident before calling drift. Before
            that the agent is still learning your baseline and the
            panel says so explicitly.
          </p>
        </div>
      </details>

      {/* Progressive disclosure: limits. */}
      <details className="group rounded-lg border-l-4 border-amber-500 bg-amber-500/5 p-5">
        <summary className="cursor-pointer list-none text-sm font-semibold text-foreground">
          <span className="mr-2 inline-block transition-transform group-open:rotate-90">
            ›
          </span>
          What this does NOT guarantee
        </summary>
        <ul className="mt-3 space-y-3 text-sm text-muted-foreground">
          <li>
            A drift signal is not a guarantee of compromise. It is
            a signal worth investigating.
          </li>
          <li>
            Legitimate causes Drift Engine cannot distinguish from a
            compromise include: an intentional build upgrade, a new
            system-prompt template that genuinely changed the
            response style, or a different category of users the
            agent suddenly started serving.
          </li>
          <li>
            Drift does not pinpoint the cause. The signal tells you{" "}
            <em>that</em> the pattern changed and roughly{" "}
            <em>when</em>. It does not tell you <em>which</em>
            turn, prompt, or model upgrade is responsible &mdash;
            we never saw the content.
          </li>
        </ul>
      </details>

      <div className="rounded-lg border bg-muted/30 p-5">
        <h3 className="text-sm font-semibold text-foreground">
          Recommended response
        </h3>
        <p className="mt-2 text-sm text-muted-foreground">
          Treat drift as the alert that tells you to check, not the
          conclusion that something is wrong.
        </p>
        <p className="mt-2 text-sm text-muted-foreground">
          Rotate the agent&apos;s secret if you suspect a
          compromise, then compare the diverging window against any
          deploys or upstream changes that happened around the same
          time.
        </p>
      </div>
    </main>
  );
}

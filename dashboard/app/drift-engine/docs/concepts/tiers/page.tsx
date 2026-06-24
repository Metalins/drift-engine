/**
 * /docs/concepts/tiers — Identity tiers explainer.
 *
 * Sprint UX-5.15.F (task #846) carved from old /docs#identity-tiers
 * anchor. Sprint UX-5.15.G (task #847) refined density.
 * Sprint UX-5.15.I (task #849) — IP protection refactor. The previous
 * "events sent →" axis on the progression diagram leaked the
 * floor structure (T0/T1/T2/T3 mapped to specific event counts is
 * calibration IP). The diagram is dropped; the tier cards already
 * convey the ladder, and the panel header in /agents/[id] links
 * here when "What does this tier mean?" is clicked. Tier copy is
 * also reframed to avoid "input → output shape" and "locked-in
 * fingerprint" mechanism hints. Rector: docs/product/IDENTITY-TIERS-AND-COMMUNICATION.md §5.
 */
export const metadata = {
  title: "Identity tiers — Drift Engine docs",
  description:
    "The four-tier ladder that names what protections are active on an agent at each point in its life.",
  alternates: { canonical: "/drift-engine/docs/concepts/tiers" },
};

export default function TiersPage() {
  return (
    <main className="space-y-10">
      <header className="space-y-3 border-b pb-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Concept
        </p>
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
          Identity tiers
        </h1>
      </header>

      {/* Default view — promise + the four tiers + guarantees. */}
      <section className="space-y-4">
        <p className="max-w-3xl text-muted-foreground">
          Drift Engine surfaces your agent&apos;s identity strength as a
          ladder of four tiers. Each tier names a concrete set of
          protections active at that point. As your agent runs, more
          protections unlock and the tier moves up.
        </p>
      </section>

      <section className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-lg border bg-card p-5">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              T0 &mdash; Registered
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              The agent&apos;s public key is on file with Drift Engine.
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              No activity has been observed yet, and nothing about
              the agent&apos;s behavior is being claimed.
            </p>
          </div>
          <div className="rounded-lg border bg-card p-5">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              T1 &mdash; Early signals
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              The first protections have activated. An impostor that
              does not hold the agent&apos;s secret fails at the
              first signed write.
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              Bulk identity swaps and naive clones are detectable
              from here.
            </p>
          </div>
          <div className="rounded-lg border bg-card p-5">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              T2 &mdash; Standard
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              The agent&apos;s normal behavior is starting to take
              shape. Wholesale prompt rewrites, model swaps and
              obvious behavioral substitutions get caught.
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              Mid confidence: enough to flag a sudden change, not
              yet enough to certify long-term stability.
            </p>
          </div>
          <div className="rounded-lg border bg-card p-5">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              T3 &mdash; Full coverage
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              The full set of protections is active. Subtle drift,
              partial swaps, and gradual injection attacks become
              detectable.
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              Drift signals are meaningful from this point: if
              Drift Engine says &ldquo;behavior changed,&rdquo; it means
              a measurable, persistent divergence.
            </p>
          </div>
        </div>
      </section>

      {/* Progressive disclosure: how progression works. */}
      <details className="group rounded-lg border bg-card p-5">
        <summary className="cursor-pointer list-none text-sm font-semibold text-foreground">
          <span className="mr-2 inline-block transition-transform group-open:rotate-90">
            ›
          </span>
          Learn how progression works
        </summary>
        <div className="mt-4 space-y-3 text-sm text-muted-foreground">
          <p>
            Tiers progress as the agent accumulates enough activity
            for each layer of protection to activate. We don&apos;t
            claim coverage we can&apos;t back up &mdash; if the
            agent hasn&apos;t been running long enough for a given
            protection to be confident, the dashboard says so
            explicitly.
          </p>
          <p>
            The dashboard always shows the full list of active
            protections with which attack each one defends against.
            The tier label is shorthand for &ldquo;everything up to
            here is active.&rdquo;
          </p>
        </div>
      </details>

      <section className="space-y-4">
        <div className="rounded-lg border-l-4 border-emerald-500 bg-emerald-500/5 p-5">
          <h3 className="text-sm font-semibold text-foreground">
            What this guarantees
          </h3>
          <ul className="mt-2 space-y-2 text-sm text-muted-foreground">
            <li>
              At every tier, the list of active protections is
              concrete and visible in the dashboard.
            </li>
            <li>
              Each row states what attack it defends against and
              what activity level its guarantee starts at.
            </li>
            <li>No silent gates, no surprise transitions.</li>
          </ul>
        </div>
        <details className="group rounded-lg border-l-4 border-amber-500 bg-amber-500/5 p-5">
          <summary className="cursor-pointer list-none text-sm font-semibold text-foreground">
            <span className="mr-2 inline-block transition-transform group-open:rotate-90">
              ›
            </span>
            What this does NOT guarantee
          </summary>
          <ul className="mt-3 space-y-2 text-sm text-muted-foreground">
            <li>
              Tiers are convenience labels for aggregate progress;
              they are not a replacement for reading the
              per-protection list.
            </li>
            <li>
              T3 is not a claim of invulnerability &mdash; every
              protection still has its own &ldquo;does NOT
              guarantee&rdquo; line.
            </li>
            <li>
              Read those before you decide what trust to place in
              any given agent.
            </li>
          </ul>
        </details>
      </section>
    </main>
  );
}

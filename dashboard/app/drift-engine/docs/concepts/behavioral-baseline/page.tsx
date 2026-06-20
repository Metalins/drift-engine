/**
 * /docs/concepts/behavioral-baseline — explainer.
 *
 * Sprint UX-5.15.F (task #846) carved from old /docs#behavioral-baseline.
 * Sprint UX-5.15.G (task #847) refined density.
 * Sprint UX-5.15.I (task #849) — IP protection refactor. Default view
 * is outcome + guarantees only; the "how it works" is now a
 * collapsible with confidence-building copy that does not name the
 * technique, the sample floor, or the input/output framing. The
 * old "events over time → fingerprint stable" diagram is dropped —
 * the verde/amarillo cards convey the essence without leaking
 * calibration numbers.
 *
 * UX-5.17 docs pass — the old "Pattern recognition" page
 * (/docs/concepts/hash-correlation) was a near-duplicate of this one;
 * the 4 fresh-eyes persona reviews all flagged the two as one concept
 * split across two pages. They are merged here. The additive bits of
 * the old page (the subtitle framing and the "two similar agents"
 * limit) are folded in; hash-correlation now redirects here.
 */
export const metadata = {
  title: "Behavior pattern — Drift Engine docs",
  description:
    "How Drift Engine learns your agent's normal pattern from hashed activity, and what that lets us catch (and what it doesn't).",
  alternates: { canonical: "/drift-engine/docs/concepts/behavioral-baseline" },
};

export default function BehavioralBaselinePage() {
  return (
    <main className="space-y-10">
      <header className="space-y-3 border-b pb-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Concept
        </p>
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
          Behavior pattern
        </h1>
        <p className="max-w-3xl text-lg text-muted-foreground">
          We learn to recognize your agent&apos;s normal pattern, and
          tell you when activity stops matching it &mdash; working
          entirely from hashed events.
        </p>
      </header>

      {/* Default view — promise + guarantees, fits in 1 viewport. */}
      <section className="space-y-5">
        <p className="max-w-3xl text-muted-foreground">
          Drift Engine watches your agent and learns what its normal
          activity looks like. Once we&apos;ve seen enough, we&apos;ll
          tell you when the pattern stops matching &mdash; without
          ever seeing the content of what your agent says or hears.
        </p>

        <div className="rounded-lg border-l-4 border-emerald-500 bg-emerald-500/5 p-5">
          <h3 className="text-sm font-semibold text-foreground">
            What this guarantees
          </h3>
          <ul className="mt-2 space-y-3 text-sm text-muted-foreground">
            <li>
              Once the pattern is settled, Drift Engine recognizes when a
              new batch of activity doesn&apos;t fit &mdash; different
              response style, different timing, different overall
              behavior.
            </li>
            <li>
              We tell you which stage the agent is in. If we
              don&apos;t have enough activity yet to call drift, we
              say so explicitly &mdash; no fabricated numbers.
            </li>
            <li>
              A clone that copies your branding but doesn&apos;t
              match how your agent actually behaves cannot earn a
              consistent-pattern mark.
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
            <strong className="text-foreground">Privacy first.</strong>{" "}
            The pattern is built entirely from hashes. We do not read
            your prompts, your responses, your model weights, or your
            users&apos; data. Every signal we use travels in
            already-hashed form.
          </p>
          <p>
            We watch the shape of your agent&apos;s activity over
            time. Early on, only the broadest strokes are visible;
            as activity accumulates the picture settles into a
            recognizable pattern for that specific agent.
          </p>
          <p>
            From that point on, new activity is compared against
            that settled pattern. A meaningful divergence surfaces
            as a drift signal. Until the pattern has settled we
            say the agent is &ldquo;learning your baseline&rdquo;
            rather than guess.
          </p>
          <p>
            We run several independent checks in parallel &mdash;
            each one shaped against a different family of attack.
            The exact way we compose them is something we don&apos;t
            publish. Knowing the recipe would let a sophisticated
            attacker craft activity that scores well without
            actually behaving like the original agent.
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
            We cannot tell you which model your agent is running,
            which prompt template it uses, or whether a specific
            user turn was a jailbreak. We only ever see hashes and
            low-resolution structural signals (lengths, format flags,
            counts, tool names, a salted vocabulary fingerprint) &mdash;
            never the content itself.
          </li>
          <li>
            We cannot distinguish &ldquo;the agent changed because
            an attacker compromised it&rdquo; from &ldquo;the agent
            changed because the operator shipped a new build.&rdquo;
            We surface the divergence; you decide if it&apos;s
            expected.
          </li>
          <li>
            Early in an agent&apos;s life the pattern is still
            taking shape. We will not claim drift before that &mdash;
            it would be sampling noise, not signal &mdash; and the
            panel says so explicitly.
          </li>
          <li>
            Two agents whose behavior happens to be very similar may
            be hard to tell apart from pattern alone &mdash; the{" "}
            <a
              href="/drift-engine/docs/concepts/cryptographic-identity"
              className="font-medium text-foreground hover:underline"
            >
              cryptographic identity
            </a>{" "}
            layer is what proves the identity itself.
          </li>
        </ul>
      </details>

      {/* Testing without polluting the production baseline (#13). Diana's
          concern: how do I try the integration in staging without
          corrupting the baseline my production agent is building? */}
      <div className="rounded-lg border bg-muted/30 p-5">
        <h3 className="text-sm font-semibold text-foreground">
          Testing without disturbing your production baseline
        </h3>
        <p className="mt-2 text-sm text-muted-foreground">
          Each agent learns its baseline from its own event history, so
          test traffic should never flow through the same agent as
          production. To try the integration in staging, register a{" "}
          <strong>separate agent</strong> &mdash; e.g. name it{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">
            test-&lt;your-agent&gt;
          </code>{" "}
          &mdash; and point your staging environment at that agent&apos;s
          key. Its baseline is independent: experiment freely, send
          deliberately weird inputs, restart it &mdash; none of it touches
          the production agent&apos;s history or its drift detection.
        </p>
        <p className="mt-2 text-sm text-muted-foreground">
          When you&apos;re done, you can leave the test agent in place
          (it just sits idle) or revoke it from its settings. A dedicated
          sandbox mode is on the roadmap; until then, a separate{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">test-*</code>{" "}
          agent is the clean way to evaluate without risk.
        </p>
      </div>
    </main>
  );
}

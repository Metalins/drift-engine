/**
 * /docs/concepts/cryptographic-identity — explainer.
 *
 * Sprint UX-5.15.F (task #846) carved from old /docs#cryptographic-identity.
 * Sprint UX-5.15.G (task #847) refined density + added inline diagram.
 * Sprint UX-5.15.I (task #849) — IP protection refactor. The diagram
 * is dropped (it labeled signed → chain → verify in a way that suggested
 * the internal flow). Default view = promise + guarantees only. The
 * detailed mechanism description is behind a collapsible.
 */
export const metadata = {
  title: "Cryptographic identity — Drift Engine docs",
  description:
    "The layer that proves an agent is the same one you registered. Works from event #1, never reads your content.",
  alternates: { canonical: "/drift-engine/docs/concepts/cryptographic-identity" },
};

export default function CryptographicIdentityPage() {
  return (
    <main className="space-y-10">
      <header className="space-y-3 border-b pb-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Concept
        </p>
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
          Cryptographic identity
        </h1>
      </header>

      {/* Default view — promise + guarantees, fits in 1 viewport. */}
      <section className="space-y-5">
        <p className="max-w-3xl text-muted-foreground">
          The layer that proves this agent is the same one you
          registered. Active from the very first event &mdash; binary,
          immediate, and we never see the content.
        </p>

        <div className="rounded-lg border-l-4 border-emerald-500 bg-emerald-500/5 p-5">
          <h3 className="text-sm font-semibold text-foreground">
            What this guarantees
          </h3>
          <ul className="mt-2 space-y-3 text-sm text-muted-foreground">
            <li>
              An entity that does not hold your agent&apos;s secret
              cannot append a single event without producing a
              signature failure Drift Engine will see on receipt.
            </li>
            <li>
              The history is tamper-evident. An attacker with read
              access to your timeline cannot insert, remove, or
              reorder events after the fact &mdash; the next write
              breaks the chain.
            </li>
            <li>
              The same guarantee applies across customer accounts. A
              third party verifying a proof gets the cryptographic
              assurance directly from Drift Engine&apos;s public key, not
              from your dashboard.
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
            Every event your agent sends is signed with a per-agent
            secret only you hold. Drift Engine verifies the signature on
            the way in before the event lands in your timeline, and
            the timeline itself is tamper-evident &mdash; tampering
            with past events breaks subsequent writes in a way we
            see immediately.
          </p>
          <p>
            If an impostor without your secret tries to send an
            event, the signature does not validate and the event is
            rejected. If someone modifies your past timeline, the
            break surfaces on the next legitimate write.
          </p>
          <p>
            A third party verifying a proof from outside your
            account uses Drift Engine&apos;s public key &mdash; they
            don&apos;t need to trust your dashboard.
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
            If your secret leaks to an attacker, that attacker can
            sign events with it. The signatures will validate fine
            &mdash; only the behavior pattern can catch this case.
          </li>
          <li>
            A valid signature proves the event came from a holder of
            the secret. It does not prove it came from the specific
            software you originally registered: ship a new build
            that still holds the same secret and signatures still
            pass.
          </li>
          <li>
            The cryptographic layer cannot tell you anything about
            the content of an event. We never see prompts, responses,
            tool arguments, or user data &mdash; only hashes and the
            low-resolution structural signals the behavioral layer uses
            (lengths, format flags, tool names, a salted vocabulary
            fingerprint).
          </li>
        </ul>
      </details>

      <div className="rounded-lg border bg-muted/30 p-5">
        <p className="text-sm text-muted-foreground">
          <strong className="text-foreground">If you suspect leakage:</strong>{" "}
          rotate the agent&apos;s secret immediately from{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">
            /agents/&lt;id&gt;/keys
          </code>{" "}
          and revoke any active claims. Future signatures from the
          old secret will fail at the verify step.
        </p>
      </div>
    </main>
  );
}

/**
 * /docs/concepts/availability — what happens if Drift Engine is unreachable.
 *
 * Issue #3. Production agents that take real actions (refunds, repo
 * access) treat a hard dependency on an external service as a blocker.
 * This page answers the evaluation question directly: verification is
 * offline-capable (the badge is a cached, signed JWT), only issuance and
 * renewal need connectivity — exactly like renewing a TLS certificate.
 * Copy mirrors docs/product/MVP1-DEFINITION.md § "Disponibilidad y
 * single point of failure". No internal mechanism names (D-PROD.18).
 */
export const metadata = {
  title: "Availability — Drift Engine docs",
  description:
    "What happens to your agent if Drift Engine is unreachable. Verification is offline-capable from a cached public key; only issuing and renewing badges needs connectivity — just like renewing a TLS certificate.",
  alternates: { canonical: "/drift-engine/docs/concepts/availability" },
};

export default function AvailabilityPage() {
  return (
    <main className="space-y-10">
      <header className="space-y-3 border-b pb-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Concept
        </p>
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
          What happens if Drift Engine goes down?
        </h1>
      </header>

      <section className="space-y-5">
        <p className="max-w-3xl text-muted-foreground">
          If your agent issues refunds, touches a code repo, or makes any
          decision that matters, a hard runtime dependency on an external
          service is a blocker &mdash; and a fair question to ask before
          you integrate. The short answer: <strong className="text-foreground">verifying
          an existing badge never calls us</strong>. Only issuing a new
          badge or renewing an expired one needs connectivity.
        </p>

        <div className="rounded-lg border-l-4 border-emerald-500 bg-emerald-500/5 p-5">
          <h3 className="text-sm font-semibold text-foreground">
            Verification is offline-capable
          </h3>
          <p className="mt-2 text-sm text-muted-foreground">
            A Drift Engine badge is a cryptographically signed JWT. To verify
            it, a relying party only needs our public key (JWKS), which it
            can cache locally. If Drift Engine is unreachable, every badge that
            was already issued keeps verifying. It works exactly like TLS:
            your browser doesn&apos;t phone Let&apos;s Encrypt on every page
            load &mdash; it checks the certificate against a key it already
            holds.
          </p>
        </div>

        <div className="rounded-lg border-l-4 border-amber-500 bg-amber-500/5 p-5">
          <h3 className="text-sm font-semibold text-foreground">
            Issuing and renewing needs connectivity
          </h3>
          <p className="mt-2 text-sm text-muted-foreground">
            Registering a new agent or renewing a badge that has expired
            does require Drift Engine to be online. Badges carry a configurable
            TTL (for example, 7 days), so a short outage on our side does
            not break anything already running in your production path. The
            same model you already trust for TLS: the certificate keeps
            working; you only need the CA reachable when it&apos;s time to
            renew.
          </p>
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">
          Two operations, two answers
        </h2>
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left">
              <tr>
                <th className="px-4 py-3 font-medium">Operation</th>
                <th className="px-4 py-3 font-medium">
                  Needs Drift Engine online?
                </th>
                <th className="px-4 py-3 font-medium">If we&apos;re down</th>
              </tr>
            </thead>
            <tbody className="divide-y text-muted-foreground">
              <tr>
                <td className="px-4 py-3">
                  Verifying an existing badge
                </td>
                <td className="px-4 py-3 text-foreground">No</td>
                <td className="px-4 py-3">
                  Keeps working from the cached public key
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3">Logging events from your agent</td>
                <td className="px-4 py-3">
                  Queued client-side, sent when we&apos;re reachable
                </td>
                <td className="px-4 py-3">
                  No data lost; the signed chain catches up on reconnect
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3">
                  Registering a new agent / renewing an expired badge
                </td>
                <td className="px-4 py-3 text-foreground">Yes</td>
                <td className="px-4 py-3">
                  Deferred until we&apos;re back; long TTLs absorb short
                  outages
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div className="rounded-lg border bg-muted/30 p-5">
        <p className="text-sm text-muted-foreground">
          <strong className="text-foreground">In one line:</strong>{" "}
          verification is offline &mdash; you only need our public key,
          cached. Issuing a new badge needs connectivity, just like
          renewing a TLS certificate. Any team that already manages SSL
          certificates knows this trade-off.
        </p>
      </div>
    </main>
  );
}

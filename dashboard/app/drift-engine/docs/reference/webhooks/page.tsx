/**
 * /docs/reference/webhooks — Webhook payload reference.
 *
 * Sprint UX-5.15.F (task #846). Carved from old
 * /docs#webhook-payload-reference. Content preserved verbatim.
 */
export const metadata = {
  title: "Webhook payload — Drift Engine docs",
  description:
    "What your endpoint receives when an agent's cryptographic layer transitions into caution or action_required.",
  alternates: { canonical: "/drift-engine/docs/reference/webhooks" },
};

export default function WebhooksReferencePage() {
  return (
    <main className="space-y-10">
      <header className="space-y-3 border-b pb-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Reference
        </p>
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
          Webhook payload &mdash; what your endpoint receives
        </h1>
        <p className="max-w-3xl text-muted-foreground">
          When the cryptographic layer of one of your agents
          transitions into <em>caution</em> or <em>action_required</em>
          , Drift Engine POSTs a signed JSON body to every active webhook
          on that agent. Behavioral-layer transitions (e.g. baselining
          → stable) are{" "}
          <strong className="text-foreground">silent</strong> &mdash;
          only the cryptographic identity signals page. Configure
          endpoints from{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">
            /agents/&lt;id&gt;/alerts
          </code>
          .
        </p>
      </header>

      <section className="space-y-4">
        <div className="rounded-lg border bg-card/60 p-5">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Request shape
          </h3>
          <pre className="mt-3 overflow-x-auto rounded-md bg-muted/60 p-3 text-xs">
            <code>{`POST <your webhook URL>
Content-Type: application/json
X-Metalins-Signature: sha256=<hex>
User-Agent: Metalins-Webhook/1.0

{
  "event": "verification_state.changed",
  "agent_id": "agt_abc123",
  "agent_name": "support-bot-prod",
  "public_slug": "support-bot-prod",
  "previous_state": "verified",
  "new_state": "caution",
  "confidence": 0.78,
  "score_factors": [
    { "severity": "warning", "code": "behavioral_drift", "message": "Recent activity diverges from the established baseline." }
  ],
  "ts": "2026-05-17T19:00:00Z"
}`}</code>
          </pre>

          <h3 className="mt-5 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Signature validation
          </h3>
          <p className="mt-2 text-sm text-muted-foreground">
            HMAC-SHA256 of the raw body with your webhook&apos;s secret {/* metalins:internal-allowed — webhook signature spec; customer needs the algorithm name to implement verification on their endpoint */}
            (the one Drift Engine showed you ONCE at creation time). The
            signature lives in the{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">
              X-Metalins-Signature
            </code>{" "}
            header as{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">
              sha256=&lt;hex&gt;
            </code>
            . Recompute and compare in constant time.
          </p>

          <pre className="mt-3 overflow-x-auto rounded-md bg-muted/60 p-3 text-xs">
            <code>{`# Node / TypeScript
import { createHmac, timingSafeEqual } from "node:crypto";

function verify(body: string, header: string, secret: string): boolean {
  const expected = "sha256=" + createHmac("sha256", secret)
    .update(body)
    .digest("hex");
  const a = Buffer.from(header);
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}`}</code>
          </pre>

          <h3 className="mt-5 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            What to do on receipt
          </h3>
          <ul className="mt-3 space-y-1.5 text-sm text-muted-foreground">
            <li>
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                new_state === &quot;caution&quot;
              </code>{" "}
              &mdash; a recent cryptographic check flagged something.
              Page your on-call but don&apos;t block production.
            </li>
            <li>
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                new_state === &quot;action_required&quot;
              </code>{" "}
              &mdash; signatures are failing. Treat as a credential
              leak: rotate the agent&apos;s key, revoke active claims,
              page your security on-call.
            </li>
            <li>
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                score_factors
              </code>{" "}
              &mdash; plain-language messages explaining what
              triggered. Useful for the alert body in your incident
              channel.
            </li>
            <li>
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                previous_state
              </code>{" "}
              &mdash; handy for de-duplication if you process the same
              body twice. The transition itself is the dedup key.
            </li>
          </ul>

          <h3 className="mt-5 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Delivery semantics
          </h3>
          <ul className="mt-3 space-y-1.5 text-sm text-muted-foreground">
            <li>
              5-second timeout. If your endpoint takes longer it&apos;s
              counted as a failure.
            </li>
            <li>
              At-most-once for V1 &mdash; no retry queue yet. The
              dashboard shows last delivery status; if you missed one,
              your endpoint can re-verify by reading the current{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                trust
              </code>{" "}
              block from{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                GET /v1/public/agents/&lt;id&gt;
              </code>
              .
            </li>
            <li>
              Best-effort: a flaky endpoint shows{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                last_delivery_error
              </code>{" "}
              in your alerts page. Fix it, future fires resume.
            </li>
          </ul>
        </div>
      </section>
    </main>
  );
}

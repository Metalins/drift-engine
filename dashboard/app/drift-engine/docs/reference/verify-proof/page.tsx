/**
 * /docs/reference/verify-proof — Reference for POST /v1/verify-proof.
 *
 * Sprint UX-5.15.F (task #846). Carved from old
 * /docs#verify-proof-reference. Content preserved verbatim.
 */
export const metadata = {
  title: "Verify-proof reference — Drift Engine docs",
  description:
    "POST /v1/verify-proof — public endpoint to verify an identity claim issued by a Drift Engine agent. No auth required.",
  alternates: { canonical: "/drift-engine/docs/reference/verify-proof" },
};

export default function VerifyProofReferencePage() {
  return (
    <main className="space-y-10">
      <header className="space-y-3 border-b pb-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Prove your agent
        </p>
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
          Verifying a claim from a buyer / integrator
        </h1>
        <p className="max-w-3xl text-muted-foreground">
          When your agent issues a signed claim (from the dashboard or
          programmatically), anyone holding it can ask Drift Engine whether
          it&apos;s authentic. Public endpoint, no API key required
          &mdash; paste it into your buyer&apos;s onboarding docs.
        </p>
      </header>

      <section className="space-y-4">
        <div className="rounded-lg border bg-card/60 p-5">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            curl
          </h3>
          <pre className="mt-3 overflow-x-auto rounded-md bg-muted/60 p-3 text-xs">
            <code>{`curl -X POST https://api.metalins.ai/v1/verify-proof \\
  -H "Content-Type: application/json" \\
  -d '{ "kappa_proof": "eyJhbGciOi..." }'`}</code>
          </pre>

          <p className="mt-3 text-xs text-muted-foreground">
            <code className="rounded bg-muted px-1 py-0.5">
              kappa_proof
            </code>{" "}
            is the signed proof token &mdash; the value returned as{" "}
            <code className="rounded bg-muted px-1 py-0.5">proof</code> by{" "}
            <code className="rounded bg-muted px-1 py-0.5">
              POST /v1/agents/{"{id}"}/proofs
            </code>
            , or resolved from a short{" "}
            <code className="rounded bg-muted px-1 py-0.5">proof_id</code>{" "}
            via{" "}
            <code className="rounded bg-muted px-1 py-0.5">
              GET /v1/public/proofs/{"{proof_id}"}
            </code>
            .
          </p>

          <h3 className="mt-5 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Response &mdash; when the proof is valid
          </h3>
          <pre className="mt-3 overflow-x-auto rounded-md bg-muted/60 p-3 text-xs">
            <code>{`{
  "valid": true,
  "agent_id": "agt_abc123",
  "proof_id": "prf_xyz789",
  "issued_at": "2026-05-17T18:00:00Z",
  "expires_at": "2026-05-17T19:00:00Z",
  "still_active": true,
  "scope": "buyer-onboarding",
  "score": null,
  "steps": null,
  "reason": null
}`}</code>
          </pre>

          <h3 className="mt-5 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Response &mdash; when the proof is invalid or revoked
          </h3>
          <pre className="mt-3 overflow-x-auto rounded-md bg-muted/60 p-3 text-xs">
            <code>{`{
  "valid": false,
  "reason": "revoked",       // or "signature_invalid", "agent_inactive"
  "agent_id": "agt_abc123",  // when known
  "proof_id": "prf_xyz789"   // when known
}`}</code>
          </pre>

          <h3 className="mt-5 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            What to check on your side
          </h3>
          <ul className="mt-3 space-y-1.5 text-sm text-muted-foreground">
            <li>
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                valid === true
              </code>{" "}
              &mdash; the signature matches Drift Engine&apos;s JWKS and
              the claim hasn&apos;t been revoked.
            </li>
            <li>
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                still_active === true
              </code>{" "}
              &mdash; the issuing agent hasn&apos;t been revoked since
              the claim was minted. If false but valid=true, decide
              locally how to treat it (the proof is cryptographically
              authentic but the agent is gone).
            </li>
            <li>
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                scope
              </code>{" "}
              &mdash; optional string the issuer set (e.g.{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                &quot;billing-portal&quot;
              </code>
              ). Match against the action your code is about to take to
              prevent claim re-use across contexts.
            </li>
            <li>
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                expires_at
              </code>{" "}
              &mdash; server-enforced TTL. The endpoint refuses expired
              proofs; you don&apos;t need to re-check the clock
              yourself.
            </li>
          </ul>
        </div>

        <p className="max-w-3xl text-sm text-muted-foreground">
          Public revocation list:{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">
            GET https://api.metalins.ai/v1/revocations?since=ISO_TIMESTAMP
          </code>{" "}
          &mdash; cache it locally if you verify high volumes.
        </p>
      </section>
    </main>
  );
}

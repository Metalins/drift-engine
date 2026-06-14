/**
 * /docs/reference/threat-model — what a Drift Engine link actually proves.
 *
 * Sprint UX-5.15.F (task #846). Carved from old /docs#threat-model.
 * Content preserved verbatim.
 */
import Link from "next/link";

export const metadata = {
  title: "Threat model — Drift Engine docs",
  description:
    "What a Drift Engine verification link proves and what it does not, in three increasing strength modes.",
  alternates: { canonical: "/drift-engine/docs/reference/threat-model" },
};

export default function ThreatModelPage() {
  return (
    <main className="space-y-10">
      <header className="space-y-3 border-b pb-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Prove your agent
        </p>
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
          Threat model: what verification proves
        </h1>
        <p className="max-w-3xl text-muted-foreground">
          A Drift Engine link can prove different things depending on how
          it was generated. The three modes below are listed in order
          of increasing strength. The verify page renders different UI
          for each so a careful visitor can tell which one they have.
        </p>
      </header>

      <section className="space-y-4">
        <div className="space-y-3 rounded-xl border bg-card p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Mode 1 &mdash; Static link
          </h2>
          <p className="text-base">
            <code className="rounded bg-muted px-1 font-mono">
              {`<dashboard-host>/v/<your-agent-slug>`}
            </code>
          </p>
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">Proves:</span>{" "}
            this agent exists and is registered with Drift Engine. The
            verify page shows any verified external anchors (Telegram
            <code className="font-mono">@handle</code>, GitHub user,
            DNS domain) so a visitor can cross-check the operator on a
            platform they already trust.
          </p>
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">
              Does NOT prove:
            </span>{" "}
            that the entity you&apos;re actually talking to right now
            is this agent. Anyone can put this URL in a message
            &mdash; a squatter can copy a real operator&apos;s link
            and paste it in their own channel. The defense is
            cross-checking the anchor: if the verify page says{" "}
            <code className="font-mono">@pepito_bot</code> but
            you&apos;re chatting with{" "}
            <code className="font-mono">@pepit0_bot</code>, the link
            doesn&apos;t apply.
          </p>
        </div>

        <div className="space-y-3 rounded-xl border bg-card p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Mode 2 &mdash; Verification link with reference word
            (recommended)
          </h2>
          <p className="text-base">
            <code className="rounded bg-muted px-1 font-mono break-all">
              {`<dashboard-host>/v/<your-agent-slug>?p=<proof-id>`}
            </code>
          </p>
          <p className="text-xs text-muted-foreground">
            The short{" "}
            <code className="font-mono">?p=&lt;proof-id&gt;</code> form
            (~15 chars) is what the dashboard generates for human
            sharing. A2A integrators can use the equivalent long form{" "}
            <code className="font-mono">?proof=&lt;jwt&gt;</code> (~700
            chars) if they want the verify page to render the proof
            without an extra round-trip.
          </p>
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">Proves:</span>{" "}
            the agent&apos;s owner just generated this link, bound to
            a reference word that the verifier supplied. The verify
            page renders the reference prominently. The proof is
            signed by Drift Engine, expires fast (5 min default), and
            includes the agent_id of the subject. A squatter who only
            sees a victim&apos;s link can&apos;t replicate it: the
            reference word inside won&apos;t match the one the new
            verifier chose.
          </p>
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">
              How to use it (operator):
            </span>{" "}
            in the agent detail page, click{" "}
            <span className="font-medium text-foreground">
              Generate verification proof
            </span>
            , type the reference word the person verifying you asked
            for (e.g.{" "}
            <code className="font-mono">cucumber-42</code>), and copy
            the resulting URL into your chat reply.
          </p>
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">
              How to use it (verifier):
            </span>{" "}
            ask the agent (or its operator) to send a proof with a
            short word YOU choose. Open the link. The verify page must
            show that word as the reference. If it shows a different
            word, treat as suspect &mdash; someone is reusing a link
            meant for someone else.
          </p>
        </div>

        <div className="space-y-3 rounded-xl border bg-card p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Mode 3 &mdash; Programmatic verification (A2A /
            integrators)
          </h2>
          <p className="text-sm text-muted-foreground">
            For agent-to-agent integrations and automated relying
            parties: the same proof JWT is consumable directly via the
            public, unauthenticated endpoint{" "}
            <code className="font-mono">
              POST https://api.metalins.ai/v1/verify-proof
            </code>{" "}
            with body{" "}
            <code className="font-mono">{`{ "kappa_proof": "..." }`}</code>
            . The response includes{" "}
            <code className="font-mono">valid</code>,{" "}
            <code className="font-mono">agent_id</code>,{" "}
            <code className="font-mono">public_slug</code>,{" "}
            <code className="font-mono">scope</code>,{" "}
            <code className="font-mono">issued_at</code>,{" "}
            <code className="font-mono">expires_at</code>,{" "}
            <code className="font-mono">still_active</code>.
          </p>
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">
              Recommended pattern for A2A:
            </span>{" "}
            the relying party generates a fresh random nonce, sends it
            to the agent it&apos;s talking to, asks for a proof with
            that nonce as the scope. The agent calls{" "}
            <code className="font-mono">
              POST /v1/agents/&#123;id&#125;/proofs
            </code>{" "}
            (auth&apos;d) with{" "}
            <code className="font-mono">{`{ "scope": "<nonce>", "ttl_seconds": 300 }`}</code>{" "}
            and returns the JWT. The relying party validates with{" "}
            <code className="font-mono">/v1/verify-proof</code> and
            confirms the returned{" "}
            <code className="font-mono">scope</code> matches the nonce
            it issued. Squatting fails because the squatter
            can&apos;t replicate a fresh nonce-bound proof without the
            real agent&apos;s credentials.
          </p>
          <p className="text-sm text-muted-foreground">
            See the{" "}
            <Link
              href="/drift-engine/docs/reference/verify-proof"
              className="font-medium text-foreground hover:underline"
            >
              Verify-proof reference
            </Link>{" "}
            for the full request/response shape and a curl example.
          </p>
        </div>

        <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-5 text-sm">
          <div className="font-semibold text-foreground">
            What Drift Engine fundamentally cannot prove
          </div>
          <p className="mt-2 text-muted-foreground">
            No public-link verification system can stop someone from
            putting a URL in a message and saying &ldquo;this is
            me&rdquo;. SSL has the same limitation: a valid cert for{" "}
            <code className="font-mono">bbva.com</code> doesn&apos;t
            protect you if you typed{" "}
            <code className="font-mono">bvba.com</code>. The visitor
            always has to do one human step: check that the identity
            shown on the verify page is the same as the entity you
            decided to interact with. Modes 2 and 3 above make that
            check robust against link copying; mode 1 keeps it manual
            via the anchor handle.
          </p>
        </div>
      </section>
    </main>
  );
}

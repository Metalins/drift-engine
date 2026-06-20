/**
 * VerifyCardSet — the visual core of the public verification page.
 *
 * Sprint UX-5.7a (#634) introduced the dual /verify/{id} + /v/{slug} layout.
 *
 * Sprint UX-5.9-A (#650) was the *trust-integrity* rewrite: the old card
 * set only had VerifiedCard / RevokedCard / NotFoundCard and rendered the
 * green "Verified by Metalins" badge for any agent whose row existed in
 * the DB — even a freshly registered one with zero events and no
 * baseline. That was identity theater.
 *
 * Sprint UX-5.12 — two-layer redesign per
 * `docs/product/TWO-LAYER-TRUST-DESIGN.md`. The single `verification_state`
 * dropped because the underlying single-number aggregator was vulnerable
 * to finite-sample MI bias (Exp-CvD finding). We now render two
 * independent blocks per agent, never combining them into one verdict:
 *
 *   ● Cryptographic identity — binary, immediate. Driven by signed
 *     events + MVS probes + revocation. Available from event #1.
 *
 *   ◐ Behavioral baseline — gradual, sample-size aware. Refuses to
 *     make claims below `events_floor` events (~2000). Surfaces drift
 *     only after stabilizing (~5000 events).
 *
 * Decisions (TWO-LAYER-TRUST-DESIGN.md §7.3):
 *   • Two visual blocks per agent. No score numbers. No factor list.
 *     No internal observables. The verify page is two verdicts, not a
 *     dashboard.
 *   • The crypto block sets the card's frame color (frame is the strongest
 *     visual signal): green=verified, amber=caution, red=action/revoked,
 *     grey=unverified.
 *   • Anchors (Sprint UX-5.9-F/G) cross-link to external identity
 *     (Telegram @username, GitHub user, DNS domain).
 *   • Subtle "Powered by Metalins" footer = low-key brand exposure.
 */
import Link from "next/link";
import {
  ShieldCheck,
  ShieldAlert,
  ShieldOff,
  Shield,
  Activity,
  Hourglass,
  TrendingUp,
} from "lucide-react";
import {
  type CryptographicState,
  type BehavioralState,
  type PublicAgentInfo,
  type PublicAnchor,
  type TrustBlock,
  type VerifyProofResult,
} from "@/lib/api";
import { timeAgo } from "@/lib/utils";

export type VerifyResult =
  | { kind: "ok"; info: PublicAgentInfo }
  | { kind: "not_found" }
  | { kind: "error"; message: string };

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

/** Conservative fallback when the server didn't return a `trust` block
 * (older deploy, or unusual error path). We never invent a "verified"
 * state from missing data — fall back to `unverified` + `not_enough_data`
 * so a stale embed degrades to the honest neutral rendering. */
const FALLBACK_TRUST: TrustBlock = {
  cryptographic: {
    state: "unverified",
    since: null,
    last_probe_at: null,
    factors: [],
  },
  behavioral: {
    state: "not_enough_data",
    events_observed: 0,
    events_floor: 2000,
    events_stable: 5000,
    descriptor: null,
    factors: [],
  },
};

export function VerifyCardSet({
  result,
  proof,
}: {
  result: VerifyResult;
  /** Sprint UX-5.11 R2 / R2.4a — when the URL carries `?proof=<JWT>`,
   * the verify page validates it server-side and passes the result
   * here. If valid + scope present, we render a prominent "Reference:
   * <scope>" block above the identity card (the *real* defense against
   * link-squatting). If valid but no scope, we still surface a small
   * "Signed Xs ago" badge but warn that it's not bound to a verifier
   * reference. If absent or invalid, we render a CTA on the static
   * card telling the visitor how to ask for a reference-bound proof. */
  proof?: VerifyProofResult | null;
}) {
  const proofIsValid = Boolean(proof && proof.valid);
  // The proof's `sub` claim is the agent_id; the verify endpoint also
  // returns the agent's slug. We check that the slug in the URL (path)
  // matches the proof's subject so a stale proof for a different agent
  // can't be misrepresented.
  const proofMatchesAgent =
    proofIsValid &&
    result.kind === "ok" &&
    (proof?.agent_id === result.info.agent_id ||
      (proof?.public_slug != null &&
        proof.public_slug === result.info.public_slug));
  return (
    <main className="mx-auto flex min-h-[70vh] max-w-xl flex-col items-center justify-center space-y-6 px-4 py-12">
      {proof && result.kind === "ok" && (
        <ProofBlock
          proof={proof}
          matchesAgent={proofMatchesAgent}
        />
      )}
      {result.kind === "ok" && (
        <TrustCard info={result.info} hasValidProof={proofMatchesAgent} />
      )}
      {result.kind === "not_found" && <NotFoundCard />}
      {result.kind === "error" && (
        <section className="w-full rounded-2xl border bg-card p-8 text-center">
          <h1 className="text-xl font-semibold tracking-tight">
            Verification temporarily unavailable.
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            We couldn&apos;t reach our verification service right now.
            Please try again in a moment.
          </p>
        </section>
      )}
      <PoweredByFooter />
    </main>
  );
}

// --------------------------------------------------------------------------- //
// Top-level card                                                              //
// --------------------------------------------------------------------------- //

// --------------------------------------------------------------------------- //
// Proof block — Sprint UX-5.11 R2 / R2.4c (2026-05-18)                         //
// --------------------------------------------------------------------------- //
//
// Renders when the verify page URL carries `?proof=<JWT>` and the
// backend says it's valid + matches the agent in the URL path.
// Reference (scope) is the dominant visual — it's the piece the
// visitor must mentally compare against the word they asked for.

function ProofBlock({
  proof,
  matchesAgent,
}: {
  proof: VerifyProofResult;
  matchesAgent: boolean;
}) {
  // Invalid proof: amber warning, not the green "live" view.
  if (!proof.valid) {
    return (
      <section className="w-full rounded-2xl border border-amber-500/40 bg-amber-500/5 p-5">
        <div className="text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
          Proof attached, but it doesn&apos;t check out
        </div>
        <p className="mt-2 text-sm text-foreground">
          The proof in this URL is{" "}
          <span className="font-medium">
            {proof.reason ?? "invalid"}
          </span>
          . Treat the rest of this page as a plain registered-identity
          card, not a live verification.
        </p>
      </section>
    );
  }
  // Valid but for a different agent — possible link-tampering or
  // someone reused a proof issued for someone else.
  if (!matchesAgent) {
    return (
      <section className="w-full rounded-2xl border border-red-500/50 bg-red-500/5 p-5">
        <div className="text-xs font-semibold uppercase tracking-wide text-red-700 dark:text-red-400">
          Proof doesn&apos;t match this agent
        </div>
        <p className="mt-2 text-sm text-foreground">
          The proof in this URL is cryptographically valid, but it was
          issued for{" "}
          <span className="font-mono">
            {proof.public_slug ?? proof.agent_id ?? "another agent"}
          </span>{" "}
          — not the agent at this URL. Ask the operator to generate a
          fresh proof for the right agent before trusting this page.
        </p>
      </section>
    );
  }

  const scope = proof.scope ?? null;
  const issuedAt = proof.issued_at ? new Date(proof.issued_at) : null;
  const expiresAt = proof.expires_at ? new Date(proof.expires_at) : null;
  const isExpired = expiresAt && expiresAt.getTime() < Date.now();
  const stillActive = proof.still_active !== false;

  // Active proof: green-framed reference card. The reference (scope)
  // is the dominant element — visitor compares to their word.
  const frameClass = isExpired || !stillActive
    ? "border-amber-500/40 bg-amber-500/5"
    : "border-emerald-500/40 bg-emerald-500/5";

  return (
    <section
      className={`w-full rounded-2xl border p-5 ${frameClass}`}
    >
      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Live proof from the operator
      </div>
      {scope ? (
        <>
          <div className="mt-2 text-xs text-muted-foreground">
            Reference
          </div>
          <div className="mt-1 break-words font-mono text-2xl font-semibold text-foreground">
            {scope}
          </div>
          <p className="mt-3 text-sm text-foreground">
            <span className="font-medium">
              Does this match the word you asked the agent to include?
            </span>{" "}
            If yes, this proof is bound to you specifically — only the
            real operator could have produced it for that reference. If
            no, treat as suspect: someone may have re-shared a link
            meant for a different person.
          </p>
        </>
      ) : (
        <p className="mt-2 text-sm text-foreground">
          This proof is signed by the operator and fresh, but it has
          <span className="font-medium"> no reference word</span>. That
          means anyone with the link can show this page. To get a proof
          bound to YOU, ask the operator to generate a new one and
          include a short phrase you choose.
        </p>
      )}
      <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {issuedAt && (
          <span>
            Signed{" "}
            <span className="text-foreground">{timeAgo(issuedAt.toISOString())}</span>
          </span>
        )}
        {expiresAt && !isExpired && (
          <span>
            Valid for ~
            <span className="text-foreground">
              {Math.max(
                0,
                Math.round((expiresAt.getTime() - Date.now()) / 60000),
              )}{" "}
              min
            </span>{" "}
            more
          </span>
        )}
        {isExpired && (
          <span className="text-amber-700 dark:text-amber-400">
            Proof expired — ask for a fresh one.
          </span>
        )}
        {!stillActive && (
          <span className="text-amber-700 dark:text-amber-400">
            Agent inactive — the proof is authentic but the agent is no
            longer registered.
          </span>
        )}
      </div>
    </section>
  );
}

function TrustCard({
  info,
  hasValidProof = false,
}: {
  info: PublicAgentInfo;
  /** Sprint UX-5.11 R2 / R2.4b — when the page DOESN'T already render
   * a valid proof block, the TrustCard surfaces a CTA explaining how
   * to ask the operator for a reference-bound proof. With a valid
   * proof above we suppress it. */
  hasValidProof?: boolean;
}) {
  const trust = info.trust ?? FALLBACK_TRUST;
  const cryptoState: CryptographicState =
    trust.cryptographic?.state ?? "unverified";

  // Revoked is terminal — drop the behavioral block, render compact
  // "no longer verified" card. The other states all show both blocks.
  if (cryptoState === "revoked") {
    return <RevokedCard info={info} />;
  }

  const frame = frameStyleFor(cryptoState);
  const HeaderIcon = headerIconFor(cryptoState);
  const headline = headlineFor(cryptoState);

  return (
    <section
      className={`w-full rounded-2xl border p-8 text-center md:p-10 ${frame.container}`}
    >
      <div
        className={`mx-auto inline-flex h-16 w-16 items-center justify-center rounded-full ${frame.iconBg}`}
      >
        <HeaderIcon size={32} aria-hidden="true" />
      </div>
      <h1 className="mt-4 text-3xl font-semibold tracking-tight">{headline}</h1>
      <p className="mt-3 text-base text-muted-foreground">
        <span className="font-semibold text-foreground">
          &ldquo;{info.name}&rdquo;
        </span>{" "}
        is a registered Metalins agent.
      </p>
      {/* Sprint UX-5.11 R2 / bug-visitor-1: surface the seller identity
          when an anchor is verified. This is the trust-distribution
          move — a visitor can now read "Operated by @sofia-research
          on Telegram" and cross-check on Telegram themselves instead
          of being asked to trust the Metalins brand alone. */}
      {info.primary_anchor && (
        <p className="mt-2 text-base">
          <span className="text-muted-foreground">Operated by </span>
          <span className="font-semibold text-foreground">
            <AnchorLabel anchor={info.primary_anchor} />
          </span>
          <span className="text-muted-foreground">
            {" "}— verified anchor you can cross-check on{" "}
            {anchorPlatformName(info.primary_anchor.type)}.
          </span>
        </p>
      )}
      {info.last_active && (
        <p className="mt-1 text-sm text-muted-foreground">
          Last active {timeAgo(info.last_active)}.
        </p>
      )}

      <div className="mt-6 space-y-3 text-left">
        <CryptographicBlock layer={trust.cryptographic} info={info} />
        <BehavioralBlock layer={trust.behavioral} />
      </div>

      <AnchorsBlock anchors={info.external_anchors} />

      {/* Sprint UX-5.11 R2 / R2.4b + R2.6 (2026-05-18). Static-mode CTA:
          explain to the visitor that for a stronger guarantee they
          should ask for a reference-bound proof. Copy adapts to the
          agent's integration_surface — MCP/HTTP agents can emit a
          proof on demand themselves, watcher / unknown agents need
          the operator to do it manually from their dashboard. We
          suppress this if a valid proof block already rendered above. */}
      {!hasValidProof && <StaticModeCTA info={info} />}

      <DocsLink className={frame.link} />
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Layer 1 — Cryptographic identity                                            //
// --------------------------------------------------------------------------- //

function CryptographicBlock({
  layer,
  info,
}: {
  layer: TrustBlock["cryptographic"];
  info: PublicAgentInfo;
}) {
  const state = layer?.state ?? "unverified";
  const accent = cryptoAccentFor(state);
  const since = layer?.since ?? info.verified_since;
  return (
    <div className="rounded-lg border bg-background/60 p-3">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        <span
          className={`inline-block h-2 w-2 rounded-full ${accent.dot}`}
          aria-hidden="true"
        />
        Cryptographic identity
      </div>
      <div className="mt-1 text-sm">
        <span className={`font-semibold ${accent.text}`}>
          {cryptoLabelFor(state)}
        </span>
        <span className="text-muted-foreground">
          {" "}
          — {cryptoDetailFor(state, since)}
        </span>
      </div>
    </div>
  );
}

function cryptoLabelFor(state: CryptographicState): string {
  switch (state) {
    case "verified":
      return "Verified";
    case "unverified":
      // Sprint UX-5.11 / bug-sofia-4 (2026-05-17). The old label was
      // "Setting up" + "Treat as untrusted" — which burns Day-1
      // vendors sharing the link before any traffic flows. The agent
      // IS registered with Metalins from the moment it's created;
      // it's just awaiting its first signed activity to upgrade.
      return "Registered";
    case "caution":
      return "Verify with care";
    case "action_required":
      return "Not trusted";
    case "revoked":
      return "Revoked";
  }
}

function cryptoDetailFor(
  state: CryptographicState,
  since: string | null,
): string {
  switch (state) {
    case "verified":
      return since
        ? `signed events match this identity since ${formatDate(since)}.`
        : "signed events match this identity.";
    case "unverified":
      // bug-sofia-4 + bug-visitor-4: reframe for freshly-registered
      // agents. They're not untrusted; they just haven't logged a
      // signed event yet. The earlier draft included "no edit on the
      // owner's end" which leaked owner-side framing onto a visitor
      // page — Visitor explicitly flagged this in Round 0.
      return since
        ? `registered with Metalins since ${formatDate(since)}. The badge upgrades to cryptographically verified once this agent logs its first signed activity.`
        : "registered with Metalins. The badge upgrades to cryptographically verified once this agent logs its first signed activity.";
    case "caution":
      return "a recent cryptographic check flagged something. Confirm before trusting.";
    case "action_required":
      return "cryptographic checks are failing. Do not trust this agent.";
    case "revoked":
      return "the owner revoked this identity.";
  }
}

// --------------------------------------------------------------------------- //
// Layer 2 — Behavioral baseline                                               //
// --------------------------------------------------------------------------- //

function BehavioralBlock({ layer }: { layer: TrustBlock["behavioral"] }) {
  const state: BehavioralState = layer?.state ?? "not_enough_data";
  const observed = layer?.events_observed ?? 0;
  const floor = layer?.events_floor ?? 2000;
  const stable = layer?.events_stable ?? 5000;
  const accent = behavioralAccentFor(state);
  const Icon = behavioralIconFor(state);

  // Progress percentage: scale to the relevant threshold for the current
  // state. While calibrating, the target is the floor. Once we've cleared
  // the floor, the target is the "stable" mark. After stable, the bar
  // stays full because there's nothing further to count up to.
  const target = state === "not_enough_data" ? floor : stable;
  const pct = Math.min(100, Math.round((observed / target) * 100));

  return (
    <div className="rounded-lg border bg-background/60 p-3">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        <Icon size={12} className={accent.text} aria-hidden="true" />
        Behavior pattern
      </div>
      <div className="mt-1 text-sm">
        <span className={`font-semibold ${accent.text}`}>
          {behavioralLabelFor(state)}
        </span>
        <span className="text-muted-foreground">
          {" "}
          — {behavioralDetailFor(state, observed, floor, stable)}
        </span>
      </div>
      {/* Bug-carlos-4: hide progress bar when the layer is in
          "not_enough_data" — to a follower the bar reads as "this
          isn't done yet" which contradicts the green Verified frame
          above. Bar reappears once behavioral tracking is meaningful. */}
      {state !== "not_enough_data" ? (
        <div
          className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted"
          aria-hidden="true"
        >
          <div
            className={`h-full ${accent.bar}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      ) : null}
    </div>
  );
}

// Sprint UX-5.11 / bug-carlos-4 (2026-05-17). Carlos round 0 v1 flagged
// that the third-party verify page showed "20 of ~2,000 events" while
// the cryptographic identity above said "Verified" — reading like the
// page was half-done to a non-technical follower. The labels +
// detail copy below address that audience (Carlos's followers): they
// describe what the agent's behavioral signal MEANS, not the raw
// counter that's useful to the owner. The dashboard-internal view
// (TrustPanel + BaseliningState) still surfaces the raw counts to the
// owner so they know exactly how close they are.

function behavioralLabelFor(state: BehavioralState): string {
  switch (state) {
    case "not_enough_data":
      // bug-visitor-5: "Tracking starts soon" carried surveillance
      // connotations for a third-party visitor. Reframe to describe
      // the data state itself, not the action.
      return "Activity history is light";
    case "building":
      return "Patterns forming";
    case "stable":
      return "Consistent";
    case "drift_detected":
      return "Behavior changed recently";
  }
}

function behavioralDetailFor(
  state: BehavioralState,
  observed: number,
  _floor: number,
  _stable: number,
): string {
  switch (state) {
    case "not_enough_data":
      // bug-visitor-5: was "we'll begin watching this agent's
      // behavioral pattern" — Visitor read it as surveillance language.
      // Describe the data state, not the action.
      return "this agent hasn't logged enough activity yet for a behavioral pattern to be meaningful. The cryptographic check above is what currently confirms identity.";
    case "building":
      return "a behavioral pattern is taking shape. So far it looks consistent with how this agent normally operates.";
    case "stable":
      return "this agent's recent behavior matches how it normally operates.";
    case "drift_detected":
      return `this agent has been behaving differently from its usual pattern (${observed.toLocaleString()}+ events observed). Reach out to the operator before relying on it.`;
  }
}

// --------------------------------------------------------------------------- //
// Card-level visual mapping (driven by the cryptographic state)               //
// --------------------------------------------------------------------------- //

type FrameStyle = {
  container: string;
  iconBg: string;
  link: string;
};

function frameStyleFor(state: CryptographicState): FrameStyle {
  switch (state) {
    case "verified":
      return {
        container: "border-emerald-500/30 bg-emerald-500/[0.04]",
        iconBg: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
        link: "text-emerald-700 dark:text-emerald-400",
      };
    case "unverified":
      return {
        container: "border bg-card",
        iconBg: "bg-muted text-muted-foreground",
        link: "text-foreground",
      };
    case "caution":
      return {
        container: "border-amber-500/40 bg-amber-500/[0.05]",
        iconBg: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
        link: "text-foreground",
      };
    case "action_required":
      return {
        container: "border-destructive/30 bg-destructive/[0.06]",
        iconBg: "bg-destructive/15 text-destructive",
        link: "text-foreground",
      };
    case "revoked":
      return {
        container: "border-destructive/30 bg-destructive/[0.06]",
        iconBg: "bg-destructive/15 text-destructive",
        link: "text-foreground",
      };
  }
}

function headerIconFor(state: CryptographicState) {
  switch (state) {
    case "verified":
      return ShieldCheck;
    case "unverified":
      return Shield;
    case "caution":
      return ShieldAlert;
    case "action_required":
      return ShieldAlert;
    case "revoked":
      return ShieldOff;
  }
}

function headlineFor(state: CryptographicState): string {
  switch (state) {
    case "verified":
      return "Verified by Metalins";
    case "unverified":
      // bug-sofia-4: "Setting up verification" reads as half-done.
      // "Registered with Metalins" is the honest neutral statement
      // for a freshly-created agent that hasn't logged anything yet —
      // it's a true claim, share-able on Day-1.
      return "Registered with Metalins";
    case "caution":
      return "Verified, with caveats";
    case "action_required":
      return "Verification failing";
    case "revoked":
      return "No longer verified";
  }
}

function cryptoAccentFor(state: CryptographicState) {
  switch (state) {
    case "verified":
      return {
        dot: "bg-emerald-500",
        text: "text-emerald-700 dark:text-emerald-400",
      };
    case "unverified":
      return { dot: "bg-muted-foreground", text: "text-muted-foreground" };
    case "caution":
      return {
        dot: "bg-amber-500",
        text: "text-amber-700 dark:text-amber-400",
      };
    case "action_required":
      return { dot: "bg-destructive", text: "text-destructive" };
    case "revoked":
      return { dot: "bg-destructive", text: "text-destructive" };
  }
}

function behavioralAccentFor(state: BehavioralState) {
  switch (state) {
    case "not_enough_data":
      return {
        text: "text-muted-foreground",
        bar: "bg-muted-foreground/50",
      };
    case "building":
      return {
        text: "text-sky-700 dark:text-sky-400",
        bar: "bg-sky-500/70",
      };
    case "stable":
      return {
        text: "text-emerald-700 dark:text-emerald-400",
        bar: "bg-emerald-500/70",
      };
    case "drift_detected":
      return {
        text: "text-amber-700 dark:text-amber-400",
        bar: "bg-amber-500/70",
      };
  }
}

function behavioralIconFor(state: BehavioralState) {
  switch (state) {
    case "not_enough_data":
      return Hourglass;
    case "building":
      return Hourglass;
    case "stable":
      return Activity;
    case "drift_detected":
      return TrendingUp;
  }
}

// --------------------------------------------------------------------------- //
// Terminal cards                                                              //
// --------------------------------------------------------------------------- //

function RevokedCard({ info }: { info: PublicAgentInfo }) {
  return (
    <section className="w-full rounded-2xl border border-destructive/30 bg-destructive/[0.06] p-8 text-center md:p-10">
      <div className="mx-auto inline-flex h-16 w-16 items-center justify-center rounded-full bg-destructive/15 text-destructive">
        <ShieldOff size={32} aria-hidden="true" />
      </div>
      <h1 className="mt-4 text-3xl font-semibold tracking-tight">
        No longer verified
      </h1>
      <p className="mt-3 text-base text-muted-foreground">
        This agent was registered as{" "}
        <span className="font-semibold text-foreground">
          &ldquo;{info.name}&rdquo;
        </span>
        {info.revoked_at
          ? ` but was revoked ${timeAgo(info.revoked_at)}.`
          : " but is no longer active."}{" "}
        Treat it as untrusted.
      </p>
      <DocsLink className="text-foreground" />
    </section>
  );
}

function NotFoundCard() {
  return (
    <section className="w-full rounded-2xl border bg-card p-8 text-center md:p-10">
      <div className="mx-auto inline-flex h-16 w-16 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <ShieldOff size={32} aria-hidden="true" />
      </div>
      <h1 className="mt-4 text-3xl font-semibold tracking-tight">
        Not verified
      </h1>
      <p className="mt-3 text-base text-muted-foreground">
        We couldn&apos;t find a Metalins-registered agent at this link.
        If you received this URL from someone, treat them with the
        suspicion you&apos;d apply to any unsigned message.
      </p>
      <DocsLink className="text-foreground" />
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Shared subcomponents                                                        //
// --------------------------------------------------------------------------- //

function StaticModeCTA({ info }: { info: PublicAgentInfo }) {
  // Sprint UX-5.11 R2 / R2.6 (2026-05-18). The CTA copy adapts to the
  // agent's integration surface. The product priority is MCP/HTTP
  // agents — for those we can specifically tell the visitor "ask the
  // agent itself for a fresh proof", because the operator can issue
  // one on demand bound to a reference word the visitor provides.
  // Watcher-only and unknown surfaces get the generic "ask the
  // operator from their dashboard" copy.
  const surface = info.integration_surface ?? "none";
  const primaryAnchorTelegram =
    info.primary_anchor?.type === "telegram"
      ? info.primary_anchor.value
      : null;

  // MCP/HTTP — the strong story. Ask the AGENT, not just the operator.
  if (surface === "mcp") {
    return (
      <div className="mx-auto mt-5 w-full max-w-sm rounded-lg border border-dashed bg-background/60 p-4 text-left text-sm">
        <div className="font-medium text-foreground">
          Want to confirm this is the agent you&apos;re actually
          interacting with?
        </div>
        <p className="mt-2 text-muted-foreground">
          This is an MCP/HTTP agent — it can issue a proof on demand.
          In the chat or API session where you met it, ask the agent to{" "}
          <span className="font-medium text-foreground">
            generate a verification link
          </span>{" "}
          and include a short reference word you choose{" "}
          <span className="font-mono text-foreground">
            (e.g. &ldquo;cucumber-42&rdquo;)
          </span>
          . It will send you a new URL with that word baked in. Metalins
          validates the proof; you confirm the reference matches.{" "}
          <span className="font-medium text-foreground">
            Only the real operator can produce one bound to your word.
          </span>
        </p>
      </div>
    );
  }

  // Watcher — there's no live API; the OPERATOR (human) generates the
  // proof from their dashboard. Optionally also a Telegram deeplink
  // so the visitor can sanity-check the bot @handle directly.
  if (surface === "watcher") {
    return (
      <div className="mx-auto mt-5 w-full max-w-sm space-y-3 text-left text-sm">
        <div className="rounded-lg border border-dashed bg-background/60 p-4">
          <div className="font-medium text-foreground">
            Want a stronger guarantee than a static link?
          </div>
          <p className="mt-2 text-muted-foreground">
            Message the operator on the platform where you met them and
            ask them to{" "}
            <span className="font-medium text-foreground">
              generate a verification proof
            </span>{" "}
            from their Metalins dashboard. Give them a reference word{" "}
            <span className="font-mono text-foreground">
              (e.g. &ldquo;cucumber-42&rdquo;)
            </span>{" "}
            — they&apos;ll send back a new URL that Metalins binds to
            that word. Only the real operator can produce it.
          </p>
        </div>
        {primaryAnchorTelegram && (
          <div className="rounded-lg border bg-background/60 p-3 text-xs text-muted-foreground">
            <span className="text-foreground">Cross-check:</span> the
            verified Telegram handle for this agent is{" "}
            <code className="rounded bg-muted px-1 font-mono">
              {primaryAnchorTelegram}
            </code>
            . Make sure that&apos;s the exact account you&apos;re
            talking to.{" "}
            <a
              href={`https://t.me/${primaryAnchorTelegram.replace(/^@/, "")}`}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-foreground underline-offset-2 hover:underline"
            >
              Open in Telegram →
            </a>
          </div>
        )}
      </div>
    );
  }

  // No integration yet (event_count==0, no watcher) — neutral copy.
  return (
    <div className="mx-auto mt-5 w-full max-w-sm rounded-lg border border-dashed bg-background/60 p-4 text-left text-sm">
      <div className="font-medium text-foreground">
        Heads up: this agent hasn&apos;t logged any activity yet.
      </div>
      <p className="mt-2 text-muted-foreground">
        It&apos;s registered with Metalins but hasn&apos;t been connected
        via MCP or a watcher. If you&apos;re interacting with something
        that claims to be this agent, ask the operator to finish setup
        and to issue you a verification proof with a reference word you
        choose before trusting it.
      </p>
    </div>
  );
}

function AnchorsBlock({ anchors }: { anchors: PublicAnchor[] | undefined }) {
  // Sprint UX-5.11 R2 / R2.2a (2026-05-18). Earlier (R1.3) we always
  // rendered this section so visitors saw "no anchors" as a signal.
  // In practice that copy ("Trust this badge only as far as you trust
  // the registrant") reads as Metalins throwing its own customers
  // under the bus on the page they share publicly. Two of our own
  // customers flagged it. We're back to: render only when there's at
  // least one verified anchor — the absence of the section is itself
  // a neutral signal, and the primary_anchor hero line above already
  // tells the visitor when there IS a cross-checkable identity.
  if (!anchors || anchors.length === 0) {
    return null;
  }
  return (
    <div className="mx-auto mt-5 w-full max-w-sm rounded-lg border bg-background/60 p-3 text-left">
      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        External anchors
      </div>
      <ul className="mt-2 space-y-1.5 text-sm">
        {anchors.map((a, i) => (
          <li
            key={`${a.type}:${a.value}:${i}`}
            className="flex items-center justify-between gap-3"
          >
            <span>
              <AnchorLabel anchor={a} />
            </span>
            <span className="text-xs text-muted-foreground">
              {a.method}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function anchorPlatformName(type: string): string {
  switch (type) {
    case "telegram":
      return "Telegram";
    case "github":
      return "GitHub";
    case "dns":
      return "the domain";
    default:
      return type;
  }
}

function AnchorLabel({ anchor }: { anchor: PublicAnchor }) {
  switch (anchor.type) {
    case "telegram":
      return (
        <span>
          Telegram bot{" "}
          <span className="font-semibold text-foreground">
            {anchor.value}
          </span>
        </span>
      );
    case "github":
      return (
        <span>
          GitHub user{" "}
          <span className="font-semibold text-foreground">
            @{anchor.value}
          </span>
        </span>
      );
    case "dns":
      return (
        <span>
          Domain{" "}
          <span className="font-semibold text-foreground">{anchor.value}</span>
        </span>
      );
    default:
      return (
        <span>
          <span className="font-semibold text-foreground">{anchor.type}</span>{" "}
          {anchor.value}
        </span>
      );
  }
}

function DocsLink({ className }: { className?: string }) {
  return (
    <div className="mt-6">
      <Link
        href="/drift-engine/docs"
        className={`text-sm font-medium hover:underline ${className ?? ""}`}
      >
        What does Metalins verify? →
      </Link>
    </div>
  );
}

function PoweredByFooter() {
  return (
    <div className="text-xs text-muted-foreground">
      Powered by{" "}
      <Link
        href="/"
        className="font-medium text-foreground hover:underline"
      >
        Metalins
      </Link>{" "}
      &mdash; identity verification for AI agents.
    </div>
  );
}

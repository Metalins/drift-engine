/**
 * /docs — public, indexable documentation hub.
 *
 * Sprint UX-5.15.F (task #846). Refactor of the prior single 4000-word
 * page. The Andrea audit (docs/audits/ANDREA-DOCS-AUDIT-2026-05-19.md)
 * identified the flat 14-pill TOC and the developer-coded headline as
 * the root cause of friction for non-technical visitors. Solution:
 *
 *   • Headline is now "Documentation" (was "Build with Drift Engine" —
 *     "Build" filtered out Andrea-class readers).
 *   • Opener is plain English ("Drift Engine watches your AI agents..."),
 *     no protocol lingo or acronyms in the first impression.
 *   • Flat 14-pill TOC replaced with a four-group grid. Getting started
 *     is the prominent banner. Concepts / Use cases / Reference are
 *     clearly subsidiary.
 *   • Body now 3-5 viewports max. Concepts, use cases and reference
 *     each live on their own sub-route under /docs/...
 *
 * Legacy hash URLs (e.g. /docs#identity-tiers) are redirected to their
 * new home by HashRedirect.tsx on mount. Every documented entry point
 * survives.
 *
 * Indexable by default; canonical is /drift-engine/docs (gh-107 — docs
 * moved under a per-product path; /docs 301s here).
 */
import Link from "next/link";
import HashRedirect from "./HashRedirect";

export const metadata = {
  title: "Drift Engine — Documentation & use cases",
  description:
    "Documentation for the Drift Engine behavioral monitoring platform for AI agents in production. Use cases: drift detection, anti-impersonation, compliance, agent-to-agent trust.",
  alternates: { canonical: "/drift-engine/docs" },
  openGraph: {
    title: "Drift Engine — Documentation & use cases",
    description:
      "Drift Engine is a behavioral monitoring platform for AI agents. Drift detection, anti-impersonation, compliance, agent-to-agent trust.",
    type: "article",
  },
};

type Card = { href: string; title: string; blurb?: string };

const CONCEPTS: Card[] = [
  {
    href: "/drift-engine/docs/concepts/what-metalins-catches",
    title: "What Drift Engine catches",
    blurb:
      "Impersonation, model swaps, prompt injection, bad deploys — the full catalog of problems we detect, and how.",
  },
  {
    href: "/drift-engine/docs/concepts/tiers",
    title: "Identity tiers",
    blurb: "The four-tier ladder of what is actively protecting an agent.",
  },
  {
    href: "/drift-engine/docs/concepts/cryptographic-identity",
    title: "Cryptographic identity",
    blurb:
      "Signed events from day one. What this guarantees, what it doesn't.",
  },
  {
    href: "/drift-engine/docs/concepts/behavioral-baseline",
    title: "Behavior pattern",
    blurb:
      "How we learn your agent's normal pattern and flag when activity stops matching — from hashes, not content.",
  },
  {
    href: "/drift-engine/docs/concepts/drift-detection",
    title: "Drift signals",
    blurb:
      "What a drift signal at Full coverage means — and what it doesn't.",
  },
  {
    href: "/drift-engine/docs/concepts/integration-lifecycle",
    title: "Integration lifecycle",
    blurb:
      "Pause, resume, reset, remove. What each one does, and why your agent can change without breaking.",
  },
];

const USE_CASES: Card[] = [
  {
    href: "/drift-engine/docs/use-cases/personal",
    title: "Personal AI",
    blurb: "Anti-impersonation for public bots on Telegram, Discord, X.",
  },
  {
    href: "/drift-engine/docs/use-cases/drift",
    title: "Drift detection",
    blurb: "Catch silent model swaps, prompt injection and bad deploys.",
  },
  {
    href: "/drift-engine/docs/use-cases/compliance",
    title: "Compliance & audit",
    blurb: "Tamper-evident logs without surrendering your data.",
  },
];

// "Prove your agent" — the third-party / agent-to-agent trust story.
// The pages keep their /reference and /use-cases URLs; this is a
// navigation grouping (Tanda B).
const PROVE: Card[] = [
  {
    href: "/drift-engine/docs/reference/threat-model",
    title: "Threat model",
    blurb:
      "What a verification link proves — and what it can't — in each of the three modes.",
  },
  {
    href: "/drift-engine/docs/reference/verify-proof",
    title: "Verify-proof endpoint",
    blurb:
      "POST /v1/verify-proof — how a relying party checks a claim. curl + response shapes.",
  },
  {
    href: "/drift-engine/docs/use-cases/agent-to-agent",
    title: "Agent-to-agent",
    blurb: "Cryptographic trust between agents across organizations.",
  },
];

const REFERENCE: Card[] = [
  {
    href: "/drift-engine/docs/reference/developer-api",
    title: "HTTP API",
    blurb:
      "Register agents, stream events, issue proofs — curl + Python SDK.",
  },
  {
    href: "/drift-engine/docs/reference/webhooks",
    title: "Webhook payload",
    blurb: "Signed JSON body, signature validation, delivery semantics.",
  },
];

function GroupHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
      {children}
    </h2>
  );
}

function CardLink({ href, title, blurb }: Card) {
  return (
    <Link
      href={href}
      className="block rounded-lg border bg-card p-4 transition-colors hover:border-foreground/40 hover:bg-accent/50"
    >
      <div className="text-sm font-medium text-foreground">{title}</div>
      {blurb && (
        <p className="mt-1 text-sm text-muted-foreground">{blurb}</p>
      )}
    </Link>
  );
}

export default function DocsHubPage() {
  return (
    <main className="space-y-10">
      <HashRedirect />

      {/* ----- Header ------------------------------------------------- */}
      <header className="space-y-3 border-b pb-8">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Drift Engine
        </p>
        <h1 className="text-4xl font-semibold tracking-tight">
          Drift Engine — Documentation
        </h1>
        <p className="max-w-3xl text-lg text-muted-foreground">
          Drift Engine is a behavioral monitoring platform for AI agents in
          production. It gives each agent a verifiable identity and watches
          for the ways an agent can go wrong &mdash; someone impersonating
          it, the model underneath being swapped, an injection hijacking it,
          a deploy quietly changing it. It surfaces what changed and asks
          you; you decide if it was expected. And the identity it gives each
          agent is verifiable by others &mdash; a buyer, an integrator, or
          another agent can check it for themselves. All of it from hashes
          &mdash; we never read your prompts, your responses, or your
          users&apos; data.
        </p>
      </header>

      {/* ----- Getting started — prominent banner -------------------- */}
      <section>
        <Link
          href="/drift-engine/docs/getting-started"
          className="block rounded-2xl border bg-card p-6 transition-colors hover:border-foreground/40 hover:bg-accent/40 md:p-8"
        >
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Getting started
          </p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight md:text-3xl">
            Start here
          </h2>
          <p className="mt-2 max-w-2xl text-base text-muted-foreground">
            What Drift Engine is, our privacy model, and how to plug an agent
            in via the HTTP API / SDK.
          </p>
          <p className="mt-4 text-sm font-medium text-foreground">
            Read the intro →
          </p>
        </Link>
      </section>

      {/* ----- Subsidiary groups ------------------------------------- */}
      <section className="space-y-4">
        <GroupHeading>Concepts</GroupHeading>
        <p className="text-sm text-muted-foreground">
          What is actually running under the hood, and what each layer
          can (and can&apos;t) claim.
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {CONCEPTS.map((c) => (
            <CardLink key={c.href} {...c} />
          ))}
        </div>
      </section>

      <section className="space-y-4">
        <GroupHeading>Use cases</GroupHeading>
        <p className="text-sm text-muted-foreground">
          Concrete situations Drift Engine solves, with how-it-works steps
          and integration notes.
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {USE_CASES.map((c) => (
            <CardLink key={c.href} {...c} />
          ))}
        </div>
      </section>

      <section className="space-y-4">
        <GroupHeading>Prove your agent</GroupHeading>
        <p className="text-sm text-muted-foreground">
          Show a third party &mdash; a buyer, an integrator, another
          agent &mdash; that your agent is who it claims to be: what a
          link proves, how a relying party checks it, and the
          agent-to-agent flow.
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {PROVE.map((c) => (
            <CardLink key={c.href} {...c} />
          ))}
        </div>
      </section>

      <section className="space-y-4">
        <GroupHeading>Reference</GroupHeading>
        <p className="text-sm text-muted-foreground">
          Endpoints and payload shapes.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          {REFERENCE.map((c) => (
            <CardLink key={c.href} {...c} />
          ))}
        </div>
      </section>

      {/* ----- CTA --------------------------------------------------- */}
      <section className="rounded-2xl border bg-card p-8 text-center">
        <h2 className="text-xl font-semibold tracking-tight">
          Try Drift Engine
        </h2>
        <p className="mx-auto mt-2 max-w-xl text-sm text-muted-foreground">
          Magic-link signup. Five minutes from zero to a verifiable
          agent.
        </p>
        <div className="mt-5 flex justify-center gap-3">
          <Link
            href="/login"
            className="rounded-md bg-primary px-5 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Get started
          </Link>
          <Link
            href="/"
            className="rounded-md border px-5 py-2 text-sm font-medium hover:bg-accent"
          >
            Back to home
          </Link>
        </div>
      </section>

      {/* ----- Contact ----------------------------------------------- */}
      <section className="rounded-xl border bg-card p-6 text-sm">
        <h3 className="font-medium">Get in touch</h3>
        <p className="mt-1 text-muted-foreground">
          Questions, integrations, business inquiries:{" "}
          <a href="mailto:support@metalins.com" className="underline">
            support@metalins.com
          </a>
          .
        </p>
      </section>
    </main>
  );
}

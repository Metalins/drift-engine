/**
 * /docs/concepts/what-metalins-catches — the catalog of problems
 * Drift Engine detects.
 *
 * UX-5.17 docs pass. Jose feedback: the docs framed Drift Engine narrowly
 * as "identity verification" — proving the agent is the one you
 * registered — when it is really protective monitoring: it catches a
 * concrete set of problems (impersonation, model swaps, prompt
 * injection, bad deploys, config drift). This page is that catalog —
 * each problem collapsed by default, expanded to explain what it is,
 * how Drift Engine catches it, and what you see.
 *
 * Content rule: customer-facing, D-PROD.18 — no internal mechanism
 * names. We speak "cryptographic identity", "behavior pattern",
 * "drift signal", "verification check"; never the engine's taxonomy.
 * Each item is honest about the "we surface, you decide" limit.
 */
import Link from "next/link";

export const metadata = {
  title: "What Drift Engine catches — Drift Engine docs",
  description:
    "The problems Drift Engine detects: impersonation and clones, leaked secrets, silent model swaps, prompt injection, bad deploys, and configuration drift — and how each one is caught.",
  alternates: { canonical: "/drift-engine/docs/concepts/what-metalins-catches" },
};

function Catch({
  title,
  summary,
  children,
}: {
  title: string;
  summary: string;
  children: React.ReactNode;
}) {
  return (
    <details className="group rounded-lg border bg-card p-5">
      <summary className="cursor-pointer list-none">
        <span className="mr-2 inline-block text-muted-foreground transition-transform group-open:rotate-90">
          ›
        </span>
        <span className="text-sm font-semibold text-foreground">
          {title}
        </span>
        <span className="mt-1 block pl-5 text-sm text-muted-foreground">
          {summary}
        </span>
      </summary>
      <div className="mt-4 space-y-3 pl-5 text-sm text-muted-foreground">
        {children}
      </div>
    </details>
  );
}

export default function WhatMetalinsCatchesPage() {
  return (
    <main className="space-y-10">
      <header className="space-y-3 border-b pb-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Concept
        </p>
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
          What Drift Engine catches
        </h1>
        <p className="max-w-3xl text-muted-foreground">
          Drift Engine isn&apos;t only an answer to &ldquo;is this my
          agent?&rdquo; It&apos;s protective monitoring: it watches each
          agent and catches a concrete set of ways an agent can go wrong
          &mdash; someone impersonating it, the model underneath being
          swapped, an injection hijacking it, a deploy quietly changing
          it. Below is the full list. Each one is collapsed; open it for
          what the problem is, how Drift Engine catches it, and what you
          see.
        </p>
      </header>

      {/* ----- The two layers, briefly ------------------------------- */}
      <section className="space-y-3">
        <p className="max-w-3xl text-sm text-muted-foreground">
          Everything here is caught by one of two layers, and entirely
          from hashes &mdash; Drift Engine never reads your prompts or
          responses. The{" "}
          <Link
            href="/drift-engine/docs/concepts/cryptographic-identity"
            className="font-medium text-foreground hover:underline"
          >
            cryptographic identity
          </Link>{" "}
          layer answers <em>is this the exact agent you registered?</em>{" "}
          The{" "}
          <Link
            href="/drift-engine/docs/concepts/behavioral-baseline"
            className="font-medium text-foreground hover:underline"
          >
            behavior pattern
          </Link>{" "}
          layer answers <em>is it still behaving the way it used
          to?</em>
        </p>
      </section>

      {/* ----- The catalog ------------------------------------------- */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold tracking-tight">
          The problems
        </h2>

        <Catch
          title="Someone clones or impersonates your agent"
          summary="An attacker stands up their own agent and passes it off as yours — same name, same branding, a copied verification link."
        >
          <p>
            Your agent has a cryptographic identity bound to its real,
            continuous history. A clone can&apos;t reproduce that
            history, so it can&apos;t answer Drift Engine&apos;s verification
            checks correctly &mdash; it never earns a verified mark,
            while your real agent keeps one.
          </p>
          <p>
            <span className="font-medium text-foreground">You see:</span>{" "}
            the clone&apos;s cryptographic layer reads{" "}
            <em>action required</em>; a third party who checks a live
            proof from the clone sees it doesn&apos;t hold up.
          </p>
        </Catch>

        <Catch
          title="Your agent's secret leaks"
          summary="The credential your agent uses to verify itself ends up somewhere it shouldn't — a committed env file, a shared log."
        >
          <p>
            The secret alone is not enough to impersonate the agent.
            Verification also depends on the agent&apos;s continuous
            history, which whoever copied the secret doesn&apos;t have.
            A leaked-secret clone still fails the verification checks.
          </p>
          <p>
            <span className="font-medium text-foreground">You see:</span>{" "}
            <em>action required</em> on the cryptographic layer. The
            recommended response is to rotate the secret &mdash; reissue
            a fresh one from the agent&apos;s settings, which retires the
            leaked one.
          </p>
        </Catch>

        <Catch
          title="The model behind your agent is swapped"
          summary="The LLM powering your agent is changed — a cheaper model, a different vendor, a quantized variant — without your knowledge."
        >
          <p>
            The agent still &ldquo;works,&rdquo; just differently. A
            different model produces a different behavior pattern. Once
            your agent&apos;s pattern has settled, Drift Engine recognizes
            that new activity no longer fits and raises a drift signal.
          </p>
          <p>
            <span className="font-medium text-foreground">You see:</span>{" "}
            a{" "}
            <Link
              href="/drift-engine/docs/concepts/drift-detection"
              className="underline"
            >
              drift signal
            </Link>{" "}
            on the behavior layer, timestamped to the window where the
            pattern changed. It tells you the pattern changed and
            roughly when &mdash; you confirm whether the swap was
            intentional.
          </p>
        </Catch>

        <Catch
          title="Your agent is hijacked by prompt injection"
          summary="A crafted input overrides the agent's instructions mid-conversation, and it starts doing things it was never built to do."
        >
          <p>
            A hijacked agent stops behaving like itself. The behavior
            layer flags the divergence from its settled pattern, the
            same way it would catch a swap.
          </p>
          <p>
            <span className="font-medium text-foreground">You see:</span>{" "}
            a drift signal. Honest limit: Drift Engine works from hashes, so
            it surfaces <em>that</em> behavior changed and roughly{" "}
            <em>when</em> &mdash; it never saw the content, so it
            can&apos;t point at the exact malicious turn.
          </p>
        </Catch>

        <Catch
          title="A bad deploy quietly changes behavior"
          summary="A deploy ships a regression — a prompt-template tweak, a dependency bump — that changes how the agent behaves, and review missed it."
        >
          <p>
            From Drift Engine&apos;s side this looks like a swap or a
            hijack: the behavior pattern shifts, and the divergence is
            caught. The point is that you find out &mdash; a quiet
            behavior regression that no test covered still surfaces.
          </p>
          <p>
            <span className="font-medium text-foreground">You see:</span>{" "}
            a drift signal timestamped to the window it started in.
            Compare that window against your deploy log to find the
            change responsible.
          </p>
        </Catch>

        <Catch
          title="Your agent isn't running the way you declared it"
          summary="You set the agent up one way — say, strict and reproducible — but it's actually running another way, so verification under- or over-fires."
        >
          <p>
            Drift Engine watches how the agent actually behaves and compares
            it to the profile you declared at setup. A mismatch means
            the wrong checks are running &mdash; either false alarms on
            normal variation, or weaker protection than you expected.
          </p>
          <p>
            <span className="font-medium text-foreground">You see:</span>{" "}
            a specific, actionable alert that names the mismatch and
            tells you which setting to change. You can update it any
            time from the agent&apos;s settings.
          </p>
        </Catch>
      </section>

      {/* ----- Honest framing ---------------------------------------- */}
      <section className="space-y-3">
        <div className="rounded-lg border-l-4 border-amber-500 bg-amber-500/5 p-5 text-sm text-muted-foreground">
          <p className="font-medium text-foreground">
            A signal is a reason to look, not a verdict.
          </p>
          <p className="mt-2">
            For the behavior-layer problems above, Drift Engine can&apos;t
            tell a compromise apart from a change you made on purpose
            &mdash; it doesn&apos;t see content. It surfaces the
            divergence and timestamps it; you decide whether it was
            expected. The cryptographic-layer problems are different:
            those are binary, and a failed verification check is not
            ambiguous.
          </p>
          <p className="mt-2">
            It also can&apos;t tell those behavior-layer problems apart
            from <em>each other</em>. A model swap, a prompt injection
            and a bad deploy all reach Drift Engine as the same thing: one
            drift signal that says the pattern changed and roughly
            when. The signal tells you <em>where</em> to look &mdash;
            your deploy log, your model config, the conversation in
            that window &mdash; not which of the three it was.
          </p>
        </div>
      </section>

      {/* ----- Footer links ------------------------------------------ */}
      <section className="rounded-2xl border bg-card p-6 text-sm">
        <h2 className="font-semibold tracking-tight text-foreground">
          Go deeper
        </h2>
        <p className="mt-2 max-w-3xl text-muted-foreground">
          Each layer has its own page:{" "}
          <Link
            href="/drift-engine/docs/concepts/cryptographic-identity"
            className="font-medium text-foreground hover:underline"
          >
            cryptographic identity
          </Link>
          ,{" "}
          <Link
            href="/drift-engine/docs/concepts/behavioral-baseline"
            className="font-medium text-foreground hover:underline"
          >
            behavior pattern
          </Link>
          , and{" "}
          <Link
            href="/drift-engine/docs/concepts/drift-detection"
            className="font-medium text-foreground hover:underline"
          >
            drift signals
          </Link>
          . When you change an agent on purpose, the{" "}
          <Link
            href="/drift-engine/docs/concepts/integration-lifecycle"
            className="font-medium text-foreground hover:underline"
          >
            integration lifecycle
          </Link>{" "}
          covers how to tell Drift Engine so it doesn&apos;t flag it. Not
          connected yet? Start at{" "}
          <Link
            href="/drift-engine/docs/getting-started"
            className="font-medium text-foreground hover:underline"
          >
            Getting started
          </Link>
          .
        </p>
      </section>
    </main>
  );
}

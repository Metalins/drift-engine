/**
 * /docs/getting-started — What Drift Engine is, how verification works,
 * the privacy model, the three ways to connect, and a quickstart.
 *
 * Sprint UX-5.15.F (#846) split the old anchors into this page.
 *
 * UX-5.17 rewrite: the page was reworded end to end. It now flows
 * concept → connect → code: what Drift Engine is, the two verification
 * layers, the privacy model, the three ways to connect (API-first),
 * and only then the quickstart — framed as the concrete form of the
 * recommended path, not as "the Python SDK is the product". Snippet
 * code comes from the shared `lib/api-snippets` builders.
 */
import Link from "next/link";
import { PIP_INSTALL, sdkRegisterSnippet } from "@/lib/api-snippets";

export const metadata = {
  title: "Getting started — Drift Engine docs",
  description:
    "What Drift Engine is, how two-layer verification works, the hashes-only privacy model, how to connect an AI agent via the HTTP API / SDK, and a copy-paste quickstart.",
  alternates: { canonical: "/drift-engine/docs/getting-started" },
};

/**
 * Board #36 (Diana-only MVP) — HIDE, NOT DELETE.
 *
 * Flip to `true` to restore the full "Three ways to connect" menu
 * (public-bot watcher + MCP alongside the SDK). While `false`, Getting
 * Started shows only the SDK / HTTP-API path so Diana reaches the three
 * lines of Python without detouring through a Telegram bot or an MCP
 * config. The bot-watcher and MCP list items are only gated by this
 * flag, never removed — reactivating them is a one-line change.
 */
const SHOW_ALL_CONNECT_PATHS = false;

function Code({ children }: { children: string }) {
  return (
    <pre className="overflow-x-auto rounded-md bg-muted/60 p-3 text-xs leading-relaxed">
      <code>{children}</code>
    </pre>
  );
}

export default function GettingStartedPage() {
  return (
    <main className="space-y-12">
      <header className="space-y-3 border-b pb-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Getting started
        </p>
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
          Start here
        </h1>
        <p className="max-w-2xl text-lg text-muted-foreground">
          Drift Engine continuously monitors each of your AI agents in
          production — and never sees your data doing it. It&apos;s
          self-hosted: you run your own instance, then point the SDK at it.
          Here&apos;s what that means, how to deploy it, and how to connect
          your first agent — end to end, no account required.
        </p>
      </header>

      {/* ----- Step 0: deploy first (self-hosted) — gh-109 ----------- */}
      {/* Drift Engine is self-hosted: every later step (mint an API key,
          point the SDK at METALINS_BASE_URL) assumes an instance is
          already running. Surface that prerequisite up front so a reader
          stands up their server before the SDK flow, instead of hitting
          "which dashboard?" halfway down. Links to the full deploy guide
          (clone → docker compose up) further down this page. */}
      <section
        id="step-0"
        className="scroll-mt-24 rounded-lg border-l-4 border-primary bg-primary/5 p-5"
      >
        <p className="text-xs font-semibold uppercase tracking-wide text-primary">
          Step 0 · before anything else
        </p>
        <h2 className="mt-1 text-lg font-semibold tracking-tight">
          Deploy your Drift Engine server
        </h2>
        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
          Drift Engine is self-hosted — there is no shared SaaS to sign up
          for. Before you mint an API key or point the SDK anywhere, you need
          your own instance running. The whole stack (FastAPI server +
          Postgres) comes up with{" "}
          <span className="font-mono text-xs">git clone</span> then{" "}
          <span className="font-mono text-xs">docker compose up</span>.
        </p>
        <p className="mt-3 text-sm">
          <a
            href="#self-host"
            className="font-medium text-primary hover:underline"
          >
            Jump to the deploy guide ↓
          </a>
        </p>
      </section>

      {/* ----- Zero Trust context — Issue #39 ----------------------- */}
      <section id="zero-trust" className="scroll-mt-24 space-y-3 rounded-lg border bg-card/40 p-5">
        <h2 className="text-base font-semibold tracking-tight">
          Why Zero Trust requires continuous behavioral verification
        </h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Zero Trust security says: never trust, always verify. For
          networks and APIs, this is solved — every request is
          authenticated. For AI agents running in production, there is
          a gap: access control decides what the agent is{" "}
          <em>allowed</em> to do, but nothing continuously verifies
          that the agent doing it is{" "}
          <em>still the one you deployed</em>.
        </p>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Anthropic&apos;s{" "}
          <strong>Zero Trust Framework for AI Agents</strong> (June 2026)
          names this gap explicitly. Drift Engine closes it: we implement
          the continuous post-deploy verification layer that Zero Trust
          requires &mdash; cryptographic identity from event one,
          behavioral drift detection as your agent runs.
        </p>
      </section>

      {/* ----- What is Drift Engine -------------------------------------- */}
      <section id="what-is" className="scroll-mt-24 space-y-4">
        <h2 className="text-2xl font-semibold tracking-tight">
          What Drift Engine is
        </h2>
        <p className="max-w-3xl text-muted-foreground">
          Drift Engine is a behavioral monitoring platform for AI agents in
          production. It gives every agent a verifiable identity: at any
          moment you can prove an agent is still the one you set up — and
          be told when something changed without your knowledge: a
          swapped model, an injected prompt, a bad deploy, a clone.
        </p>
        <p className="max-w-3xl text-muted-foreground">
          You bring the agent — a backend LLM pipeline, a coding
          assistant, a Discord bot, anything. From its first logged
          event, Drift Engine gives it a cryptographic identity and a
          tamper-evident timeline of what it did. As it runs, Drift Engine
          also learns its behavior pattern and tells you when activity
          stops matching it.
        </p>
        <p className="max-w-3xl text-muted-foreground">
          That identity is also portable. When your agent needs to
          prove itself to someone else — a customer, an integrator,
          another agent — it can hand over a signed claim that anyone
          can verify against one public endpoint, with no Drift Engine
          account required.
        </p>
      </section>

      {/* ----- Two layers of verification --------------------------- */}
      <section id="verification" className="scroll-mt-24 space-y-4">
        <h2 className="text-2xl font-semibold tracking-tight">
          Two layers of verification
        </h2>
        <p className="max-w-3xl text-muted-foreground">
          Drift Engine reports two independent signals. It never blends them
          into one score — each answers a different question, and each
          becomes trustworthy on its own schedule.
        </p>
        <div className="rounded-lg border bg-card/60 p-5">
          <ul className="space-y-3 text-sm text-muted-foreground">
            <li>
              <span className="font-medium text-foreground">
                Cryptographic identity
              </span>{" "}
              &mdash; binary and immediate. Live from the very first
              event. It answers: <em>is this the exact agent you
              registered?</em>
            </li>
            <li>
              <span className="font-medium text-foreground">
                Behavior pattern
              </span>{" "}
              &mdash; gradual and sample-size aware. It answers:{" "}
              <em>is the agent still behaving the way it used to?</em>{" "}
              Until enough events have landed for the pattern to settle,
              Drift Engine says it&apos;s still learning your baseline &mdash;
              it doesn&apos;t fabricate a number.
            </li>
          </ul>
        </div>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Between the two layers, Drift Engine catches a concrete set of
          problems &mdash; someone impersonating your agent, the model
          underneath being swapped, an injection hijacking it, a deploy
          quietly changing it. The{" "}
          <Link
            href="/drift-engine/docs/concepts/what-metalins-catches"
            className="font-medium text-foreground hover:underline"
          >
            What Drift Engine catches
          </Link>{" "}
          page lists them all, with how each one is detected.
        </p>
        <p className="max-w-3xl text-sm text-muted-foreground">
          How much is actively protecting an agent climbs over time. The{" "}
          <Link
            href="/drift-engine/docs/concepts/tiers"
            className="font-medium text-foreground hover:underline"
          >
            identity tiers
          </Link>{" "}
          page explains that ladder.
        </p>
      </section>

      {/* ----- Privacy model ---------------------------------------- */}
      <section id="privacy" className="scroll-mt-24 space-y-4">
        <h2 className="text-2xl font-semibold tracking-tight">
          Your data stays private
        </h2>
        <div className="rounded-lg border-l-4 border-emerald-500 bg-emerald-500/5 p-5">
          <p className="text-sm text-foreground">
            <strong>
              We never see your prompts, responses, tool arguments, or
              users&apos; data.
            </strong>
          </p>
          <p className="mt-2 text-sm text-muted-foreground">
            However you connect, every event is hashed on your side
            before it reaches us. We store only the hashes &mdash; plus a
            few low-resolution structural signals the SDK measures in your
            process (lengths, format flags, sentence counts, the names of
            tools called, latency, and a salted, irreversible fingerprint
            of the output&apos;s vocabulary). Enough to prove identity and
            spot behavioral drift, never enough to learn what your agent
            said. You can opt out of the structural signals with{" "}
            <span className="font-mono text-xs">compute_behavioral=False</span>;
            see{" "}
            <a
              href="/drift-engine/docs/concepts/what-leaves-your-infra"
              className="font-medium text-foreground hover:underline"
            >
              what leaves your infra
            </a>
            .
          </p>
        </div>
        <p className="max-w-3xl text-muted-foreground">
          That&apos;s what lets Drift Engine serve regulated work &mdash;
          GDPR Art. 32, SOC 2 evidence collection, the EU AI Act &mdash;
          and what sets it apart from observability tools that pipe your
          full traffic through their servers.
        </p>
      </section>

      {/* ----- Three ways to connect -------------------------------- */}
      <section id="connect" className="scroll-mt-24 space-y-4">
        <h2 className="text-2xl font-semibold tracking-tight">
          {SHOW_ALL_CONNECT_PATHS ? "Three ways to connect" : "How to connect"}
        </h2>
        <p className="max-w-3xl text-muted-foreground">
          {SHOW_ALL_CONNECT_PATHS
            ? "Pick the path that matches how your agent runs. You can change it later from the agent's settings — and each path has a full walkthrough of its own."
            : "Drift Engine connects to a backend agent you run in your own code: call the HTTP API directly, or drop in the SDK, which wraps it in a few lines."}
        </p>
        <ol className="space-y-3 text-sm">
          {/* Board #36: bot-watcher path hidden, not deleted. */}
          {SHOW_ALL_CONNECT_PATHS && (
          <li className="rounded-md border bg-card p-4">
            <span className="font-medium">1. Public-bot watcher</span>{" "}
            <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              · no code
            </span>
            <p className="mt-1 text-muted-foreground">
              The fastest start if you&apos;d rather not touch code.
              Paste a public bot&apos;s token and Drift Engine polls its
              messages. Telegram works today; Discord, Slack, and X are
              on the roadmap.{" "}
              <Link
                href="/drift-engine/docs/getting-started/bot-watcher"
                className="font-medium text-foreground hover:underline"
              >
                Public-bot watcher →
              </Link>
            </p>
          </li>
          )}
          <li className="rounded-md border bg-card p-4">
            <span className="font-medium">
              {SHOW_ALL_CONNECT_PATHS ? "2. HTTP API / SDK" : "HTTP API / SDK"}
            </span>{" "}
            {SHOW_ALL_CONNECT_PATHS && (
              <span className="text-xs font-medium uppercase tracking-wide text-primary">
                · primary
              </span>
            )}
            <p className="mt-1 text-muted-foreground">
              For a backend agent you run in your own code, and the path
              we build the product around. Call the HTTP API directly
              from any language, or drop in the SDK, which wraps it —
              either way it reports events <em>and</em> answers
              verification checks.{" "}
              <Link
                href="/drift-engine/docs/reference/developer-api"
                className="font-medium text-foreground hover:underline"
              >
                HTTP API / SDK reference →
              </Link>
            </p>
          </li>
          {/* Board #36: MCP path hidden, not deleted. */}
          {SHOW_ALL_CONNECT_PATHS && (
          <li className="rounded-md border bg-card p-4">
            <span className="font-medium">3. MCP server</span>
            <p className="mt-1 text-muted-foreground">
              For an assistant that lives inside a chat or editor —
              Claude Desktop, Claude Code, Cursor, or any MCP-aware
              client. One line of client config, no code on your side.{" "}
              <Link
                href="/drift-engine/docs/getting-started/mcp-setup"
                className="font-medium text-foreground hover:underline"
              >
                MCP setup →
              </Link>
            </p>
          </li>
          )}
        </ol>
      </section>

      {/* ----- Deploy your own instance (self-hosted) ---------------- */}
      {/* gh-106 (2026-06-15): Drift Engine is self-hosted (AGPL-3.0).
          metalins.com is the lab's reference instance, not a SaaS you sign
          up for — getting started means standing up your OWN instance. This
          is the end-to-end deploy path (clone → docker compose up → point
          the SDK at it) so a dev can be running in their own infra without
          leaving for the GitHub README or needing an account anywhere. */}
      <section id="self-host" className="scroll-mt-24 space-y-5">
        <h2 className="text-2xl font-semibold tracking-tight">
          Deploy your own instance
        </h2>
        <p className="max-w-3xl text-muted-foreground">
          Drift Engine runs on your infrastructure. There is no account to
          create and no shared server it phones home to &mdash; you run the
          verification server, and the SDK talks only to it. The stack
          (FastAPI server + Postgres) comes up with a single command.
        </p>

        <ol className="space-y-6">
          <li className="space-y-2">
            <p className="font-medium">
              1. Clone the repository
            </p>
            <Code>{`git clone https://github.com/Metalins/drift-engine
cd drift-engine`}</Code>
          </li>

          <li className="space-y-2">
            <p className="font-medium">2. Configure (optional)</p>
            <p className="max-w-3xl text-sm text-muted-foreground">
              Every setting has a working default, so the stack runs as-is.
              Copy the example env file and edit only what you need &mdash;
              for a real deployment that&apos;s typically{" "}
              <span className="font-mono text-xs">METALINS_DB_URL</span>{" "}
              (to point at your own Postgres) and{" "}
              <span className="font-mono text-xs">
                METALINS_PUBLIC_BASE_URL
              </span>{" "}
              (the public URL your instance is reachable at, baked into the
              κ-Proofs it issues).
            </p>
            <Code>{`cp .env.example .env   # then edit if needed — defaults work out of the box`}</Code>
          </li>

          <li className="space-y-2">
            <p className="font-medium">3. Signing keypair</p>
            <p className="max-w-3xl text-sm text-muted-foreground">
              The server signs κ-Proofs with an RS256 keypair.{" "}
              <strong>docker compose generates it automatically</strong> on
              first boot and persists it in a named volume, so you can skip
              ahead. Generate one by hand only if you run the server outside
              Docker (or want to manage your own keys):
            </p>
            <Code>{`# only if NOT using docker compose:
cd server && python scripts/generate_keypair.py`}</Code>
          </li>

          <li className="space-y-2">
            <p className="font-medium">4. Start the stack</p>
            <Code>{`docker compose up   # (or: docker-compose up)`}</Code>
            <p className="max-w-3xl text-sm text-muted-foreground">
              On first boot the server generates its keypair, waits for
              Postgres, creates the schema, and prints a{" "}
              <strong>dev API key</strong> in the logs (it&apos;s shown
              once &mdash; copy it). Confirm it&apos;s live:
            </p>
            <Code>{`curl http://localhost:8000/health
# -> {"status":"ok","service":"metalins-server"}

# the public key others use to verify your agent's κ-Proofs:
curl http://localhost:8000/.well-known/jwks.json`}</Code>
            <p className="max-w-3xl text-sm text-muted-foreground">
              Lost the key? <span className="font-mono text-xs">docker
              compose logs server | grep ml_dev_</span>. The dashboard
              (Next.js) is a separate deploy target &mdash; the server +
              API above is the core that issues and verifies κ-Proofs.
            </p>
          </li>

          <li className="space-y-2">
            <p className="font-medium">
              5. Point the SDK at your instance
            </p>
            <p className="max-w-3xl text-sm text-muted-foreground">
              Install the SDK and tell it where your server lives. There is
              no default endpoint &mdash; set{" "}
              <span className="font-mono text-xs">METALINS_BASE_URL</span>{" "}
              (or pass{" "}
              <span className="font-mono text-xs">base_url=</span> to{" "}
              <span className="font-mono text-xs">metalins_drift.Agent</span>
              ) and authenticate with the API key from step 4.
            </p>
            <Code>{`pip install metalins-drift
export METALINS_BASE_URL=http://localhost:8000   # your instance
export METALINS_API_KEY=ml_dev_...               # from the server logs`}</Code>
          </li>
        </ol>

        {/* Optional: production deploy target. */}
        <div className="rounded-lg border bg-card/40 p-5">
          <p className="text-sm font-semibold">
            Going to production? Deploy to GCP Cloud Run.
          </p>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            The repo ships an idempotent{" "}
            <span className="font-mono text-xs">
              server/deploy-cloudrun.sh
            </span>{" "}
            that builds the image, manages secrets, deploys to Cloud Run
            (scale-to-zero), and runs smoke tests &mdash; see{" "}
            <span className="font-mono text-xs">
              docs/dev/DEPLOY-CLOUDRUN.md
            </span>{" "}
            in the{" "}
            <a
              href="https://github.com/Metalins/drift-engine"
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-foreground hover:underline"
            >
              repository
            </a>
            . Point your SDK&apos;s{" "}
            <span className="font-mono text-xs">METALINS_BASE_URL</span> at
            the resulting service URL instead of{" "}
            <span className="font-mono text-xs">localhost</span>.
          </p>
        </div>
      </section>

      {/* ----- Quickstart -------------------------------------------- */}
      <section id="quickstart" className="scroll-mt-24 space-y-4">
        <h2 className="text-2xl font-semibold tracking-tight">
          Connect your first agent
        </h2>
        <p className="max-w-3xl text-muted-foreground">
          With your instance running (above), the HTTP API is the surface —
          it works from any language. The quickest concrete start is the
          SDK, which wraps it. Mint an API key from your instance&apos;s
          dashboard (or use the dev key the server printed on first boot),
          then add one block to your agent&apos;s startup and one call per
          turn:
        </p>
        <Code>{PIP_INSTALL}</Code>
        <Code>{sdkRegisterSnippet()}</Code>
        <p className="max-w-3xl text-sm text-muted-foreground">
          That&apos;s the whole integration — the SDK reports each
          interaction <em>and</em> answers verification checks in the
          background. Not on Python? The{" "}
          <Link
            href="/drift-engine/docs/reference/developer-api"
            className="font-medium text-foreground hover:underline"
          >
            HTTP API reference
          </Link>{" "}
          is the same contract from any language; an SDK wrapper for
          Python ships today, with more languages to follow.
        </p>
      </section>

      {/* ----- CTA --------------------------------------------------- */}
      {/* gh-106 (2026-06-15): self-hosted — the CTA is "clone and run your
          own instance", not "sign up". Removed the magic-link/signup copy
          and the /login link (there is no public signup); point at the
          deploy steps above and the GitHub repo instead. */}
      <section className="rounded-2xl border bg-card p-8 text-center">
        <h2 className="text-xl font-semibold tracking-tight">
          Ready to run it
        </h2>
        <p className="mx-auto mt-2 max-w-xl text-sm text-muted-foreground">
          Clone the repo, <span className="font-mono text-xs">docker
          compose up</span>, and point the SDK at your instance — minutes
          from zero to a verifiable agent, all on your own infrastructure.
        </p>
        <div className="mt-5 flex justify-center gap-3">
          <a
            href="#self-host"
            className="rounded-md bg-primary px-5 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Deploy your instance
          </a>
          <a
            href="https://github.com/Metalins/drift-engine"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-md border px-5 py-2 text-sm font-medium hover:bg-accent"
          >
            View on GitHub
          </a>
          <Link
            href="/drift-engine/docs"
            className="rounded-md border px-5 py-2 text-sm font-medium hover:bg-accent"
          >
            Back to docs hub
          </Link>
        </div>
      </section>
    </main>
  );
}

/**
 * /docs/getting-started/bot-watcher — public primer for the
 * public-bot watcher integration path.
 *
 * Sprint UX-5.17 docs pass. The three ways to connect each get a
 * page under "Getting started": HTTP API / SDK, MCP setup, and —
 * added here — the public-bot watcher. Until now the watcher was
 * only described inside /docs/use-cases/personal, which the
 * API-first reorg left hard to find. This is the dedicated,
 * public, indexable how-to, parallel to mcp-setup/page.tsx.
 *
 * The real setup (paste your token) lives in the dashboard at
 * /agents/[id]/watchers/setup, gated behind login. This page is the
 * pre-signup walkthrough — it shows the shape of the flow so a
 * visitor knows what connecting a bot means before they sign up.
 *
 * Content rule: customer-facing, D-PROD.18 — no internal mechanism
 * names. We speak "event", "verification", "tier".
 */
import Link from "next/link";

export const metadata = {
  title: "Public-bot watcher — Drift Engine docs",
  description:
    "Connect a public bot to Drift Engine with zero code — paste the bot's token and Drift Engine polls its public messages, hashing them locally.",
  alternates: { canonical: "/drift-engine/docs/getting-started/bot-watcher" },
};

function Step({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <li className="flex gap-3">
      <span
        className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-foreground text-xs font-semibold text-background"
        aria-hidden="true"
      >
        {n}
      </span>
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <div className="text-sm text-muted-foreground">{children}</div>
      </div>
    </li>
  );
}

export default function BotWatcherPage() {
  return (
    <main className="space-y-10">
      <header className="space-y-3 border-b pb-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Getting started
        </p>
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
          Public-bot watcher
        </h1>
        <p className="max-w-3xl text-muted-foreground">
          The zero-code way in. Paste your public bot&apos;s token and
          Drift Engine polls its messages on a schedule, hashes them, and
          identity-tracks the bot &mdash; no package to install, no code
          on your side. Best for creators running a customer-facing bot
          who want a verification badge their followers can check.
        </p>
      </header>

      {/* ----- When to use it --------------------------------------- */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">
          When the watcher is the right path
        </h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Pick the watcher when your agent <em>is</em> a public bot &mdash;
          something followers already message on a platform like Telegram.
          You don&apos;t run its code, or you&apos;d rather not touch it.
          Drift Engine watches from the outside.
        </p>
        <p className="max-w-3xl text-sm text-muted-foreground">
          If your agent runs in your own backend, the{" "}
          <Link
            href="/drift-engine/docs/reference/developer-api"
            className="font-medium text-foreground hover:underline"
          >
            HTTP API / SDK
          </Link>{" "}
          gives fuller coverage. If it lives inside a chat or editor
          client, use{" "}
          <Link
            href="/drift-engine/docs/getting-started/mcp-setup"
            className="font-medium text-foreground hover:underline"
          >
            MCP setup
          </Link>
          . You can change paths later from the agent&apos;s settings.
        </p>
      </section>

      {/* ----- Privacy ---------------------------------------------- */}
      <section className="space-y-3">
        <h2 className="text-xl font-semibold tracking-tight">
          What Drift Engine sees
        </h2>
        <div className="rounded-lg border-l-4 border-emerald-500 bg-emerald-500/5 p-5">
          <p className="text-sm text-foreground">
            <strong>Only hashes. Never message content.</strong>
          </p>
          <p className="mt-2 text-sm text-muted-foreground">
            The watcher fetches your bot&apos;s public messages, computes
            a sha256 hash of each one, and stores <em>only</em> the hash.
            The text itself is never written to our database. Your bot
            token is held encrypted at rest and used solely to poll the
            platform.
          </p>
        </div>
      </section>

      {/* ----- What you'll do --------------------------------------- */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">
          What you&apos;ll do
        </h2>
        <ol className="space-y-4">
          <Step n={1} title="Create an agent in the dashboard">
            Sign in and open{" "}
            <Link
              href="/agents/new"
              className="font-medium text-foreground hover:underline"
            >
              New agent
            </Link>
            . Give it a name &mdash; this is the identity your followers
            will verify.
          </Step>
          <Step n={2} title="Pick “Public bot watcher” on the connect screen">
            Right after creation the dashboard asks how the agent
            connects. Choose the <strong>Public bot watcher</strong> card.
            It routes you to the bot setup page for that agent.
          </Step>
          <Step n={3} title="Paste your bot token">
            Drop in your bot&apos;s API token (see below for how to get a
            Telegram one). Drift Engine validates it, stores it encrypted,
            and registers the watcher.
          </Step>
          <Step n={4} title="Watch the events arrive">
            Drift Engine polls the platform every few seconds. As your bot
            posts, the event count on its detail page ticks up and the{" "}
            <Link
              href="/drift-engine/docs/concepts/tiers"
              className="font-medium text-foreground hover:underline"
            >
              tier
            </Link>{" "}
            climbs from <em>Registered</em> upward.
          </Step>
        </ol>
        <p className="max-w-3xl text-sm text-muted-foreground">
          That&apos;s the whole integration &mdash; no code, no deploy.
          The dashboard walks you through the same steps with your real
          agent filled in.
        </p>
      </section>

      {/* ----- Telegram token --------------------------------------- */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">
          Getting a Telegram bot token
        </h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Telegram is the platform supported today. If your bot already
          exists you have a token; if not, Telegram&apos;s own BotFather
          mints one:
        </p>
        <ol className="ml-1 list-decimal space-y-1.5 pl-5 text-sm leading-relaxed text-muted-foreground">
          <li>
            In Telegram, open a chat with{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">
              @BotFather
            </code>
            .
          </li>
          <li>
            Send{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">
              /newbot
            </code>{" "}
            and follow the prompts for a name and username.
          </li>
          <li>
            BotFather replies with an API token &mdash; a string like{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">
              123456789:AAE…
            </code>
            . That&apos;s what you paste into Drift Engine.
          </li>
        </ol>
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-muted-foreground">
          Treat the token like a password. Drift Engine stores it encrypted,
          but if it ever leaks elsewhere, revoke it with BotFather&apos;s{" "}
          <code className="rounded bg-muted px-1 py-0.5">/revoke</code> and
          paste the new one.
        </div>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Discord, Slack, and X are on the roadmap &mdash; one public-bot
          platform per agent.
        </p>
      </section>

      {/* ----- After it's connected --------------------------------- */}
      <section className="space-y-3">
        <h2 className="text-xl font-semibold tracking-tight">
          After it&apos;s connected
        </h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Once events are flowing, the agent&apos;s detail page shows its
          live verification state, and you can publish a public verify
          link &mdash; a page anyone can open to confirm they&apos;re
          talking to the real bot. If you pause the bot or change it,
          Drift Engine flags the change rather than failing silently; see the{" "}
          <Link
            href="/drift-engine/docs/concepts/integration-lifecycle"
            className="font-medium text-foreground hover:underline"
          >
            integration lifecycle
          </Link>{" "}
          for what pause, resume, and reset each do.
        </p>
      </section>

      {/* ----- Footer cross-links ----------------------------------- */}
      <section className="rounded-2xl border bg-card p-6 text-sm">
        <h2 className="font-semibold tracking-tight text-foreground">
          Not a public bot?
        </h2>
        <p className="mt-2 max-w-3xl text-muted-foreground">
          The watcher only fits agents that post publicly. For a backend
          service you own, use the{" "}
          <Link
            href="/drift-engine/docs/reference/developer-api"
            className="font-medium text-foreground hover:underline"
          >
            HTTP API / SDK
          </Link>
          ; for an assistant inside Claude Desktop, Claude Code, or
          Cursor, use{" "}
          <Link
            href="/drift-engine/docs/getting-started/mcp-setup"
            className="font-medium text-foreground hover:underline"
          >
            MCP setup
          </Link>
          .
        </p>
      </section>
    </main>
  );
}

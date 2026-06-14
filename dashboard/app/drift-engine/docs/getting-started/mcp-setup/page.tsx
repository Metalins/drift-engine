/**
 * /docs/getting-started/mcp-setup — Generic walkthrough of MCP setup.
 *
 * Sprint UX-5.15.H (task #848). The MCP setup with the user's actual
 * API key lives at /agents/[id]/mcp (per-agent, gated behind login).
 * This doc page is the public-facing primer: shows the shape of each
 * client's config (Claude Code, Cursor, Claude Desktop) so a visitor
 * understands what plugging in means before they sign up.
 *
 * The real configuration page in the dashboard injects the agent's
 * key and the right URL; this page uses placeholders.
 */

export const metadata = {
  title: "MCP setup — Drift Engine docs",
  description:
    "How to plug an AI agent into Drift Engine via MCP — one line of config in Claude Code, Cursor, or Claude Desktop.",
  alternates: { canonical: "/drift-engine/docs/getting-started/mcp-setup" },
};

const MCP_BASE = "https://api.metalins.ai/mcp";

function ConfigBlock({
  title,
  description,
  code,
}: {
  title: string;
  description: string;
  code: string;
}) {
  return (
    <div className="rounded-lg border bg-card p-5">
      <h3 className="text-sm font-semibold tracking-tight text-foreground">
        {title}
      </h3>
      <p className="mt-2 text-sm text-muted-foreground">{description}</p>
      <pre className="mt-3 overflow-x-auto rounded-md bg-muted/60 p-3 text-xs">
        <code>{code}</code>
      </pre>
    </div>
  );
}

export default function McpSetupPage() {
  return (
    <main className="space-y-10">
      <header className="space-y-3 border-b pb-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Getting started
        </p>
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
          MCP setup
        </h1>
        <p className="max-w-3xl text-muted-foreground">
          Plug an AI client into Drift Engine by pasting one block of
          configuration. Once the client is connected, every agent
          action it takes is identity-tracked &mdash; no code on your
          side, no package to install.
        </p>
      </header>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">
          What you&apos;ll do
        </h2>
        <ol className="space-y-2 text-sm text-muted-foreground">
          <li>
            <span className="font-medium text-foreground">1.</span>{" "}
            Create an agent from{" "}
            <a
              href="/agents/new"
              className="font-medium text-foreground underline underline-offset-2"
            >
              New agent
            </a>{" "}
            in the dashboard, then mint a key &mdash; the{" "}
            <a
              href="/keys"
              className="font-medium text-foreground underline underline-offset-2"
            >
              API keys page
            </a>{" "}
            issues one that works across all your agents.
          </li>
          <li>
            <span className="font-medium text-foreground">2.</span>{" "}
            Paste a config block into your client (Claude Code, Cursor,
            or Claude Desktop &mdash; pick the one you use).
          </li>
          <li>
            <span className="font-medium text-foreground">3.</span>{" "}
            Restart the client. From the next action onwards, the
            event count on your agent&apos;s detail page ticks up.
          </li>
        </ol>
        <p className="max-w-3xl text-sm text-muted-foreground">
          The dashboard walks you through the same flow with your real
          key filled in. This page just shows the shape of each
          client&apos;s config so you can preview it.
        </p>
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">
          Per-client config
        </h2>
        <p className="text-sm text-muted-foreground">
          Replace{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">
            YOUR_METALINS_KEY
          </code>{" "}
          with the plaintext key, and{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">
            metalins-AGENT
          </code>{" "}
          with a per-agent name like{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">
            metalins-claude-desktop
          </code>
          . The dashboard fills both in automatically once you mint a key.
        </p>

        <div className="space-y-4">
          <ConfigBlock
            title="Claude Code (CLI)"
            description="One-time command — URL is positional; --scope user installs it for every project on the machine."
            code={`claude mcp add --transport http metalins-AGENT ${MCP_BASE}/jsonrpc \\
  -H "Authorization: Bearer YOUR_METALINS_KEY" \\
  --scope user`}
          />
          <ConfigBlock
            title="Cursor"
            description="Paste into ~/.cursor/mcp.json (global) or .cursor/mcp.json (this project):"
            code={`{
  "mcpServers": {
    "metalins-AGENT": {
      "url": "${MCP_BASE}/jsonrpc",
      "headers": {
        "Authorization": "Bearer YOUR_METALINS_KEY"
      }
    }
  }
}`}
          />
          {/* Claude Desktop: HTTP MCP servers must be added through the
              in-app Settings, NOT via claude_desktop_config.json (that
              file is stdio-only). Show the UI flow instead of a JSON
              block that would silently fail. */}
          <div className="rounded-lg border bg-card p-5">
            <h3 className="text-sm font-semibold tracking-tight text-foreground">
              Claude Desktop
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              Claude Desktop reads HTTP MCP servers from the in-app UI,
              not from the config file. Add Drift Engine like this:
            </p>
            <ol className="mt-3 space-y-1.5 pl-5 text-sm leading-relaxed text-muted-foreground [&>li]:list-decimal">
              <li>
                Open <strong>Settings &rarr; Connectors</strong>.
              </li>
              <li>
                Click <strong>Add custom connector</strong>.
              </li>
              <li>
                Name: <code className="rounded bg-muted px-1 py-0.5 text-xs">Drift Engine</code>.
                Remote MCP server URL:{" "}
                <code className="break-all rounded bg-muted px-1 py-0.5 text-xs">
                  {MCP_BASE}/jsonrpc
                </code>
                .
              </li>
              <li>
                Under <strong>Advanced &rarr; Custom headers</strong>, add{" "}
                <code className="rounded bg-muted px-1 py-0.5 text-xs">Authorization</code> with value{" "}
                <code className="break-all rounded bg-muted px-1 py-0.5 text-xs">
                  Bearer YOUR_METALINS_KEY
                </code>
                . Save.
              </li>
            </ol>
            <p className="mt-3 text-xs text-muted-foreground">
              Custom connectors require a Claude paid plan (Pro / Max /
              Team / Enterprise). Free-tier users should use Claude Code
              or Cursor above.
            </p>
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold tracking-tight">
          Verify it&apos;s working
        </h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Restart your client and ask it to do anything that triggers
          an action. Within a few seconds, the event count on your
          agent&apos;s detail page should tick up. The tier badge
          starts at <em>Registered</em> and progresses as more events
          arrive &mdash; the{" "}
          <a
            href="/drift-engine/docs/concepts/tiers"
            className="font-medium text-foreground hover:underline"
          >
            identity tiers
          </a>{" "}
          page explains the ladder.
        </p>
        <p className="max-w-3xl text-sm text-muted-foreground">
          From then on the agent&apos;s detail page is where you watch
          its verification state. If you later change the assistant or
          move machines, Drift Engine flags the change rather than failing
          silently &mdash; see the{" "}
          <a
            href="/drift-engine/docs/concepts/integration-lifecycle"
            className="font-medium text-foreground hover:underline"
          >
            integration lifecycle
          </a>
          .
        </p>
      </section>

      <section className="rounded-2xl border bg-card p-6 text-sm">
        <h2 className="font-semibold tracking-tight text-foreground">
          What if I don&apos;t use an MCP-aware client?
        </h2>
        <p className="mt-2 max-w-3xl text-muted-foreground">
          Two other ways to connect. If your agent is a public bot, use
          the{" "}
          <a
            href="/drift-engine/docs/getting-started/bot-watcher"
            className="font-medium text-foreground hover:underline"
          >
            public-bot watcher
          </a>{" "}
          &mdash; paste the bot&apos;s token and Drift Engine polls it for
          you, zero code on your side. If it&apos;s a backend service you
          run in your own code, use the{" "}
          <a
            href="/drift-engine/docs/reference/developer-api"
            className="font-medium text-foreground hover:underline"
          >
            HTTP API / SDK
          </a>
          .
        </p>
      </section>
    </main>
  );
}

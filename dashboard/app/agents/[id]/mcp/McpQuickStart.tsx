/**
 * McpQuickStart — Step 2 + Step 3 of /agents/[id]/mcp as ONE client
 * component, so the plaintext key minted in step 2 can flow into the
 * step-3 snippets without the user having to substitute
 * `YOUR_API_KEY` by hand.
 *
 * Sprint UX-5.15.K (task #852). Jose feedback 2026-05-19: the previous
 * version of this page showed `YOUR_API_KEY` placeholders even
 * after the user just minted a real key — every single MCP onboarding
 * paid a copy-paste-edit tax. Now step 3 snippets render with the
 * actual key the moment step 2 produces one, and there's a single
 * "Copy command" / "Copy config" button per block.
 *
 * The Claude Code CLI syntax was also wrong (`--url <U>` doesn't
 * exist; URL is positional). Fixed in this same component, plus in
 * /docs/getting-started/mcp-setup/page.tsx for the public docs.
 *
 * Security: the plaintext only ever lives in this component's local
 * React state. It is wiped when the user clicks "I've copied it —
 * dismiss" in KeyManager (which clears its own state, but the parent
 * state survives until reload because the user might still be copying
 * snippets). For an extra safety margin we expose an explicit "Hide
 * key from snippets" affordance below the snippets too.
 *
 * ─── Sprint UX-5.15.R (D-PROD.26 — MVP-SCOPE.md) ──────────────────
 *
 * Added a third block: "Copy this into your agent's system prompt."
 * The MCP transport only delivers events when the LLM client decides
 * to call a tool, so a chat-heavy surface (Claude Desktop, ChatGPT,
 * Cursor in conversational mode) will go quiet for long stretches. To
 * give Andrea-tier users a parcial-but-honest path to coverage without
 * having to bolt on a desktop wrapper, we ship a copy-paste system
 * prompt block that nudges the LLM to call `metalins_log_event` after
 * every meaningful action. The agent_id is inlined literally (post
 * UX-5.15.Q, slugs are also accepted but the canonical form is the
 * `agt_…` id, and we want the LLM to use exactly that). The disclaimer
 * below the snippet is honest about the failure mode: this works as
 * well as the LLM cooperates, and Diana-tier (backend) customers
 * don't need it because their orchestration code calls tools
 * deterministically.
 */
"use client";

import { useState } from "react";
import { KeyManager, type CreatedKey } from "../keys/KeyManager";
import type { ApiKeySummary } from "@/lib/api";
import {
  MCP_URL,
  PLACEHOLDER,
  mcpServerName,
  buildClientConfigSnippets,
  buildSystemPromptSnippet,
  buildConversationPrimerSnippet,
} from "@/lib/mcp-snippets";
import { CopyButton } from "./CopyButton";
import { ConfigBlock } from "./ConfigBlock";

// UX-5.15.T (2026-05-19): the snippet builders + UI primitives that
// used to live inline here were extracted to `lib/mcp-snippets.ts`,
// `./CopyButton.tsx`, and `./ConfigBlock.tsx` so the new
// step-by-step wizard at `/mcp/setup` can render the same blocks
// without code duplication. The visible behavior of this page is
// unchanged — only the imports moved.

interface Props {
  agentId: string;
  agentName: string;
  initialKeys: ApiKeySummary[];
}

export function McpQuickStart({ agentId, agentName, initialKeys }: Props) {
  // The plaintext stays in memory only; we never persist it. The user
  // can clear it manually too (button below the snippets).
  const [mintedSecret, setMintedSecret] = useState<string | null>(null);

  // Per-agent MCP server name (Sprint UX-5.15.M follow-up). Avoids the
  // "MCP server metalins already exists in user config" error Jose hit
  // when he registered a second agent.
  const serverName = mcpServerName(agentName);

  const keyForSnippets = mintedSecret ?? PLACEHOLDER;
  const snippets = buildClientConfigSnippets(keyForSnippets, serverName);
  const hasRealKey = mintedSecret != null;

  return (
    <>
      <section className="rounded-lg border bg-card p-6">
        <h2 className="text-sm font-semibold tracking-tight text-foreground">
          Create an MCP key
        </h2>
        <p className="mt-2 mb-4 text-sm text-muted-foreground">
          MCP authenticates with a Bearer token. Keys you create from
          here work across every agent in your account &mdash; one key
          lets your client log to all of them. We&apos;ll inline the
          value into the snippets below the moment you mint it, so you
          can copy a ready-to-run command.
        </p>
        {/* Sprint UX-5.15.M — Andrea fix F1. The previous copy said
            "scoped to this agent" + linked /keys for "all agents",
            which felt like a hidden mismatch when the customer later
            found the key only on /keys, not on /agents/[id]/keys. The
            backend creates these keys customer-wide; the copy now
            says so up front. The list below lists THIS account's
            active keys (filtered to the ones usable for MCP — i.e.
            scoped to no agent or to this one). */}
        <div className="mb-4 rounded-md border border-blue-500/40 bg-blue-500/10 p-3 text-xs">
          You can also manage keys for the whole account at{" "}
          <a
            href="/keys"
            className="font-medium underline underline-offset-2"
          >
            /keys
          </a>
          .
        </div>
        <KeyManager
          agentId={agentId}
          initialKeys={initialKeys}
          onKeyMinted={(k: CreatedKey) => setMintedSecret(k.secret)}
        />
      </section>

      <section className="rounded-lg border bg-card p-6">
        <h2 className="text-sm font-semibold tracking-tight text-foreground">
          Paste this into your client
        </h2>
        {hasRealKey ? (
          <p className="mt-2 mb-4 text-sm text-muted-foreground">
            Below are the configs with your fresh key inlined. Pick the
            client you use and click <strong>Copy</strong> — no
            substitution needed.
          </p>
        ) : (
          <p className="mt-2 mb-4 text-sm text-muted-foreground">
            Pick the client you use. The placeholder gets replaced
            automatically the moment you mint a key above.
          </p>
        )}

        <div className="space-y-5">
          <ConfigBlock
            title="Claude Code (CLI)"
            description="One-time command — installs the server globally for every Claude Code project on this machine."
            code={snippets.claudeCode}
            copyLabel="Copy command"
            hasRealKey={hasRealKey}
          />
          <ConfigBlock
            title="Cursor"
            description="Paste into ~/.cursor/mcp.json (global) or .cursor/mcp.json (this project):"
            code={snippets.cursor}
            copyLabel="Copy config"
            hasRealKey={hasRealKey}
          />
          {/* Claude Desktop does NOT support HTTP MCP servers via the
              config JSON. Per Anthropic's official help docs, remote
              connectors must be added through the in-app Settings UI.
              Showing a JSON snippet here would have users paste it
              into claude_desktop_config.json and watch nothing happen.
              Replaced with the actual UI flow. */}
          <div className="rounded-md border bg-muted/30 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-sm font-medium">Claude Desktop</div>
                <div className="mt-0.5 text-xs text-muted-foreground">
                  Add through the in-app Settings UI &mdash; the config
                  file route is stdio-only and won&apos;t reach a remote
                  HTTP server.
                </div>
              </div>
              {hasRealKey && (
                <CopyButton
                  value={mintedSecret!}
                  label="Copy key"
                />
              )}
            </div>
            <ol className="mt-3 space-y-1.5 pl-5 text-xs leading-relaxed text-muted-foreground [&>li]:list-decimal">
              <li>
                Open <strong>Settings &rarr; Connectors</strong> in
                Claude Desktop.
              </li>
              <li>
                Click <strong>Add custom connector</strong>.
              </li>
              <li>
                Set <strong>Name</strong> to{" "}
                <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                  {serverName}
                </code>{" "}
                and <strong>Remote MCP server URL</strong> to{" "}
                <code className="break-all rounded bg-muted px-1 py-0.5 text-[11px]">
                  {MCP_URL}
                </code>
                .
              </li>
              <li>
                Under <strong>Advanced &rarr; Custom headers</strong>,
                add{" "}
                <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                  Authorization
                </code>
                {" "}with value{" "}
                <code className="break-all rounded bg-muted px-1 py-0.5 text-[11px]">
                  Bearer {hasRealKey ? mintedSecret : PLACEHOLDER}
                </code>
                . Save.
              </li>
              <li>
                Custom connectors require a Claude paid plan (Pro / Max
                / Team / Enterprise). Free-tier users should use Claude
                Code or Cursor above.
              </li>
            </ol>
          </div>

          {/* ChatGPT (Developer mode) — UX-5.15.W. Late-2025 ChatGPT
              supports remote HTTP MCP servers via the Developer
              mode beta (Settings → Apps, formerly Connectors).
              Verified against help.openai.com/en/articles/12584461
              and developers.openai.com Developer mode guide. */}
          <div className="rounded-md border bg-muted/30 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-sm font-medium">
                  ChatGPT (Developer mode, beta)
                </div>
                <div className="mt-0.5 text-xs text-muted-foreground">
                  Web only (chatgpt.com). Pro / Plus / Business /
                  Enterprise / Edu — not Free. Enable Developer
                  mode first.
                </div>
              </div>
              {hasRealKey && (
                <CopyButton value={mintedSecret!} label="Copy key" />
              )}
            </div>
            <ol className="mt-3 space-y-1.5 pl-5 text-xs leading-relaxed text-muted-foreground [&>li]:list-decimal">
              <li>
                <strong>Business / Enterprise / Edu only:</strong>{" "}
                a workspace admin must enable it under{" "}
                <strong>
                  Workspace Settings &rarr; Permissions &amp; Roles
                  &rarr; Connected Data &rarr; &quot;Developer mode /
                  Create custom MCP connectors&quot;
                </strong>
                . Pro / Plus self-enable, skip to step 2.
              </li>
              <li>
                In ChatGPT, open <strong>Settings &rarr; Apps</strong>{" "}
                (formerly &quot;Connectors&quot;) &rarr;{" "}
                <strong>Advanced settings</strong> &rarr; toggle{" "}
                <strong>Developer mode</strong> on.
              </li>
              <li>
                Back at Settings → Apps, click{" "}
                <strong>Create app</strong> (only visible with
                Developer mode on).
              </li>
              <li>
                Set <strong>Name</strong> to{" "}
                <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                  {serverName}
                </code>
                , <strong>MCP Server URL</strong> to{" "}
                <code className="break-all rounded bg-muted px-1 py-0.5 text-[11px]">
                  {MCP_URL}
                </code>
                , pick{" "}
                <strong>Authentication: OAuth (Static credentials)</strong>
                , paste your key:{" "}
                <code className="break-all rounded bg-muted px-1 py-0.5 text-[11px]">
                  {hasRealKey ? mintedSecret : PLACEHOLDER}
                </code>
                . Save — lands under <em>Drafts</em>.
              </li>
              <li>
                In a chat: click <strong>+</strong> in the composer
                &rarr; <strong>Developer mode</strong> &rarr; pick
                the app. Mention it by name in your prompts.
              </li>
              <li className="text-amber-700 dark:text-amber-400">
                Caveats: Developer-mode chats only (not standard
                ChatGPT, not mobile, not Deep Research, not voice /
                agent mode). Write tools require per-call
                confirmation. Beta, &quot;elevated risk&quot; per
                OpenAI.
              </li>
            </ol>
          </div>
        </div>

        {hasRealKey && (
          <div className="mt-5 flex items-center justify-between rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs">
            <span>
              The plaintext key is currently inlined in the snippets
              above. Click hide when you&apos;re done pasting.
            </span>
            <button
              type="button"
              onClick={() => setMintedSecret(null)}
              className="rounded-md border bg-background px-2.5 py-1 text-xs font-medium hover:bg-accent"
            >
              Hide key from snippets
            </button>
          </div>
        )}
      </section>

      {/* Sprint UX-5.15.R — D-PROD.26. The system-prompt block is the
          second mandatory half of the MCP setup. MCP alone only fires
          when the LLM decides to call a tool; chat-heavy surfaces
          (Claude Desktop, ChatGPT, Cursor in conversation mode) need
          this nudge to actually instrument every action. Backend
          agents (Diana) who already call `metalins_log_event` from
          deterministic code can skip the snippet, but the framing is
          "required by default, skip only if you orchestrate
          manually". The earlier "(optional)" framing made customers
          do step 1 and walk away with silent agents, which is the
          exact failure mode this block fixes. */}
      <DensePromptSection agentId={agentId} serverName={serverName} />
    </>
  );
}

/**
 * DensePromptSection — UX-5.15.X. Two-variant snippet (persistent
 * system-prompt vs per-conversation primer) shown in the dense /mcp
 * page. Mirrors the wizard's PromptStep so editing one place
 * doesn't drift from the other.
 */
function DensePromptSection({
  agentId,
  serverName,
}: {
  agentId: string;
  serverName: string;
}) {
  const [variant, setVariant] = useState<"persistent" | "primer">(
    "persistent",
  );
  const snippet =
    variant === "persistent"
      ? buildSystemPromptSnippet(agentId, serverName)
      : buildConversationPrimerSnippet(agentId, serverName);

  return (
    <section className="rounded-lg border-2 border-primary/40 bg-card p-6">
      <div className="mb-4 flex items-center gap-2">
        <span className="rounded-md bg-primary/10 px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-primary">
          Required · part 2 of 2
        </span>
      </div>
      <h2 className="text-sm font-semibold tracking-tight text-foreground">
        Paste this into your agent&apos;s instructions
      </h2>
      <p className="mt-2 mb-4 text-sm text-muted-foreground">
        Connecting MCP above is half of the setup. The snippet below
        teaches your LLM to call{" "}
        <code className="rounded bg-muted px-1 py-0.5 text-xs">
          metalins_log_event
        </code>{" "}
        after each meaningful turn. Pick the variant that fits how
        your client handles persistent instructions.
      </p>

      <div className="mb-3 inline-flex rounded-md border bg-muted/50 p-0.5 text-xs">
        <button
          type="button"
          onClick={() => setVariant("persistent")}
          className={`rounded px-3 py-1.5 font-medium transition-colors ${
            variant === "persistent"
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          System prompt
          <span className="ml-1.5 rounded bg-primary/10 px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
            Recommended
          </span>
        </button>
        <button
          type="button"
          onClick={() => setVariant("primer")}
          className={`rounded px-3 py-1.5 font-medium transition-colors ${
            variant === "primer"
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Start of each chat
        </button>
      </div>

      <p className="mb-3 text-xs text-muted-foreground">
        {variant === "persistent" ? (
          <>
            <strong>Recommended.</strong> Goes into the
            persistent-instructions slot your client respects (Claude
            Code <code className="text-[11px]">CLAUDE.md</code>,
            Cursor <code className="text-[11px]">.cursor/rules</code>,
            Claude Desktop preferences / Project instructions,
            ChatGPT Custom Instructions or Project instructions).
          </>
        ) : (
          <>
            <strong>
              Use this if your client has no usable system-prompt
              slot
            </strong>{" "}
            (free ChatGPT, plain Claude.ai chat without a Project).
            Paste this as your first message in <em>each new chat</em>.
          </>
        )}
      </p>

      <ConfigBlock
        title={
          variant === "persistent"
            ? "Persistent instructions"
            : "First message of each chat"
        }
        description={`References agent_id ${agentId} on server ${serverName}.`}
        code={snippet}
        copyLabel="Copy snippet"
        hasRealKey={true}
      />

      <p className="mt-4 text-xs text-muted-foreground">
        Backend agents with deterministic orchestration (Python,
        LangChain, your own loop) can skip this — call{" "}
        <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
          metalins_log_event
        </code>{" "}
        directly from code.
      </p>
    </section>
  );
}

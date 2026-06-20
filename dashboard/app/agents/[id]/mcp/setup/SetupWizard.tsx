/**
 * SetupWizard — UX-5.15.T client wizard for the sequential MCP setup.
 *
 * One Client Component owning all four steps because the minted-key
 * plaintext has to flow from step 1 (mint) into step 2 (client
 * snippets) and step 3 (system-prompt block) without leaking into the
 * URL or being lost on Next-link nav. We persist the secret in
 * sessionStorage scoped by agent id so a reload on step 2 still has
 * the key inlined; the secret is wiped on step 4 success or on the
 * explicit "Hide key" affordance.
 *
 * Step rendering shares the SAME blocks as the dense `/mcp` page:
 *   - KeyManager (from /keys/KeyManager)
 *   - ConfigBlock (from ../ConfigBlock)
 *   - buildClientConfigSnippets / buildSystemPromptSnippet (from
 *     lib/mcp-snippets)
 * Edit those once → both surfaces update.
 *
 * Step 4 (verify) polls /api/agents/[id] every 4s and shows a manual
 * "Refresh now" button (per Jose UX-5.15.T spec — "click refresh when
 * you agent sent an event or you talk with it first time"). On
 * event_count > 0 it flips to a success state with a "View your
 * agent" CTA that goes to /agents/[id]?new=1.
 */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { KeyManager, type CreatedKey } from "../../keys/KeyManager";
import { ConfigBlock } from "../ConfigBlock";
import { CopyButton } from "../CopyButton";
import type { ApiKeySummary } from "@/lib/api";
import {
  MCP_URL,
  PLACEHOLDER,
  mcpServerName,
  buildClientConfigSnippets,
  buildSystemPromptSnippet,
  buildConversationPrimerSnippet,
} from "@/lib/mcp-snippets";

export type SetupStep = "key" | "configure" | "prompt" | "verify";

interface Props {
  agentId: string;
  agentName: string;
  initialKeys: ApiKeySummary[];
  initialEventCount: number;
  step: SetupStep;
  isWizard: boolean;
}

const STEPS: { id: SetupStep; label: string }[] = [
  { id: "key", label: "API key" },
  { id: "configure", label: "Configure client" },
  { id: "prompt", label: "Instructions" },
  { id: "verify", label: "Verify" },
];

function sessionKeyFor(agentId: string): string {
  return `metalins:mcp-setup:secret:${agentId}`;
}

function stepHref(
  agentId: string,
  step: SetupStep,
  isWizard: boolean,
): string {
  const params = new URLSearchParams({ step });
  if (isWizard) params.set("new", "1");
  return `/agents/${encodeURIComponent(agentId)}/mcp/setup?${params.toString()}`;
}

export function SetupWizard({
  agentId,
  agentName,
  initialKeys,
  initialEventCount,
  step,
  isWizard,
}: Props) {
  const router = useRouter();
  const [mintedSecret, setMintedSecret] = useState<string | null>(null);

  // Recover any previously-minted secret from sessionStorage so we
  // can carry it across step navigation. We intentionally do NOT use
  // localStorage — the secret should not survive a tab close.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const stored = window.sessionStorage.getItem(sessionKeyFor(agentId));
      if (stored) setMintedSecret(stored);
    } catch {
      /* sessionStorage may be unavailable in privacy modes */
    }
  }, [agentId]);

  const persistSecret = useCallback(
    (secret: string | null) => {
      setMintedSecret(secret);
      if (typeof window === "undefined") return;
      try {
        const key = sessionKeyFor(agentId);
        if (secret) window.sessionStorage.setItem(key, secret);
        else window.sessionStorage.removeItem(key);
      } catch {
        /* ignore */
      }
    },
    [agentId],
  );

  const serverName = mcpServerName(agentName);
  const keyForSnippets = mintedSecret ?? PLACEHOLDER;
  const hasRealKey = mintedSecret != null;

  const currentIdx = STEPS.findIndex((s) => s.id === step);
  const prevStep = currentIdx > 0 ? STEPS[currentIdx - 1].id : null;
  const nextStep =
    currentIdx >= 0 && currentIdx < STEPS.length - 1
      ? STEPS[currentIdx + 1].id
      : null;

  return (
    <div className="space-y-6">
      <SubStepper currentStep={step} agentId={agentId} isWizard={isWizard} />

      {step === "key" && (
        <KeyStep
          agentId={agentId}
          initialKeys={initialKeys}
          mintedSecret={mintedSecret}
          onKeyMinted={(k) => persistSecret(k.secret)}
          onClearSecret={() => persistSecret(null)}
        />
      )}

      {step === "configure" && (
        <ConfigureStep
          serverName={serverName}
          keyForSnippets={keyForSnippets}
          hasRealKey={hasRealKey}
          mintedSecret={mintedSecret}
        />
      )}

      {step === "prompt" && (
        <PromptStep agentId={agentId} serverName={serverName} />
      )}

      {step === "verify" && (
        <VerifyStep
          agentId={agentId}
          initialEventCount={initialEventCount}
          isWizard={isWizard}
          onSuccess={() => persistSecret(null)}
        />
      )}

      {step !== "verify" && (
        <NavRow
          prevHref={
            prevStep ? stepHref(agentId, prevStep, isWizard) : null
          }
          nextHref={
            nextStep ? stepHref(agentId, nextStep, isWizard) : null
          }
          nextLabel={
            step === "key"
              ? hasRealKey
                ? "Next: configure your client"
                : "Skip key (already have one)"
              : step === "configure"
                ? "Next: system prompt"
                : "Next: verify"
          }
          // Lightweight gate: from step=key, don't push to step 2
          // until they have either minted or skipped via the same
          // button — but we let them skip if they already have a key
          // they want to reuse. No hard block.
          nextDisabled={false}
        />
      )}

      {/* Skip-the-wizard escape hatch — Jose wants the customer to
          be able to bail out if they already know what they're
          doing. */}
      {step !== "verify" && (
        <div className="text-center text-xs text-muted-foreground">
          Want to see everything on one screen?{" "}
          <Link
            href={`/agents/${encodeURIComponent(agentId)}/mcp${isWizard ? "?new=1" : ""}`}
            className="underline"
          >
            Open the full MCP page
          </Link>
          .
        </div>
      )}

      {/* MCP_URL referenced here for the IDE's "go to definition" —
          dead in runtime, alive in static analysis. */}
      <span className="hidden" aria-hidden="true">
        {MCP_URL}
      </span>
    </div>
  );
}

// ---------- Sub-stepper -------------------------------------------------- //

function SubStepper({
  currentStep,
  agentId,
  isWizard,
}: {
  currentStep: SetupStep;
  agentId: string;
  isWizard: boolean;
}) {
  const currentIdx = STEPS.findIndex((s) => s.id === currentStep);
  return (
    <nav
      aria-label="MCP setup progress"
      className="flex flex-wrap items-center gap-2 text-xs"
    >
      {STEPS.map((s, idx) => {
        const isCurrent = idx === currentIdx;
        const isComplete = idx < currentIdx;
        const dotStyle = isCurrent
          ? "bg-foreground text-background"
          : isComplete
            ? "bg-emerald-500/20 text-emerald-700 dark:text-emerald-400"
            : "bg-muted text-muted-foreground";
        const labelStyle = isCurrent
          ? "font-semibold text-foreground"
          : isComplete
            ? "text-muted-foreground"
            : "text-muted-foreground/60";
        const content = (
          <span className="flex items-center gap-2">
            <span
              className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${dotStyle}`}
              aria-current={isCurrent ? "step" : undefined}
            >
              {isComplete ? "✓" : idx + 1}
            </span>
            <span className={labelStyle}>{s.label}</span>
            {idx < STEPS.length - 1 && (
              <span
                className="h-px w-6 bg-muted-foreground/20"
                aria-hidden="true"
              />
            )}
          </span>
        );
        if (isCurrent || idx > currentIdx) {
          return <span key={s.id}>{content}</span>;
        }
        return (
          <Link
            key={s.id}
            href={stepHref(agentId, s.id, isWizard)}
            className="hover:opacity-80"
          >
            {content}
          </Link>
        );
      })}
    </nav>
  );
}

// ---------- Step 1: API key -------------------------------------------- //

function KeyStep({
  agentId,
  initialKeys,
  mintedSecret,
  onKeyMinted,
  onClearSecret,
}: {
  agentId: string;
  initialKeys: ApiKeySummary[];
  mintedSecret: string | null;
  onKeyMinted: (k: CreatedKey) => void;
  onClearSecret: () => void;
}) {
  const activeKeys = initialKeys.filter((k) => !k.revoked_at);
  const hasExistingActiveKey = activeKeys.length > 0;

  return (
    <section className="rounded-lg border bg-card p-6">
      <h2 className="text-base font-semibold tracking-tight">
        Step 1 — Create an MCP key
      </h2>
      <p className="mt-2 mb-4 text-sm text-muted-foreground">
        MCP authenticates with a Bearer token. Keys work across every
        agent in your account — one key lets your client log to all of
        them. We&apos;ll keep the plaintext in memory and inline it
        into the snippets in the next two steps.
      </p>
      {hasExistingActiveKey && !mintedSecret && (
        <div className="mb-4 rounded-md border border-blue-500/40 bg-blue-500/10 p-3 text-xs">
          You already have {activeKeys.length} active key
          {activeKeys.length === 1 ? "" : "s"} in this account. If you
          still have the plaintext somewhere safe, you can skip
          minting a new one and use it in the next step (you&apos;ll
          paste it into the snippets manually). Otherwise mint a new
          one below.
        </div>
      )}
      <KeyManager
        agentId={agentId}
        initialKeys={initialKeys}
        onKeyMinted={onKeyMinted}
      />
      {mintedSecret && (
        <div className="mt-5 flex items-center justify-between rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs">
          <span>
            The plaintext key is held in memory and will be inlined in
            the next steps. Click hide if you want to clear it.
          </span>
          <button
            type="button"
            onClick={onClearSecret}
            className="rounded-md border bg-background px-2.5 py-1 text-xs font-medium hover:bg-accent"
          >
            Hide key
          </button>
        </div>
      )}
    </section>
  );
}

// ---------- Step 2: Configure client ---------------------------------- //

function ConfigureStep({
  serverName,
  keyForSnippets,
  hasRealKey,
  mintedSecret,
}: {
  serverName: string;
  keyForSnippets: string;
  hasRealKey: boolean;
  mintedSecret: string | null;
}) {
  const snippets = buildClientConfigSnippets(keyForSnippets, serverName);

  return (
    <section className="rounded-lg border bg-card p-6">
      <h2 className="text-base font-semibold tracking-tight">
        Step 2 — Configure your MCP client
      </h2>
      <p className="mt-2 mb-4 text-sm text-muted-foreground">
        {hasRealKey ? (
          <>
            Snippets below have your fresh key inlined — pick your
            client, copy, paste. When you&apos;re done, hit{" "}
            <em>Next</em>.
          </>
        ) : (
          <>
            We&apos;ll inline the key into the snippets the moment you
            mint one in step 1. For now they show the placeholder.
          </>
        )}
      </p>

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
        <div className="rounded-md border bg-muted/30 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-sm font-medium">Claude Desktop</div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                Add through the in-app Settings UI — the config file
                route is stdio-only and won&apos;t reach a remote
                HTTP server.
              </div>
            </div>
            {hasRealKey && mintedSecret && (
              <CopyButton value={mintedSecret} label="Copy key" />
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
              </code>{" "}
              with value{" "}
              <code className="break-all rounded bg-muted px-1 py-0.5 text-[11px]">
                Bearer {hasRealKey ? mintedSecret : PLACEHOLDER}
              </code>
              . Save.
            </li>
            <li>
              Custom connectors require a Claude paid plan (Pro /
              Max / Team / Enterprise). Free-tier users should use
              Claude Code or Cursor above.
            </li>
          </ol>
        </div>

        {/* ChatGPT — UX-5.15.W. As of late 2025 ChatGPT supports
            remote HTTP MCP servers via Developer mode (rebranded
            from "Connectors" to "Apps" on 2025-12-17). It's a beta
            flagged "Elevated risk" — show the steps but be honest
            about the caveats. Sourced from
            help.openai.com/en/articles/12584461 and
            developers.openai.com/api/docs/guides/developer-mode. */}
        <div className="rounded-md border bg-muted/30 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-sm font-medium">ChatGPT (Developer mode, beta)</div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                Web only (chatgpt.com). Pro / Plus / Business /
                Enterprise / Edu — not Free. You&apos;ll need to
                enable Developer mode first.
              </div>
            </div>
            {hasRealKey && mintedSecret && (
              <CopyButton value={mintedSecret} label="Copy key" />
            )}
          </div>
          <ol className="mt-3 space-y-1.5 pl-5 text-xs leading-relaxed text-muted-foreground [&>li]:list-decimal">
            <li>
              <strong>Business / Enterprise / Edu only:</strong> a
              workspace admin must first enable it under{" "}
              <strong>
                Workspace Settings &rarr; Permissions &amp; Roles
                &rarr; Connected Data &rarr; &quot;Developer mode /
                Create custom MCP connectors&quot;
              </strong>
              . Pro / Plus users can self-enable, skip to step 2.
            </li>
            <li>
              In ChatGPT, open <strong>Settings &rarr; Apps</strong>{" "}
              (formerly &quot;Connectors&quot;) &rarr;{" "}
              <strong>Advanced settings</strong> &rarr; toggle{" "}
              <strong>Developer mode</strong> on.
            </li>
            <li>
              Back at Settings → Apps, click <strong>Create app</strong>{" "}
              (the button only appears once Developer mode is on).
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
              , pick <strong>Authentication: OAuth (Static credentials)</strong>,
              and paste your key as the static credential:{" "}
              <code className="break-all rounded bg-muted px-1 py-0.5 text-[11px]">
                {hasRealKey ? mintedSecret : PLACEHOLDER}
              </code>
              . Save — the app lands under <em>Drafts</em>.
            </li>
            <li>
              To use it in a chat: click the <strong>+</strong> in
              the composer &rarr; <strong>Developer mode</strong>{" "}
              &rarr; pick the app. You&apos;ll have to mention the
              app by name in your prompts (e.g. &quot;use the{" "}
              {serverName} app to log…&quot;).
            </li>
            <li className="text-amber-700 dark:text-amber-400">
              Caveats: only works in Developer-mode chats (not
              standard ChatGPT chat, not mobile, not Deep Research,
              not voice / agent mode). Write tools require per-call
              confirmation. Marked beta &amp; &quot;elevated risk&quot;
              by OpenAI.
            </li>
          </ol>
        </div>
      </div>
    </section>
  );
}

// ---------- Step 3: System prompt ------------------------------------- //

function PromptStep({
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
      <div className="mb-3 flex items-center gap-2">
        <span className="rounded-md bg-primary/10 px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-primary">
          Required
        </span>
      </div>
      <h2 className="text-base font-semibold tracking-tight">
        Step 3 — Paste this into your agent&apos;s instructions
      </h2>
      <p className="mt-2 mb-4 text-sm text-muted-foreground">
        Without this block your MCP connection only logs events when
        the LLM happens to call a tool. The snippet teaches your LLM
        to call{" "}
        <code className="rounded bg-muted px-1 py-0.5 text-xs">
          metalins_log_event
        </code>{" "}
        after each meaningful turn. Pick the variant that fits how
        your client handles persistent instructions.
      </p>

      {/* Variant tabs — UX-5.15.X. Two flavors of the same snippet:
          short for system-prompt slots that fire every turn, longer
          primer for clients without a usable system-prompt (free
          ChatGPT, plain Claude.ai chat). */}
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
          System prompt (instructions)
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
            ChatGPT Custom Instructions or Project instructions). The
            model sees it on every turn, so it stays short.
          </>
        ) : (
          <>
            <strong>Use this if your client has no usable
            system-prompt slot</strong> (free ChatGPT, plain Claude.ai
            chat without a Project, or you just don&apos;t want to
            commit a <code className="text-[11px]">CLAUDE.md</code>).
            Paste this as your first message in <em>each new chat</em>.
            It&apos;s longer because the model only sees it once per
            conversation — it needs more context to cooperate.
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

      {/* Per-client paste locations — UX-5.15.V. Sourced from each
          vendor's official docs (Anthropic / Cursor / OpenAI) on
          2026-05-19. UX-5.15.X-follow-up: only render under the
          "System prompt" tab — the "Start of each chat" primer is
          self-contained (you paste it as your first message, no
          UI navigation needed). */}
      {variant === "persistent" && (
      <div className="mt-6">
        <h3 className="text-sm font-semibold tracking-tight">
          Where to paste it
        </h3>
        <p className="mt-1 mb-4 text-xs text-muted-foreground">
          Pick the entry that matches the client you set up in step 2.
          Project-scoped is preferred when available (the rule only
          loads when you&apos;re actually working with this agent);
          user-scoped works as a fallback.
        </p>

        <div className="space-y-3">
          {/* Claude Code */}
          <details className="group rounded-md border bg-muted/30 p-4 [&_summary::-webkit-details-marker]:hidden">
            <summary className="flex cursor-pointer items-center justify-between gap-3 text-sm font-medium">
              <span>Claude Code (CLI)</span>
              <span className="text-xs text-muted-foreground group-open:hidden">
                Show steps
              </span>
              <span className="hidden text-xs text-muted-foreground group-open:inline">
                Hide
              </span>
            </summary>
            <div className="mt-3 space-y-2 text-xs leading-relaxed text-muted-foreground">
              <p>
                <strong>Project-scoped (preferred)</strong> — paste at
                the bottom of{" "}
                <code className="rounded bg-muted px-1 py-0.5">
                  CLAUDE.md
                </code>{" "}
                at your repo root. If the file doesn&apos;t exist yet
                run <code className="rounded bg-muted px-1 py-0.5">/init</code>{" "}
                inside Claude Code to scaffold one. Project files
                survive <code className="rounded bg-muted px-1 py-0.5">/compact</code>.
              </p>
              <p>
                <strong>User-scoped</strong> — paste at the bottom of{" "}
                <code className="rounded bg-muted px-1 py-0.5">
                  ~/.claude/CLAUDE.md
                </code>
                . Applies across every Claude Code project on this
                machine.
              </p>
              <p className="text-muted-foreground/70">
                Format: Markdown. Keep each file under ~200 lines for
                best adherence.
              </p>
            </div>
          </details>

          {/* Cursor */}
          <details className="group rounded-md border bg-muted/30 p-4 [&_summary::-webkit-details-marker]:hidden">
            <summary className="flex cursor-pointer items-center justify-between gap-3 text-sm font-medium">
              <span>Cursor</span>
              <span className="text-xs text-muted-foreground group-open:hidden">
                Show steps
              </span>
              <span className="hidden text-xs text-muted-foreground group-open:inline">
                Hide
              </span>
            </summary>
            <div className="mt-3 space-y-2 text-xs leading-relaxed text-muted-foreground">
              <p>
                <strong>Project-scoped (preferred)</strong> — create{" "}
                <code className="rounded bg-muted px-1 py-0.5">
                  .cursor/rules/metalins.mdc
                </code>{" "}
                at your repo root with this frontmatter, then paste
                the snippet below it:
              </p>
              <pre className="overflow-x-auto rounded bg-background p-2 text-[11px] leading-relaxed">
                <code>{`---
description: Metalins identity instrumentation
alwaysApply: true
---

<paste the snippet here>`}</code>
              </pre>
              <p>
                <strong>Global / User</strong> — open Cursor →
                Settings → Rules → <em>User Rules</em>, paste the
                snippet there. Applies across every project.
              </p>
              <p className="text-muted-foreground/70">
                Legacy{" "}
                <code className="rounded bg-muted px-1 py-0.5">
                  .cursorrules
                </code>{" "}
                still works but is deprecated — prefer{" "}
                <code className="rounded bg-muted px-1 py-0.5">
                  .cursor/rules/
                </code>
                .
              </p>
            </div>
          </details>

          {/* Claude Desktop */}
          <details className="group rounded-md border bg-muted/30 p-4 [&_summary::-webkit-details-marker]:hidden">
            <summary className="flex cursor-pointer items-center justify-between gap-3 text-sm font-medium">
              <span>Claude Desktop</span>
              <span className="text-xs text-muted-foreground group-open:hidden">
                Show steps
              </span>
              <span className="hidden text-xs text-muted-foreground group-open:inline">
                Hide
              </span>
            </summary>
            <div className="mt-3 space-y-2 text-xs leading-relaxed text-muted-foreground">
              <p>
                <strong>Per-project (preferred, paid plans only)</strong> —
                open a Project →{" "}
                <em>Instructions</em> field on the right rail → paste
                the snippet. Project instructions only apply when
                chatting inside that project.
              </p>
              <p>
                <strong>Account-wide</strong> — Settings → Profile →
                &quot;What personal preferences should Claude consider
                in responses?&quot; — paste at the bottom. Applies to
                every chat on this account.
              </p>
              <p className="text-muted-foreground/70">
                Format: plain text prose. Custom &quot;Styles&quot;
                are separate (formatting) — keep this snippet in the
                preferences/instructions field.
              </p>
            </div>
          </details>

          {/* ChatGPT */}
          <details className="group rounded-md border bg-muted/30 p-4 [&_summary::-webkit-details-marker]:hidden">
            <summary className="flex cursor-pointer items-center justify-between gap-3 text-sm font-medium">
              <span>ChatGPT</span>
              <span className="text-xs text-muted-foreground group-open:hidden">
                Show steps
              </span>
              <span className="hidden text-xs text-muted-foreground group-open:inline">
                Hide
              </span>
            </summary>
            <div className="mt-3 space-y-2 text-xs leading-relaxed text-muted-foreground">
              <p>
                <strong>Per-project (preferred)</strong> — open the
                Project → three-dot menu (top right) → Project
                settings → <em>Instructions</em> → paste the snippet.
              </p>
              <p>
                <strong>Account-wide</strong> — Settings →
                Personalization → Custom Instructions → toggle
                &quot;Enable customization&quot; on → paste in the{" "}
                <em>How ChatGPT should respond</em> field.
              </p>
              <p className="text-muted-foreground/70">
                Only the Developer-mode chat surface speaks MCP. If
                you set up ChatGPT in step 2, the instructions
                live here and apply to your account&apos;s
                Developer-mode chats.
              </p>
            </div>
          </details>
        </div>
      </div>
      )}

      <p className="mt-5 text-xs text-muted-foreground">
        If your agent runs in backend code (LangChain, your own loop)
        you can skip this — call{" "}
        <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
          metalins_log_event
        </code>{" "}
        directly from your orchestration code instead.
      </p>
    </section>
  );
}

// ---------- Step 4: Verify ------------------------------------------- //

const POLL_INTERVAL_MS = 4_000;
const GIVE_UP_MS = 10 * 60_000;

function VerifyStep({
  agentId,
  initialEventCount,
  isWizard,
  onSuccess,
}: {
  agentId: string;
  initialEventCount: number;
  isWizard: boolean;
  onSuccess: () => void;
}) {
  const router = useRouter();
  const [eventCount, setEventCount] = useState(initialEventCount);
  const [isChecking, setIsChecking] = useState(false);
  const [lastCheckedAt, setLastCheckedAt] = useState<number | null>(null);
  const [startedAt] = useState(() => Date.now());
  const [givenUp, setGivenUp] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const checkNow = useCallback(async () => {
    setIsChecking(true);
    try {
      const res = await fetch(
        `/api/agents/${encodeURIComponent(agentId)}`,
        { cache: "no-store" },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = (await res.json()) as { event_count?: number };
      const n = typeof body.event_count === "number" ? body.event_count : 0;
      setEventCount(n);
      setLastCheckedAt(Date.now());
    } catch {
      /* transient — next tick / next click will retry */
    } finally {
      setIsChecking(false);
    }
  }, [agentId]);

  // Background polling
  useEffect(() => {
    if (eventCount > 0) return;
    let cancelled = false;

    function schedule() {
      timerRef.current = setTimeout(async () => {
        if (cancelled) return;
        if (Date.now() - startedAt > GIVE_UP_MS) {
          setGivenUp(true);
          return;
        }
        await checkNow();
        if (!cancelled) schedule();
      }, POLL_INTERVAL_MS);
    }

    schedule();
    return () => {
      cancelled = true;
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    };
  }, [eventCount, startedAt, checkNow]);

  if (eventCount > 0) {
    // First event arrived — celebrate, wipe the in-memory key, send
    // them to the detail page.
    return (
      <section
        className="rounded-lg border border-emerald-500/40 bg-emerald-500/[0.06] p-6"
        aria-live="polite"
      >
        <div className="flex items-start gap-4">
          <div
            className="mt-1 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
            aria-hidden="true"
          >
            <CheckCircle2 size={22} />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-xl font-semibold tracking-tight">
              Your agent is set up correctly.
            </h2>
            <p className="mt-1.5 text-sm text-muted-foreground">
              We received your first event. From here on every action
              your agent takes will be identity-tracked.
            </p>
            <div className="mt-4">
              <button
                type="button"
                onClick={() => {
                  onSuccess();
                  router.push(
                    `/agents/${encodeURIComponent(agentId)}${isWizard ? "?new=1" : ""}`,
                  );
                }}
                className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-emerald-700"
              >
                View your agent
                <ArrowRight size={14} />
              </button>
            </div>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-lg border bg-card p-6" aria-live="polite">
      <div className="flex items-start gap-4">
        <div
          className="mt-1 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground"
          aria-hidden="true"
        >
          <Loader2 size={22} className={givenUp ? "" : "animate-spin"} />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-xl font-semibold tracking-tight">
            {givenUp
              ? "Still waiting on first activity."
              : "Step 4 — Waiting for first event…"}
          </h2>
          <p className="mt-1.5 text-sm text-muted-foreground">
            {givenUp ? (
              <>
                We haven&apos;t seen any events from this agent yet.
                Double-check that your client is configured (step 2)
                and that the system prompt block is in place (step 3),
                then send a message / action from your agent and click
                refresh below.
              </>
            ) : (
              <>
                Talk to your agent for the first time. The moment it
                calls{" "}
                <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                  metalins_log_event
                </code>{" "}
                we&apos;ll detect it. We&apos;re polling automatically
                every {POLL_INTERVAL_MS / 1000}s, but you can also hit
                refresh.
              </>
            )}
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={checkNow}
              disabled={isChecking}
              className="inline-flex items-center gap-2 rounded-md border bg-background px-3 py-1.5 text-sm font-medium hover:bg-accent disabled:opacity-50"
            >
              <RefreshCw
                size={14}
                className={isChecking ? "animate-spin" : ""}
              />
              {isChecking ? "Checking…" : "Refresh now"}
            </button>
            {lastCheckedAt && (
              <span className="text-xs text-muted-foreground">
                Last checked{" "}
                {Math.max(
                  0,
                  Math.round((Date.now() - lastCheckedAt) / 1000),
                )}
                s ago
              </span>
            )}
          </div>
          <div className="mt-5 text-xs text-muted-foreground">
            Wired everything up but stuck? Go back to{" "}
            <Link
              href={stepHref(agentId, "configure", isWizard)}
              className="underline"
            >
              step 2 (client config)
            </Link>{" "}
            or{" "}
            <Link
              href={stepHref(agentId, "prompt", isWizard)}
              className="underline"
            >
              step 3 (system prompt)
            </Link>
            .
          </div>
        </div>
      </div>
    </section>
  );
}

// ---------- Nav row --------------------------------------------------- //

function NavRow({
  prevHref,
  nextHref,
  nextLabel,
  nextDisabled,
}: {
  prevHref: string | null;
  nextHref: string | null;
  nextLabel: string;
  nextDisabled: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      {prevHref ? (
        <Link
          href={prevHref}
          className="inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-1.5 text-sm font-medium hover:bg-accent"
        >
          <ArrowLeft size={14} />
          Back
        </Link>
      ) : (
        <span />
      )}
      {nextHref ? (
        <Link
          href={nextDisabled ? "#" : nextHref}
          aria-disabled={nextDisabled}
          className={`inline-flex items-center gap-1.5 rounded-md px-3.5 py-1.5 text-sm font-medium ${
            nextDisabled
              ? "bg-muted text-muted-foreground pointer-events-none"
              : "bg-foreground text-background hover:bg-foreground/90"
          }`}
        >
          {nextLabel}
          <ArrowRight size={14} />
        </Link>
      ) : (
        <span />
      )}
    </div>
  );
}

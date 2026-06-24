/**
 * /agents/[id]/connect — UX-5.15.S surface picker.
 *
 * Sprint UX-5.15.S (2026-05-19). Jose feedback after the post-create
 * walkthrough: landing on /agents/[id] right after creation is
 * confusing — Andrea/Carlos/Diana don't know what to do next and the
 * agent detail panel is showing "no events" empty state while the
 * customer is still trying to figure out *how* to connect anything.
 *
 * New flow:
 *   /agents/new  → register agent
 *                → /agents/[id]/connect?new=1   (this page, surface picker)
 *                → /agents/[id]/mcp?new=1       (MCP sub-wizard)
 *                  or /agents/[id]/watchers?new=1  (Bot sub-wizard)
 *                  or stay here with "coming soon" for SDK
 *                → /agents/[id]?new=1           (verify / detail)
 *
 * The three cards, in grid order (UX-5.17 API-first):
 *
 *   • HTTP API / SDK — the recommended path, leading the grid. The
 *     developer HTTP API is the primary, language-agnostic product
 *     surface; an SDK wraps it for convenience (Python today, more
 *     languages later). Routes to a real setup page (mint key +
 *     curl/SDK snippet).
 *
 *   • MCP — for assistants inside a chat or editor client. Routes to
 *     /mcp/setup.
 *
 *   • BOT (Watcher) — the zero-code on-ramp for creators with a
 *     public bot; sits last. Routes to /watchers/setup.
 *
 * Each card lists its limitations honestly so the customer
 * self-selects the right path instead of bouncing later.
 */
import Link from "next/link";
import { notFound } from "next/navigation";
import { Terminal, Bot, Code2, ArrowRight } from "lucide-react";
import { ApiError, getAgent } from "@/lib/api";
import { WizardProgress } from "@/components/WizardProgress";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Pick how this agent connects",
};

/**
 * Issue #38 — Diana-first connect flow.
 *
 * When false: only the HTTP API / SDK card is shown. The path is
 * direct — register → SDK setup. MCP and Bot Watcher code stays
 * intact (OCULTAR, NO BORRAR) so restoring them is a one-line change.
 *
 * When true: the full 3-column picker (HTTP API / SDK + MCP + Bot
 * Watcher) is restored.
 */
const SHOW_ALTERNATIVE_PATHS = false;

interface PageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ new?: string }>;
}

interface OptionProps {
  href: string;
  icon: React.ReactNode;
  title: string;
  blurb: string;
  bestFor: string;
  limitations: string[];
  cta: string;
  recommended?: boolean;
  /**
   * Preview badge — for paths that work but route to documentation
   * because the dedicated SDK wrapper is still in development. We
   * keep these clickable (Jose's UX-5.15.AA feedback) rather than
   * disabled, since the underlying integration via MCP REST is
   * fully usable today; the SDK card just leads to the docs that
   * explain that route.
   */
  preview?: boolean;
}

function ConnectOption({
  href,
  icon,
  title,
  blurb,
  bestFor,
  limitations,
  cta,
  recommended,
  preview,
}: OptionProps) {
  const baseClasses =
    "group flex h-full flex-col rounded-lg border bg-card p-5 transition-shadow hover:shadow-md hover:border-foreground/30";
  const borderClasses = recommended
    ? "border-primary/40 ring-1 ring-primary/20"
    : "border-foreground/10";

  return (
    <Link href={href} className={`${baseClasses} ${borderClasses}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-foreground/70">{icon}</span>
          <h3 className="text-base font-semibold tracking-tight">{title}</h3>
        </div>
        <div className="flex flex-col items-end gap-1">
          {recommended && (
            <span className="rounded-md bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
              Recommended
            </span>
          )}
          {preview && (
            <span className="rounded-md bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
              Preview
            </span>
          )}
        </div>
      </div>
      <p className="mt-3 text-sm text-muted-foreground">{blurb}</p>
      <div className="mt-4 text-xs">
        <div className="font-medium text-foreground/80">Best for</div>
        <p className="mt-0.5 text-muted-foreground">{bestFor}</p>
      </div>
      <div className="mt-4 text-xs">
        <div className="font-medium text-foreground/80">Limitations</div>
        <ul className="mt-1 space-y-1 text-muted-foreground">
          {limitations.map((l, i) => (
            <li key={i} className="flex gap-1.5">
              <span aria-hidden="true">•</span>
              <span>{l}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="mt-auto pt-5">
        <span className="inline-flex items-center gap-1.5 rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background group-hover:bg-foreground/90">
          {cta}
          <ArrowRight
            size={14}
            className="transition-transform group-hover:translate-x-0.5"
          />
        </span>
      </div>
    </Link>
  );
}

/**
 * UX-5.15.AD: the picker no longer reads `use_case` (that whole
 * concept was retired).
 *
 * UX-5.17 (API-first): the HTTP API / SDK is the recommended path and
 * leads the grid — it is the primary product surface, the SDK does the
 * full verification round-trip, and the API is the contract every
 * other path wraps. MCP is the option for assistants inside a chat or
 * editor client; the public-bot watcher is the zero-code on-ramp for
 * creators and sits last.
 */

export default async function ConnectPickerPage({
  params,
  searchParams,
}: PageProps) {
  const [{ id }, sp] = await Promise.all([params, searchParams]);
  const agentId = decodeURIComponent(id);
  const isWizard = sp.new === "1";

  let agentName = agentId;
  try {
    const agent = await getAgent(agentId);
    agentName = agent.name;
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
  }

  const wizardSuffix = isWizard ? "?new=1" : "";

  return (
    <main className="space-y-8">
      {isWizard && (
        <div className="pt-2">
          <WizardProgress currentStep={2} />
        </div>
      )}

      <div>
        <Link
          href={`/agents/${encodeURIComponent(agentId)}`}
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← Skip and go to the agent
        </Link>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">
          How will <span className="text-primary">{agentName}</span> talk to
          Drift Engine?
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          Identity tracking starts when this agent sends events to Drift Engine.
          Pick the path that matches how your agent is used. You can change
          this later from the agent settings.
        </p>
      </div>

      {/* Issue #38 — SHOW_ALTERNATIVE_PATHS=false: SDK-only grid.
          MCP and Bot Watcher cards kept below for easy restoration. */}
      <div className={`grid gap-4 ${SHOW_ALTERNATIVE_PATHS ? "md:grid-cols-3" : "max-w-xl"}`}>
        <ConnectOption
          // UX-5.17 — API-first: the HTTP API is the primary surface,
          // language-agnostic, and the recommended path (leads the
          // grid). An SDK wraps the same endpoints for convenience;
          // Python ships today, more languages later — so the card
          // pitches the API and keeps the SDK generic, never
          // "Python-first".
          href={`/agents/${encodeURIComponent(agentId)}/api/setup${wizardSuffix}`}
          icon={<Code2 size={20} />}
          title="HTTP API / SDK"
          blurb="Call the HTTP API from your agent's code in any language — it handles verification end to end. Prefer a ready-made wrapper? An SDK does the same in a few lines: one block at startup, one call per turn."
          bestFor="Backend agents in production with their own orchestration code — services you own end-to-end, not running inside a chat client."
          limitations={[
            "You add the integration to your code: one block at startup, one call per interaction.",
            "Raw prompt/response text stays on your side — events carry sha256 hashes plus low-resolution structural signals (lengths, format flags, tool names), never the content. Opt out with compute_behavioral=False.",
            "The background check loop needs a long-running process; a short-lived script reports events but answers fewer checks.",
          ]}
          cta="Set up the SDK"
          recommended
        />
        {/* Issue #38 — Hidden until SHOW_ALTERNATIVE_PATHS is re-enabled.
            MCP and Bot Watcher paths stay here intact (OCULTAR, NO BORRAR). */}
        {SHOW_ALTERNATIVE_PATHS && (
          <>
            <ConnectOption
              href={`/agents/${encodeURIComponent(agentId)}/mcp/setup${wizardSuffix}`}
              icon={<Terminal size={20} />}
              title="MCP server"
              blurb="Connect Drift Engine as an MCP server in Claude Desktop, Claude Code, Cursor, or any client that speaks the protocol. Your client logs events as it calls tools."
              bestFor="Power users of a chat or editor surface (Claude Desktop, ChatGPT, Cursor, Claude Code) who want their assistant identity-tracked."
              limitations={[
                "Events fire only when the LLM decides to call a tool. Chat-only surfaces need a system-prompt block (we'll give you one) for continuous coverage.",
                "Coverage depends on the LLM following instructions — most modern models comply but it's not a guarantee.",
                "Setup requires editing your client's MCP config file.",
              ]}
              cta="Set up MCP"
            />
            <ConnectOption
              // UX-5.15.AA — route the bot card to the dedicated wizard
              // page at `/watchers/setup`, parallel to `/mcp/setup`. The
              // dense `/watchers` page stays untouched for managing an
              // already-connected bot from the agent detail.
              href={`/agents/${encodeURIComponent(agentId)}/watchers/setup`}
              icon={<Bot size={20} />}
              title="Public bot watcher"
              blurb="Connect a public Telegram bot (Discord/Slack/X next). We poll its messages, hash them locally, identity-track without any code on your side."
              bestFor="Creators with a customer-facing bot who want a public verification badge for their followers."
              limitations={[
                "Only one public-bot platform per agent.",
                "Telegram supported today; Discord/Slack/X are on the roadmap.",
                "We only see hashes — never message contents.",
              ]}
              cta="Connect a bot"
            />
          </>
        )}
      </div>

      {SHOW_ALTERNATIVE_PATHS ? (
        <div className="rounded-md border bg-muted/30 p-4 text-xs text-muted-foreground">
          Not sure which to pick? Backend production services use the{" "}
          <strong>HTTP API / SDK</strong> (see{" "}
          <Link href="/drift-engine/docs/reference/developer-api" className="underline">
            the API reference
          </Link>
          ). Assistants inside a chat or editor client go with{" "}
          <strong>MCP</strong>. Public bots go with the{" "}
          <strong>watcher</strong>.
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          See the full{" "}
          <Link href="/drift-engine/docs/reference/developer-api" className="underline hover:text-foreground">
            API reference
          </Link>{" "}
          for curl examples, advanced options, and other language clients.
        </p>
      )}
    </main>
  );
}

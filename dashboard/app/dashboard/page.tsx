/**
 * Dashboard — list of agents on this customer's account.
 *
 * Sprint UX-5.5b (2026-05-16): redesigned to match
 * docs/product/PRODUCT-EXPERIENCE-V2.md §5.
 *
 *   • Hero "fleet state" up top: one of {empty, calma, atención, acción}.
 *     In calma (default, ~95% of visits) it says "All your agents are
 *     healthy" and dominates the fold — the user knows in 1 second
 *     nothing needs attention.
 *   • Agent rows drop the raw confidence percentage from calma. Status
 *     becomes a colored dot + "Active" / "Needs attention" / "Inactive"
 *     verdict — never a number. The number was a leaked-engineer artifact.
 *     (D-PROD.18 customer copy rules apply.)
 *   • Quick help section at the bottom for low-tech users (Andrea / Carlos).
 *
 * Server Component. Calls GET /v1/agents using the Supabase session JWT.
 */
import Link from "next/link";
import {
  Bot,
  Terminal,
  CircleDashed,
  ChevronRight,
  ShieldCheck,
  Plus,
  Plug,
  BookOpen,
} from "lucide-react";
import { listAgents, listCustomerKeys, ApiError, type AgentSummary } from "@/lib/api";
import { TrustStrip } from "@/components/agents";
import { timeAgo } from "@/lib/utils";
import { ApiKeyOnboarding } from "./ApiKeyOnboarding";

export const dynamic = "force-dynamic";

// Private route — never index even when ALLOW_INDEX=true.
export const metadata = {
  title: "Your agents",
  robots: { index: false, follow: false, nocache: true },
};

// --------------------------------------------------------------------------- //
// Fleet state (Calma / Atención / Acción)                                     //
// --------------------------------------------------------------------------- //

type AgentLevel = 0 | 1 | 2; // 0 = healthy, 1 = attention, 2 = action

/**
 * Map a single agent to a level for the fleet hero.
 *
 * Sprint UX-5.12 — driven by the cryptographic layer of the trust
 * block + watcher state. Behavioral layer (drift) is intentionally
 * a separate signal that doesn't escalate the headline by itself;
 * the agent detail page surfaces drift inline. Rules:
 *
 *   level 2 (action) — agent revoked OR crypto state = action_required.
 *   level 1 (attention) — crypto state = caution OR watcher errored.
 *   level 0 (healthy)  — everything else. Empty / building agents stay
 *                        at 0 so a fresh agent isn't shouted at.
 */

function agentLevel(a: AgentSummary): AgentLevel {
  if (!a.is_active) return 2;
  const crypto = a.trust?.cryptographic.state;
  if (crypto === "action_required" || crypto === "revoked") return 2;
  if (crypto === "caution") return 1;
  if (a.watcher_state === "error") return 1;
  return 0;
}

interface FleetCounts {
  total: number;
  active: number;
  empty: number;      // active + 0 events
  baselining: number; // active + behavioral = not_enough_data
  healthy: number;    // active + behavioral ∈ {building, stable}
  inactive: number;   // !is_active
  watcherError: number;
}

function tallyFleet(agents: AgentSummary[]): FleetCounts {
  const c: FleetCounts = {
    total: agents.length,
    active: 0,
    empty: 0,
    baselining: 0,
    healthy: 0,
    inactive: 0,
    watcherError: 0,
  };
  for (const a of agents) {
    if (!a.is_active) {
      c.inactive += 1;
      continue;
    }
    c.active += 1;
    if (a.watcher_state === "error") c.watcherError += 1;
    if (a.event_count === 0) {
      c.empty += 1;
      continue;
    }
    const behavioral = a.trust?.behavioral.state;
    if (behavioral === "not_enough_data") c.baselining += 1;
    else c.healthy += 1;
  }
  return c;
}

type FleetState =
  | { kind: "empty" }
  | {
      kind: "calma";
      counts: FleetCounts;
      lastChecked: string | null;
    }
  | {
      kind: "atencion";
      troubled: AgentSummary;
      counts: FleetCounts;
    }
  | {
      kind: "accion";
      troubled: AgentSummary;
      counts: FleetCounts;
    };

function computeFleetState(agents: AgentSummary[]): FleetState {
  if (agents.length === 0) return { kind: "empty" };

  const counts = tallyFleet(agents);
  let worst: { agent: AgentSummary; level: AgentLevel } | null = null;
  let mostRecent: string | null = null;

  for (const a of agents) {
    const level = agentLevel(a);
    if (worst === null || level > worst.level) worst = { agent: a, level };
    if (a.last_event_at) {
      if (
        mostRecent === null ||
        new Date(a.last_event_at).getTime() > new Date(mostRecent).getTime()
      ) {
        mostRecent = a.last_event_at;
      }
    }
  }

  if (worst === null || worst.level === 0) {
    return { kind: "calma", counts, lastChecked: mostRecent };
  }
  if (worst.level === 1) {
    return { kind: "atencion", troubled: worst.agent, counts };
  }
  return { kind: "accion", troubled: worst.agent, counts };
}

/**
 * Compose an honest one-line summary for the calma hero.
 *
 * Pre-UX-5.9-C the banner just said "All your agents are healthy" even
 * when most agents were empty/baselining. The new copy admits:
 *
 *   "5 agents · 1 healthy · 3 setting up · 1 inactive"
 *
 * When everything is genuinely healthy we still get the strong
 * single-sentence reassurance — but only then.
 */
function calmaHeadline(counts: FleetCounts): {
  title: string;
  detail: string;
} {
  const { active, empty, baselining, healthy, inactive, total } = counts;
  if (active === 0 && inactive === 0 && total > 0) {
    return {
      title: "Nothing to verify yet.",
      detail: "Pick an integration to start tracking your first agent.",
    };
  }
  if (active === 0 && inactive > 0) {
    return {
      title: "No active agents right now.",
      detail: `${inactive} inactive agent${inactive === 1 ? "" : "s"}. Connect a new one or reconnect an existing one.`,
    };
  }
  if (active > 0 && empty === active) {
    return {
      title: "Waiting for first activity.",
      detail: `${active} agent${active === 1 ? "" : "s"} connected, none have logged events yet. Send a test event from one of them.`,
    };
  }
  if (active > 0 && healthy === active) {
    return {
      title: "All your agents are healthy.",
      detail: `${active} agent${active === 1 ? "" : "s"} active`,
    };
  }
  // Mixed: report each bucket honestly.
  const parts: string[] = [];
  if (healthy > 0) parts.push(`${healthy} healthy`);
  if (baselining > 0) parts.push(`${baselining} setting up`);
  if (empty > 0) parts.push(`${empty} waiting for activity`);
  if (inactive > 0) parts.push(`${inactive} inactive`);
  return {
    title: "Your fleet is steady.",
    detail: `${active} active · ` + parts.join(" · "),
  };
}

// --------------------------------------------------------------------------- //
// Hero card                                                                   //
// --------------------------------------------------------------------------- //

function FleetHero({ state }: { state: FleetState }) {
  if (state.kind === "empty") {
    return (
      <section className="rounded-2xl border-2 border-dashed bg-card p-10 text-center">
        <ShieldCheck
          size={48}
          className="mx-auto mb-4 text-muted-foreground"
          aria-hidden="true"
        />
        <h2 className="text-2xl font-semibold tracking-tight">
          Let&apos;s protect your first agent.
        </h2>
        <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
          Five minutes. Connect your agent with 3 lines of Python &mdash;
          via the HTTP API or SDK.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <Link
            href="/agents/new"
            className="rounded-md bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Connect an agent
          </Link>
          <Link
            href="/drift-engine/docs"
            className="rounded-md border px-5 py-2.5 text-sm font-medium hover:bg-accent"
          >
            How it works
          </Link>
        </div>
      </section>
    );
  }

  if (state.kind === "calma") {
    const headline = calmaHeadline(state.counts);
    // Only paint the celebratory green when everything is genuinely
    // healthy. Mixed fleets get a neutral card so the user doesn't read
    // the green as "everything's fine" when in fact most agents haven't
    // baselined yet.
    const allHealthy =
      state.counts.active > 0 &&
      state.counts.healthy === state.counts.active;
    return (
      <section
        className={
          "rounded-2xl border p-8 md:p-10 " +
          (allHealthy
            ? "border-emerald-500/30 bg-emerald-500/[0.04]"
            : "border bg-card")
        }
        aria-live="polite"
      >
        <div className="flex items-start gap-4">
          <div
            className={
              "mt-1 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full " +
              (allHealthy
                ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                : "bg-muted text-muted-foreground")
            }
          >
            <ShieldCheck size={22} aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">
              {headline.title}
            </h2>
            <p className="mt-1.5 text-sm text-muted-foreground">
              {headline.detail}
              {state.lastChecked
                ? ` · last activity ${timeAgo(state.lastChecked)}`
                : ""}
              {" · "}auto-refreshes
            </p>
          </div>
        </div>
      </section>
    );
  }

  if (state.kind === "atencion") {
    const enc = encodeURIComponent(state.troubled.agent_id);
    // The level-1 banner has two distinct causes (see agentLevel): a
    // cryptographic `caution`, or a watcher stuck in `error`. A
    // connection error is a setup problem, not a trust signal — saying
    // "something shifted in trust signals" for a 0-event bot with a bad
    // token is just wrong, so the copy branches. When both are true the
    // crypto caution wins: the real trust event is the more important
    // message (Jose, 2026-05-21).
    const cryptoCaution =
      state.troubled.trust?.cryptographic.state === "caution";
    const connIssue =
      !cryptoCaution && state.troubled.watcher_state === "error";
    return (
      <section
        className="rounded-2xl border border-amber-500/40 bg-amber-500/[0.06] p-6 md:p-8"
        aria-live="polite"
      >
        <div className="flex items-start gap-4">
          <div
            className="mt-1 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-amber-500/20 text-amber-700 dark:text-amber-300"
            aria-hidden="true"
          >
            ⚠
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-xl font-semibold tracking-tight md:text-2xl">
              One agent needs your attention.
            </h2>
            <p className="mt-1.5 text-sm text-muted-foreground">
              <span className="font-medium text-foreground">
                {state.troubled.name}
              </span>{" "}
              {connIssue
                ? "— Drift Engine can't connect to this agent's bot. Check the bot setup so verification can start."
                : "— something shifted in this agent's trust signals. Open it to see what changed."}
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Link
                href={`/agents/${enc}`}
                className="rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background hover:bg-foreground/90"
              >
                {connIssue ? "Check the connection" : "Investigate"}
              </Link>
              <Link
                href={`/agents/${enc}`}
                className="rounded-md border px-4 py-2 text-sm font-medium hover:bg-accent"
              >
                See details
              </Link>
            </div>
          </div>
        </div>
      </section>
    );
  }

  // accion
  const enc = encodeURIComponent(state.troubled.agent_id);
  return (
    <section
      className="rounded-2xl border border-destructive/40 bg-destructive/[0.06] p-6 md:p-8"
      aria-live="assertive"
    >
      <div className="flex items-start gap-4">
        <div
          className="mt-1 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-destructive/20 text-destructive"
          aria-hidden="true"
        >
          🛑
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-xl font-semibold tracking-tight md:text-2xl">
            Unusual activity detected.
          </h2>
          <p className="mt-1.5 text-sm text-muted-foreground">
            <span className="font-medium text-foreground">
              {state.troubled.name}
            </span>{" "}
            — its identity signals look very different from before. This
            usually means a compromise or a major change in how it&apos;s
            running.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link
              href={`/agents/${enc}`}
              className="rounded-md bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground hover:bg-destructive/90"
            >
              Review now
            </Link>
            <Link
              href={`/agents/${enc}`}
              className="rounded-md border px-4 py-2 text-sm font-medium hover:bg-accent"
            >
              I&apos;ll handle this later
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Agent row — minimal, verdict-driven                                         //
// --------------------------------------------------------------------------- //

function surfaceIcon(s: AgentSummary["integration_surface"]) {
  if (s === "watcher") return Bot;
  if (s === "mcp") return Terminal;
  if (s === "sdk") return Terminal;
  return CircleDashed;
}

function surfaceLabel(s: AgentSummary["integration_surface"]) {
  if (s === "watcher") return "Bot";
  if (s === "mcp") return "MCP";
  if (s === "sdk") return "SDK";
  return "Pending";
}

function statusFor(a: AgentSummary): {
  label: string;
  dot: string;
} {
  if (!a.is_active) return { label: "Inactive", dot: "bg-muted-foreground/50" };
  // Sprint UX-5.9-D — watcher adapter failing trumps the activity-based
  // verdict. We surface it inline so the user doesn't have to drill into
  // the watcher page to discover the bot is offline.
  if (a.watcher_state === "error")
    return { label: "Connection issue", dot: "bg-amber-500" };
  if (a.watcher_state === "paused")
    return { label: "Paused", dot: "bg-muted-foreground/60" };
  const lvl = agentLevel(a);
  if (lvl === 2)
    return { label: "Needs review", dot: "bg-destructive" };
  if (lvl === 1)
    return { label: "Needs attention", dot: "bg-amber-500" };
  // Sprint UX-5.12 — distinguish activity buckets via the behavioral
  // layer's state instead of a hard-coded event count threshold.
  if (a.event_count === 0) return { label: "Awaiting first event", dot: "bg-sky-500" };
  if (a.trust?.behavioral.state === "not_enough_data")
    return { label: "Setting up", dot: "bg-sky-500" };
  if (a.trust?.behavioral.state === "drift_detected")
    return { label: "Drift detected", dot: "bg-amber-500" };
  return { label: "Healthy", dot: "bg-emerald-500" };
}

/**
 * Sprint UX-5.15.C2 — compact protections badge for the dashboard list.
 * Shows "X active · Y available · Z total" so a glance tells you which
 * agents already have a full catalog and which are still building up.
 */
function ProtectionsBadge({
  summary,
}: {
  summary: NonNullable<AgentSummary["protections_summary"]>;
}) {
  const { active_count, applicable_count, total_count } = summary;
  // Color: emerald if all applicable active, amber if some pending, sky if early.
  const dot =
    active_count === applicable_count && applicable_count > 0
      ? "bg-emerald-500"
      : active_count > 0
        ? "bg-amber-500"
        : "bg-sky-500";
  return (
    <div className="mt-1.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden />
      <span>
        <span className="font-medium text-foreground/80">{active_count}</span>
        <span className="opacity-60"> / {applicable_count} protections</span>
        {applicable_count < total_count && (
          // Sprint UX-5.15.M (Andrea fix F6): "N need setup" sounded
          // alarming for a brand-new agent — read as "you forgot to
          // do 16 things". The honest framing is that those rows
          // unlock automatically as the agent accumulates history.
          <span className="opacity-50"> · {total_count - applicable_count} unlock as it runs</span>
        )}
      </span>
    </div>
  );
}

function AgentRow({ agent }: { agent: AgentSummary }) {
  const enc = encodeURIComponent(agent.agent_id);
  const Icon = surfaceIcon(agent.integration_surface);
  const surface = surfaceLabel(agent.integration_surface);
  const status = statusFor(agent);
  const eventStr =
    agent.event_count === 1
      ? "1 event"
      : `${agent.event_count.toLocaleString()} events`;

  return (
    <Link
      href={`/agents/${enc}`}
      className="group flex items-center gap-3 rounded-lg border bg-card p-4 transition-colors hover:border-foreground/40 hover:bg-accent/40"
    >
      <div className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
        <Icon size={18} aria-hidden="true" />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate font-medium group-hover:underline underline-offset-2">
            {agent.name}
          </span>
          <span className="shrink-0 rounded-full border bg-background/50 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            {surface}
          </span>
        </div>
        <div className="mt-0.5 truncate text-xs text-muted-foreground">
          {eventStr} · last activity {timeAgo(agent.last_event_at)}
        </div>
        {agent.is_active && agent.trust && (
          <TrustStrip trust={agent.trust} className="mt-1.5" />
        )}
        {agent.is_active && agent.protections_summary && (
          <ProtectionsBadge summary={agent.protections_summary} />
        )}
      </div>

      <div className="flex items-center gap-2 shrink-0">
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span
            className={`h-2 w-2 rounded-full ${status.dot}`}
            aria-hidden="true"
          />
          <span className="hidden sm:inline">{status.label}</span>
        </span>
        <ChevronRight
          size={16}
          className="text-muted-foreground/60 group-hover:text-foreground"
          aria-hidden="true"
        />
      </div>
    </Link>
  );
}

// --------------------------------------------------------------------------- //
// Quick help                                                                  //
// --------------------------------------------------------------------------- //
//
// UX-5.15.AB (2026-05-19): grid of help cards that fills the dashboard
// width. UX-5.15.AC follow-up: dropped the "Email & webhook alerts —
// Shipping next sprint" card. Alerts already live per-agent under
// /agents/[id]/alerts; teasing them as a "coming soon" feature on the
// dashboard was misleading and ate a third of the row. Two cards now
// span the full width with `sm:grid-cols-2`.

function QuickHelp() {
  return (
    <section className="space-y-3">
      <h3 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
        Quick help
      </h3>
      <div className="grid gap-3 sm:grid-cols-2">
        <Link
          href="/agents/new"
          className="group flex flex-col rounded-lg border bg-card p-4 transition-colors hover:border-foreground/30 hover:bg-accent/40"
        >
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Plug size={18} aria-hidden />
          </div>
          <div className="mt-3 text-sm font-medium">Connect a new agent</div>
          <p className="mt-1 text-xs text-muted-foreground">
            Five minutes. Connect your agent with 3 lines of Python via the SDK or HTTP API.
          </p>
          <span className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-primary group-hover:underline">
            Start <ChevronRight size={12} />
          </span>
        </Link>

        <Link
          href="/drift-engine/docs"
          className="group flex flex-col rounded-lg border bg-card p-4 transition-colors hover:border-foreground/30 hover:bg-accent/40"
        >
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
            <BookOpen size={18} aria-hidden />
          </div>
          <div className="mt-3 text-sm font-medium">How verification works</div>
          <p className="mt-1 text-xs text-muted-foreground">
            What we check, and what stays private. The two-layer trust
            model in plain language.
          </p>
          <span className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-emerald-700 group-hover:underline dark:text-emerald-400">
            Read docs <ChevronRight size={12} />
          </span>
        </Link>
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Page                                                                        //
// --------------------------------------------------------------------------- //

export default async function DashboardPage() {
  let agents: AgentSummary[] = [];
  let count = 0;
  let error: string | null = null;

  try {
    const res = await listAgents({ limit: 100 });
    // #33 — hide Metalins's own internal/system agents (e2e, dogfood,
    // calibration, orchestrator) from the customer view. Filter only,
    // never delete; count reflects what the customer actually sees.
    agents = res.agents;
    count = agents.length;
  } catch (err) {
    error =
      err instanceof ApiError
        ? `${err.status} — ${err.message}`
        : err instanceof Error
          ? err.message
          : "Unknown error";
  }

  const fleetState = computeFleetState(agents);

  // ux-1 — surface the API key at the fold so a new user can grab it in
  // seconds instead of hunting through /settings. A failure here must
  // never take down the dashboard, so we degrade to "no card" on error.
  let activeKey: { name: string | null; created_at: string | null } | null =
    null;
  try {
    const { keys } = await listCustomerKeys();
    const active = keys.filter((k) => k.is_active);
    const chosen =
      active.find((k) => k.scope === "customer-wide") ?? active[0] ?? null;
    if (chosen) {
      activeKey = { name: chosen.name, created_at: chosen.created_at };
    }
  } catch {
    activeKey = null;
  }

  return (
    <main className="space-y-8">
      <ApiKeyOnboarding activeKey={activeKey} />

      {error ? (
        <section className="rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm">
          <div className="font-medium text-destructive">
            Could not load your agents
          </div>
          <div className="mt-1 text-destructive/90">{error}</div>
          <div className="mt-2 text-xs text-muted-foreground">
            Your session may have expired. Try signing out and back in.
          </div>
        </section>
      ) : (
        <FleetHero state={fleetState} />
      )}

      {!error && agents.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
              Your agents{" "}
              <span className="ml-1 text-muted-foreground/70">({count})</span>
            </h2>
            {/* UX-5.15.AB — bumped from a flat outline button to a
                solid primary CTA. Same size, just more presence so
                the customer's eye actually catches it. The icon
                replaces the literal "+" character so it scales with
                the type. */}
            <Link
              href="/agents/new"
              className="inline-flex items-center gap-1.5 rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background shadow-sm transition-colors hover:bg-foreground/90"
            >
              <Plus size={14} aria-hidden />
              New agent
            </Link>
          </div>
          <ul className="space-y-2">
            {agents.map((a) => (
              <li key={a.agent_id}>
                <AgentRow agent={a} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Quick help is a secondary footer for a populated dashboard.
          On the empty state the FleetHero already IS the connect +
          how-it-works CTA, so showing QuickHelp there just repeats it
          (Jose, 2026-05-22) — hide it until there's a fleet. */}
      {!error && agents.length > 0 && <QuickHelp />}
    </main>
  );
}

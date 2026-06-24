/**
 * Agent detail page — `/agents/[id]`.
 *
 * Sprint UX-5.5c (2026-05-16): redesigned to match the 3-state model
 * from docs/product/PRODUCT-EXPERIENCE-V2.md §6.
 *
 *   • Calma (default, ~95%): no gauge, no factor table. A "Healthy."
 *     headline + the Share-verification card (Carlos / Sofía JTBD)
 *     promoted to a primary surface. Activity + manage live below.
 *   • Atención (medium confidence): the gauge + score factors appear
 *     headline-driven, with action buttons inferred from the dominant
 *     factor. The Share card collapses to a secondary position.
 *   • Acción (low confidence or revoked): the whole page collapses to
 *     one card with the problem statement and one recommended action.
 *     "I'll handle later" stays visible — agency without pressure
 *     (calm-UX principle).
 *
 * D-PROD.18 stays on: we never name κ-Proof / RS256 / RKS / MVS /
 * ICR / ZKH in the customer copy. Verdicts are in plain language.
 *
 * Server Component. Fans out 3 parallel API requests for agent +
 * observables + probes, just like before.
 */
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ApiError,
  getAgent,
  getObservables,
  getProbes,
  type AgentDetail,
  type ObservableSnapshot,
  type ProbeRow,
  type ObservablesHistoryResponse,
  type ProbesResponse,
} from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { AgentSettings } from "./AgentSettings";
import { AgentIdCopy } from "./AgentIdCopy";
import { RefreshScoreButton } from "./RefreshScoreButton";
import { IssueClaim } from "./IssueClaim";
import { LiveVerification } from "./LiveVerification";
import ProtectionsChecklist from "./ProtectionsChecklist";
import { ShareVerification } from "./ShareVerification";
import { StripNewParam } from "./StripNewParam";
import { TierBadge } from "./TierBadge";
import { VerificationsPanel } from "./VerificationsPanel";
import { WizardProgress } from "@/components/WizardProgress";
import {
  CollapsedSection,
  MVSHistoryTimeline,
  PendingProbesPanel,
  ScoreFactors,
  TrustPanel,
} from "@/components/agents";
import { DriftAlert } from "@/components/agents/DriftAlert";
import { WatcherAlert } from "@/components/agents/WatcherAlert";
import { ProfileMismatchAlert } from "@/components/agents/ProfileMismatchAlert";
import { IssueCard } from "@/components/agents/AgentAlert";
import { deriveIssues } from "@/lib/agent-issues";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ new?: string }>;
}

/**
 * Tab title shows the agent name (or its slug) so multiple agent
 * tabs are distinguishable in the browser tab strip. Sprint UX-5.8d
 * (#641).
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const agentId = decodeURIComponent(id);
  try {
    const agent = await getAgent(agentId);
    return { title: agent.name || "Agent" };
  } catch {
    return { title: "Agent" };
  }
}

interface AgentBundle {
  agent: AgentDetail;
  observables: ObservablesHistoryResponse;
  probes: ProbesResponse;
}

async function loadBundle(agentId: string): Promise<AgentBundle> {
  const [agent, observables, probes] = await Promise.all([
    getAgent(agentId),
    getObservables(agentId, { limit: 50 }),
    getProbes(agentId, { status: "all", limit: 100 }),
  ]);
  return { agent, observables, probes };
}

function splitProbes(probes: ProbeRow[]): {
  pending: ProbeRow[];
  history: ProbeRow[];
} {
  const now = Date.now();
  const pending: ProbeRow[] = [];
  const history: ProbeRow[] = [];
  for (const p of probes) {
    const isResponded = !!p.responded_at;
    const expiresMs = p.expires_at ? new Date(p.expires_at).getTime() : null;
    const isExpired = expiresMs !== null && expiresMs < now;
    if (!isResponded && !isExpired) {
      pending.push(p);
    } else {
      history.push(p);
    }
  }
  return { pending, history };
}

function LatestObservableHint(snap: ObservableSnapshot | null): string {
  // UX-5.15.J Fix 2A — strip the "window of N events" string from the
  // customer surface. The N (and the fact that there is a fixed window
  // size) is calibration IP and gives away the score's denominator.
  // The backend still returns `n_events` in the API response for
  // internal debugging; we just don't render it here.
  if (!snap || !snap.ts) return "no batch run yet";
  return timeAgo(snap.ts);
}

// --------------------------------------------------------------------------- //
// Body layout: Empty / Baselining / Calma / Atención                          //
// --------------------------------------------------------------------------- //
//
// UX-5.15.AG — the problem list is now computed separately by
// `deriveIssues()` (see lib/agent-issues.ts) and rendered as a stack of
// homogeneous AgentAlert cards above the body. `deriveState` no longer
// decides the headline — it only picks which BODY layout to render:
//
//   • Revoked / inactive → atención (investigation) body. The revoked
//     AgentAlert on top carries the headline; there's no longer a
//     dedicated full-page ActionState collapse.
//   • Event count = 0 → empty body (LiveVerification "waiting for
//     first event"). Any alerts stack above it.
//   • Any issue → atención body (trust + factors expanded so the
//     customer can investigate).
//   • Behavioral not_enough_data → baselining. Else → calma.
//
// The positive heroes ("Healthy" / "calibrating") live inside the
// calma/baselining bodies and, by construction, only render when there
// are no issues — so a green verdict never sits beside a red alert.

type DetailState = "empty" | "baselining" | "calma" | "atencion";

function deriveState(agent: AgentDetail, hasIssues: boolean): DetailState {
  if (!agent.is_active) return "atencion";
  if (agent.event_count === 0) return "empty";
  if (hasIssues) return "atencion";
  const behavioral = agent.trust?.behavioral.state ?? "not_enough_data";
  if (behavioral === "not_enough_data") return "baselining";
  return "calma";
}

// --------------------------------------------------------------------------- //
// Page                                                                        //
// --------------------------------------------------------------------------- //

export default async function AgentDetailPage({
  params,
  searchParams,
}: PageProps) {
  const [{ id }, sp] = await Promise.all([params, searchParams]);
  const agentId = decodeURIComponent(id);
  const isJustCreated = sp.new === "1";

  let bundle: AgentBundle | null = null;
  let error: { status: number; message: string } | null = null;
  try {
    bundle = await loadBundle(agentId);
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.status === 404) notFound();
      error = { status: err.status, message: err.message };
    } else {
      error = {
        status: 0,
        message: err instanceof Error ? err.message : "Unknown error",
      };
    }
  }

  if (error || !bundle) {
    return (
      <main className="space-y-4">
        <Link
          href="/dashboard"
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← Back to agents
        </Link>
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm">
          <div className="font-medium text-destructive">
            Could not load agent
          </div>
          <div className="mt-1 text-destructive/90">
            {error
              ? `${error.status || "?"} — ${error.message}`
              : "Unknown error"}
          </div>
        </div>
      </main>
    );
  }

  const { agent, observables, probes } = bundle;
  const snap = agent.latest_observables;
  // UX-5.15.AG — one homogeneous problem list. Every issue an agent
  // can have (revoked, crypto failing, behavioral drift or warnings,
  // watcher error) becomes a stacked AgentAlert card below;
  // deriveState only decides the body layout, not the headline.
  const issues = deriveIssues(agent);
  const state = deriveState(agent, issues.length > 0);
  const { pending: pendingProbes, history: historyProbes } = splitProbes(
    probes.probes
  );
  const enc = encodeURIComponent(agent.agent_id);
  // UX-5.15.AD (2026-05-19) — the per-agent surface-policy gating
  // (was: read metadata.use_case → drive SurfacePolicy → hide
  // Share / IssueClaim / anchors / alerts emphasis) is gone. Every
  // agent now sees every surface; legacy metadata.use_case values
  // are simply ignored.

  // Sprint UX-5.10-9 — wizard progress when arriving via ?new=1.
  // UX-5.15.Y (2026-05-19): in the original UX-5.5d flow the agent
  // detail page WAS the wizard's last step, so showing BASICS / PICK
  // PATH / SETUP / VERIFY on top while events trickled in made sense.
  // Sprint UX-5.15.S split the wizard into its own /connect → /mcp
  // /setup sub-pages, and the detail page is now the terminus — once
  // you land here with an integration bound, you've already left the
  // wizard. Showing the steps then is misleading ("am I stuck on
  // VERIFY?"). New rule: only render the wizard progress when the
  // user arrived via ?new=1 AND hasn't picked an integration yet
  // (i.e. they bounced back to the detail from the picker without
  // continuing). Once `integration.surface` flips to mcp/watcher,
  // the wizard has done its job and we drop the breadcrumb.
  const wizardStep: 1 | 2 | 3 | 4 | null =
    isJustCreated && agent.integration.surface === "none" ? 2 : null;

  // UX-5.15.Y — once the agent is bound to an integration, strip the
  // stale `?new=1` from the URL so it doesn't leak into copy/paste,
  // bookmarks, or a refresh. The picker + wizard breadcrumb are
  // already hidden at this point; this just keeps the address bar
  // honest. Pure side-effect; no UI.
  const shouldStripNewParam =
    isJustCreated && agent.integration.surface !== "none";

  return (
    <main className="space-y-8">
      <StripNewParam shouldStrip={shouldStripNewParam} />
      {wizardStep && (
        <div className="pt-2">
          <WizardProgress currentStep={wizardStep} />
        </div>
      )}
      {/* Header */}
      <div className="space-y-2">
        <Link
          href="/dashboard"
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← Back to agents
        </Link>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="text-3xl font-semibold tracking-tight">
                {agent.name}
              </h1>
              {/* UX-5.15.J Fix 4 — TierBadge prominently in the header
                  so Andrea can see her agent's coverage tier at a
                  glance without scrolling into the Protections list.
                  UX-5.15.A — `tier` is now server-derived; falls back to
                  nothing if absent (older deploys). */}
              <TierBadge tier={agent.tier} />
              {/* UX-5.15.AG — revoked chip in the header. The detail
                  page no longer collapses to a dedicated ActionState
                  for revoked agents; it renders normally with the
                  revoked AgentAlert on top, so the header carries the
                  status chip the old ActionState used to show. */}
              {!agent.is_active && (
                <Badge variant="destructive">revoked</Badge>
              )}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-sm text-muted-foreground">
              {/* UX-5.15.J Fix 5 — the internal agent_id used to be
                  the first thing in the subtitle. Andrea has no idea
                  what to do with it; power users + support tickets
                  still need it. Moved into a small copy-to-clipboard
                  pill so the visual stays clean while keeping the ID
                  one click away. */}
              <AgentIdCopy agentId={agent.agent_id} />
              {agent.model ? <span>{agent.model}</span> : null}
              {agent.framework ? (
                <>
                  <span aria-hidden>·</span>
                  <span>{agent.framework}</span>
                </>
              ) : null}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {/* IssueClaim is the agent-to-agent verifiable JWT minter
                (Sprint 6-A2A 6.1).
                Sprint UX-5.11 / bug-sofia-2 (2026-05-17): we used to
                gate this to !empty && !baselining, which hid it for
                months from any vendor running fewer than ~2,000 events.
                Vendor Day-1 cases (Sofía: HuggingFace listing) need
                claim issuance long before behavioral baseline. The
                claim itself only attests to what's signed; with
                event_count === 0 it still issues a valid JWT proving
                "this agent is registered to this customer at time T",
                which is exactly the trust signal buyers need.
                Gate now: just is_active.
                bug-r1-andrea-2 (Sprint UX-5.11 R2): additional gate on
                use_case — Andrea's personal-AI flow has no A2A
                JTBD, so we hide IssueClaim entirely for her. Other
                use cases (creator/production/vendor) keep it. Legacy
                agents pre-radio resolve to permissive policy and see
                it. */}
            {/* UX-5.15.AD — IssueClaim shows for every active agent.
                Previously gated by use_case (personal hid it); now
                every agent gets the A2A surface and the customer
                ignores it if they don't need it. */}
            {agent.is_active && (
              <IssueClaim
                agentId={agent.agent_id}
                agentName={agent.name}
                publicSlug={agent.public_slug ?? null}
              />
            )}
            {agent.integration.surface === "watcher" && (
              <>
                <Link
                  href={`/agents/${enc}/watchers`}
                  className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                >
                  Manage bot
                </Link>
                <Link
                  href={`/agents/${enc}/anchors`}
                  className="rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-accent"
                >
                  External anchors
                </Link>
              </>
            )}
            {agent.integration.surface === "mcp" && (
              <>
                {/* gh-122 — "Manage MCP" routed to the cloud MCP server
                    config, which doesn't exist in self-hosted. Removed.
                    External anchors stay: public verify links apply to
                    every agent regardless of integration surface. */}
                <Link
                  href={`/agents/${enc}/anchors`}
                  className="rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-accent"
                >
                  External anchors
                </Link>
              </>
            )}
            {/* Sprint UX-5.11 / bug-diana-1: Alerts must be reachable
                regardless of integration surface. Diana didn't see the
                old 'Webhook alerts' link because it was gated to
                surface=='mcp' — she had created an agent but not
                connected yet, so the surface was 'none' and the link
                was hidden. Now Alerts is always discoverable and
                lives at /agents/[id]/alerts (renamed from /webhooks
                per Diana's expectation — she hunted for /alerts). */}
            <Link
              href={`/agents/${enc}/alerts`}
              className="rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-accent"
            >
              Alerts
            </Link>
            {agent.integration.surface === "none" && (
              // UX-5.17 docs/UX pass — one "Connect" button routes to
              // the /connect picker, which presents all three paths
              // (HTTP API / SDK, MCP, public-bot watcher) API-first.
              // Previously the header hard-coded just MCP + bot, so the
              // API/SDK path was unreachable from the agent detail.
              <Link
                href={`/agents/${enc}/connect`}
                className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                Connect this agent
              </Link>
            )}
          </div>
        </div>
      </div>

      {/* Post-create panel — shown on first landing only.
          UX-5.15.Y (2026-05-19): also gated on integration.surface ===
          "none". Previously the picker stayed visible whenever
          `?new=1` was in the URL — so a user who finished the MCP
          sub-wizard and clicked "Back to agent" still saw the
          SDK/BOT/MCP picker on top of an agent that already had an
          integration set up and was logging events. Now the picker
          only appears for fresh agents that haven't bound to an
          integration yet; once `integration.surface` flips to
          "mcp" or "watcher", the picker disappears even if `?new=1`
          is still in the address bar. */}
      {isJustCreated && agent.integration.surface === "none" && (
        <section className="rounded-lg border-2 border-emerald-500/40 bg-emerald-500/5 p-6">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-400">
            Agent created ✓
          </div>
          <h2 className="text-xl font-semibold tracking-tight">
            Pick how this agent will talk to Metalins
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Choose one — this agent&apos;s identity is bound to one
            integration. You can come back later if you&apos;re not ready.
          </p>
          {/* Sprint UX-5.11 R2 — optional anchor hint after integration
              pick. Anchors are NOT mandatory; the agent works without
              them. They matter only if you're going to share the verify
              link publicly.
              UX-5.15.AD — surface-policy gating removed; the hint
              shows for every agent now. Customers who don't share
              publicly just ignore it. */}
          <p className="mt-3 rounded-md border border-emerald-500/30 bg-background/40 p-3 text-xs text-muted-foreground">
            <strong className="text-foreground">Planning to share the verify link?</strong>{" "}
            Then consider adding an{" "}
            <Link
              href={`/agents/${enc}/anchors`}
              className="font-medium text-foreground underline underline-offset-2"
            >
              external anchor
            </Link>
            {" "}— a public handle you already control (Telegram,
            GitHub, or DNS). Visitors cross-check it on that
            platform themselves, so trust doesn&apos;t depend on
            Metalins alone. Optional &mdash; the agent works without
            it.
          </p>
          {/* UX-5.17 docs/UX pass — route to the /connect picker
              instead of duplicating the path cards inline. The picker
              presents all three paths (HTTP API / SDK first, then MCP,
              then public-bot watcher); keeping a second copy here is
              what let the API/SDK path silently fall off this panel. */}
          <div className="mt-5">
            <Link
              href={`/agents/${enc}/connect?new=1`}
              className="inline-flex items-center rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-600/90"
            >
              Choose how to connect →
            </Link>
            <p className="mt-2 text-xs text-muted-foreground">
              HTTP API / SDK for backend agents, MCP for chat &amp;
              editor clients, or a zero-code public-bot watcher.
            </p>
          </div>
        </section>
      )}

      {/* UX-5.15.AG — homogeneous problem stack. Every issue the agent
          has (revoked, crypto failing, behavioral drift or warnings,
          watcher error) renders as one AgentAlert card, ordered
          most-severe first. They lead the page; the state-driven body
          renders below unchanged. DriftAlert and WatcherAlert keep
          their own interactive/explanatory bodies but render through
          the same AgentAlert shell as the generic IssueCard, so every
          problem looks identical regardless of kind. Several can show
          at once — they just stack. */}
      {issues.length > 0 && (
        <div className="space-y-4">
          {issues.map((issue) => {
            if (issue.kind === "drift") {
              return (
                <DriftAlert
                  key={issue.key}
                  agentId={agent.agent_id}
                  agentName={agent.name}
                />
              );
            }
            if (issue.kind === "watcher") {
              return (
                <WatcherAlert
                  key={issue.key}
                  agentId={agent.agent_id}
                  agentName={agent.name}
                />
              );
            }
            if (issue.kind === "profile") {
              return (
                <ProfileMismatchAlert
                  key={issue.key}
                  agent={agent}
                  issue={issue}
                />
              );
            }
            return <IssueCard key={issue.key} issue={issue} />;
          })}
        </div>
      )}

      {/* State-driven render — Sprint UX-5.8 (#638-641).
          Each state owns the entire body of the page. Empty and
          Baselining intentionally hide Share / Issue Claim /
          Verifications panel because there's nothing real to attest
          to yet. */}
      {state === "empty" && agent.is_active && (
        <>
          <LiveVerification
            agentId={agent.agent_id}
            initialEventCount={agent.event_count}
            surface={agent.integration.surface}
          />
          {/* Sprint UX-5.11 / bug-sofia-1: vendors who want to LAUNCH
              with a verified listing (HuggingFace Spaces, marketplace
              etc.) need the share link + embeddable badge from event 0.
              The carlos-3 fix only surfaced this in baselining (event
              ≥ 1). For a 30-subs/mo vendor that gap is months. The
              `daystate="registered"` variant reframes the copy honestly
              — no false-verified claim — while exposing the same share
              + badge tooling.
              UX-5.15.AD: surface-policy gating dropped; ShareVerification
              renders for every empty-state agent.
              UX-5.15.AE: wrapped in CollapsedSection — the empty-state
              hero is LiveVerification ("waiting for first event"); the
              share link is secondary until there's actually something
              to verify, so it stays collapsed by default like the
              other non-hero panels. */}
          <CollapsedSection
            title="Share verification link"
            summary="Get a public link others can use to confirm this agent is yours."
          >
            <ShareVerification
              agentId={agent.agent_id}
              agentName={agent.name}
              publicSlug={agent.public_slug}
              daystate="registered"
              compact
            />
          </CollapsedSection>
        </>
      )}

      {state === "baselining" && (
        <BaseliningState agent={agent} snap={snap} />
      )}

      {state === "calma" && (
        <CalmState
          agent={agent}
          snap={snap}
          historyProbes={historyProbes}
          pendingProbes={pendingProbes}
        />
      )}

      {state === "atencion" && (
        <AttentionState
          agent={agent}
          snap={snap}
          historyProbes={historyProbes}
          pendingProbes={pendingProbes}
        />
      )}

      {/* UX-5.15.J Fix 6 — protections checklist moved BELOW the
          state-driven hero (Healthy / Baselining / Attention). The two-
          layer trust card answers "are we OK?" — the protections list
          is the per-row breakdown that backs the answer.
          UX-5.15.P / P.5 — in calma/baselining we collapse this. In
          atencion/accion we leave it expanded so the customer sees
          what's covered while investigating. */}
      {agent.is_active && agent.protections && (
        (state === "calma" || state === "baselining") ? (
          <CollapsedSection
            title="Protections active"
            summary={(() => {
              const s = agent.protections!.summary;
              const upcoming = s.applicable_count - s.active_count;
              return upcoming > 0
                ? `${s.active_count} active · ${upcoming} unlock as it runs`
                : `${s.active_count} active`;
            })()}
            tone={state === "calma" ? "ok" : "info"}
          >
            <ProtectionsChecklist
              protections={agent.protections}
              agentId={agent.agent_id}
            />
          </CollapsedSection>
        ) : (
          <ProtectionsChecklist
            protections={agent.protections}
            agentId={agent.agent_id}
          />
        )
      )}

      {/* Verifications served — visible from Baselining onwards. Hidden
          for empty agents because there can't be any verifications
          when the agent has never logged an event.
          UX-5.15.P / P.5 — collapsed in quiet states. */}
      {state !== "empty" && (
        (state === "calma" || state === "baselining") ? (
          <CollapsedSection
            title="Verifications served"
            summary="Recent verify-proof requests against this agent."
          >
            <VerificationsPanel agentId={agent.agent_id} />
          </CollapsedSection>
        ) : (
          <VerificationsPanel agentId={agent.agent_id} />
        )
      )}

      {/* Settings + Danger zone — bottom of the page, collapsed by
          default (Sprint UX-5.11 R2, 2026-05-18). bug-r1-andrea-2.d:
          the section was previously always-expanded and the danger
          zone red box pulled the eye every time you scrolled down.
          Now it's a closed details element. */}
      <AgentSettings
        agentId={agent.agent_id}
        initialName={agent.name}
        initialModel={agent.model}
        initialFramework={agent.framework}
        initialMetadata={agent.metadata}
        isActive={agent.is_active}
        integrationSurface={agent.integration.surface}
      />
    </main>
  );
}

// --------------------------------------------------------------------------- //
// Baselining — first events arriving, identity not yet trustworthy             //
// --------------------------------------------------------------------------- //
//
// The agent has logged real events but not enough for the identity
// signal to be statistically meaningful. We tell the truth: "we're
// learning". We DELIBERATELY do not show:
//   • "Healthy." (we don't know yet)
//   • Share verification (a public link backed by zero baseline is
//     worse than no link — gives the visitor false confidence)
//   • IssueClaim (no claim to attest to)
//
// What we DO show: progress + activity counters so the customer
// knows things are working and how long until they get the real
// experience.

function BaseliningState({
  agent,
  snap,
}: {
  agent: AgentDetail;
  snap: ObservableSnapshot | null;
}) {
  // Sprint UX-5.15.I (task #849) — IP protection refactor. The
  // behavioral floor is calibration IP; we no longer surface the
  // specific number to customers. The progress bar still tracks
  // observed/floor ratio internally for the visual, but the copy
  // only mentions the observed count and a generic "enough
  // activity" phrasing. The floor still arrives in the trust
  // block (used elsewhere); falling back to a defensive default
  // if the server didn't send it.
  const floor = agent.trust?.behavioral.events_floor ?? 2000;
  const observed = agent.trust?.behavioral.events_observed ?? agent.event_count;
  const ratio = Math.min(1, observed / floor);
  const pct = Math.round(ratio * 100);
  // gh-82 — a fresh agent whose cryptographic identity is still being
  // established (state "unverified" = "Setting up") must NOT claim
  // "Cryptographic identity verified". We tell the onboarding truth
  // instead: the system is observing and learning, nothing is wrong.
  const settingUp = (agent.trust?.cryptographic.state ?? "unverified") !== "verified";
  return (
    <>
      <section className="rounded-2xl border border-sky-500/30 bg-sky-500/[0.04] p-8 md:p-10">
        <div className="flex items-start gap-4">
          <div
            className="mt-1 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-sky-500/15 text-sky-600 dark:text-sky-400"
            aria-hidden="true"
          >
            ⋯
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">
              {settingUp
                ? "Setting up — establishing this agent's identity."
                : "Cryptographic identity verified. Still learning your baseline."}
            </h2>
            <p className="mt-1.5 text-sm text-muted-foreground">
              {settingUp ? (
                <>
                  Your agent is being observed. We&apos;ll establish its
                  identity baseline as events are recorded —{" "}
                  {observed.toLocaleString()} so far. Nothing is wrong; a
                  brand-new agent simply hasn&apos;t completed its first
                  identity checks yet.
                </>
              ) : (
                <>
                  {observed.toLocaleString()+' '} events collected so far. The
                  behavior layer kicks in once we have enough activity to
                  know what &quot;normal&quot; looks like for this agent —
                  the cryptographic check already proves the identity
                  itself.
                </>
              )}
            </p>
            <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-sky-500 transition-all"
                style={{ width: `${Math.max(2, pct)}%` }}
                aria-label={`Learning your baseline — ${pct}% of the way there`}
              />
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              {snap?.ts
                ? `Last check ${timeAgo(snap.ts)}.`
                : "First identity check runs after the next batch window."}
            </p>
          </div>
        </div>
      </section>

      {/* UX-5.15.P / P.5 — Baselining is also a quiet state. Trust
          breakdown collapsed by default (the hero already says crypto
          ✓ and behavior still learning the baseline). */}
      {agent.trust && (
        <CollapsedSection
          title="Trust details"
          summary={
            settingUp
              ? "Setting up · establishing identity, learning your baseline."
              : "Cryptographic identity verified · learning your baseline."
          }
          tone="info"
        >
          <TrustPanel trust={agent.trust} />
        </CollapsedSection>
      )}

      {/* Sprint UX-5.11 / bug-carlos-3: surface share-verification in
          baselining state. Once cryptographic identity is verified
          (which happens from event 1), creators can already share
          the link — followers don't need behavioral baseline to
          validate "this is the real X". The compact variant
          de-emphasizes the embed badge while keeping URL +
          share-buttons one-tap available.
          UX-5.15.AD: use_case gating removed; the card renders for
          every active agent with a verified crypto signature. */}
      {agent.is_active &&
        agent.trust?.cryptographic.state === "verified" && (
          <ShareVerification
            agentId={agent.agent_id}
            agentName={agent.name}
            publicSlug={agent.public_slug}
            compact
          />
        )}

      <CollapsedSection
        title="Activity so far"
        summary={`${agent.event_count.toLocaleString()} events · last ${timeAgo(agent.last_event_at)}`}
      >
        <dl className="grid gap-3 text-sm sm:grid-cols-3">
          <Stat
            label="Last activity"
            value={timeAgo(agent.last_event_at)}
          />
          <Stat
            label="Events captured"
            value={agent.event_count.toLocaleString()}
          />
          <Stat label="Latest check" value={LatestObservableHint(snap)} />
        </dl>
      </CollapsedSection>
    </>
  );
}

// --------------------------------------------------------------------------- //
// Calma — healthy, default                                                     //
// --------------------------------------------------------------------------- //

function CalmState({
  agent,
  snap,
  historyProbes,
  pendingProbes,
}: {
  agent: AgentDetail;
  snap: ObservableSnapshot | null;
  historyProbes: ProbeRow[];
  pendingProbes: ProbeRow[];
}) {
  return (
    <>
      {/* Headline-driven verdict. No gauge, no number. */}
      <section className="rounded-2xl border border-emerald-500/30 bg-emerald-500/[0.04] p-8 md:p-10">
        <div className="flex items-start gap-4">
          <div
            className="mt-1 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
            aria-hidden="true"
          >
            ✓
          </div>
          <div className="min-w-0">
            <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">
              Healthy.
            </h2>
            <p className="mt-1.5 text-sm text-muted-foreground">
              {snap?.ts
                ? `We verified this agent ${timeAgo(snap.ts)}. Nothing unusual.`
                : "Connect this agent or send its first event to start verifying."}
              {agent.event_count > 0
                ? ` ${agent.event_count.toLocaleString()} events captured.`
                : ""}
            </p>
          </div>
        </div>
      </section>

      {/* UX-5.15.P / P.5 — Calma is the quiet state. The hero card
          above already says "Healthy" in one sentence. Trust details
          and activity belong below the fold, collapsed by default.
          The customer who wants to dig in clicks; the customer who
          just wants reassurance is done. */}
      {agent.trust && (
        <CollapsedSection
          title="Trust details"
          summary="Cryptographic identity verified · behavior consistent."
          tone="ok"
        >
          <TrustPanel trust={agent.trust} />
        </CollapsedSection>
      )}

      {/* Share verification — primary surface in Calma.
          UX-5.15.AD: surface-policy gating removed; renders for
          every active agent. */}
      {agent.is_active && (
        <ShareVerification
          agentId={agent.agent_id}
          agentName={agent.name}
          publicSlug={agent.public_slug}
        />
      )}

      {/* Activity — collapsed by default. Summary in one line. */}
      <CollapsedSection
        title="Activity"
        summary={`${agent.event_count.toLocaleString()} events · last ${timeAgo(agent.last_event_at)}`}
      >
        <div className="flex items-baseline justify-end">
          <RefreshScoreButton
            agentId={agent.agent_id}
            eventCount={agent.event_count}
          />
        </div>
        <dl className="mt-2 grid gap-3 text-sm sm:grid-cols-3">
          <Stat
            label="Last activity"
            value={timeAgo(agent.last_event_at)}
          />
          <Stat
            label="Events captured"
            value={agent.event_count.toLocaleString()}
          />
          <Stat label="Latest check" value={LatestObservableHint(snap)} />
        </dl>

        {agent.probe_capable && historyProbes.length > 0 && (
          <details className="group mt-5">
            <summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground">
              Show recent verification checks ({historyProbes.length})
            </summary>
            <div className="mt-3 rounded-md border bg-background/40 p-3">
              <MVSHistoryTimeline probes={historyProbes} />
            </div>
          </details>
        )}

        {agent.probe_capable && pendingProbes.length > 0 && (
          <details className="group mt-3">
            <summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground">
              Pending checks ({pendingProbes.length})
            </summary>
            <div className="mt-3 rounded-md border bg-background/40 p-3">
              <PendingProbesPanel probes={pendingProbes} />
            </div>
          </details>
        )}
      </CollapsedSection>
    </>
  );
}

// --------------------------------------------------------------------------- //
// Atención — something changed but not severe                                  //
// --------------------------------------------------------------------------- //

function AttentionState({
  agent,
  snap,
  historyProbes,
  pendingProbes,
}: {
  agent: AgentDetail;
  snap: ObservableSnapshot | null;
  historyProbes: ProbeRow[];
  pendingProbes: ProbeRow[];
}) {
  // UX-5.15.AG — the amber headline hero is gone. The problem itself
  // is now one (or more) of the stacked AgentAlert cards rendered
  // above the body; this function only renders the investigation
  // detail — trust signals, factors and recent checks, expanded.
  return (
    <>
      {/* Two-layer trust + factors — the investigation body. */}
      {/* UX-5.15.AL — the Recent-checks column only renders for
          probe-capable agents; without it the section is single-column. */}
      <section
        className={
          agent.probe_capable ? "grid gap-6 md:grid-cols-2" : "grid gap-6"
        }
      >
        <div className="rounded-lg border bg-card p-6">
          <h2 className="mb-4 text-sm font-medium uppercase tracking-wide text-muted-foreground">
            Trust signals
          </h2>
          {agent.trust ? (
            <TrustPanel trust={agent.trust} />
          ) : (
            <p className="text-sm text-muted-foreground">
              No trust data yet.
            </p>
          )}
          <p className="mt-4 text-xs text-muted-foreground">
            {LatestObservableHint(snap)}
          </p>
          {snap?.score_factors && snap.score_factors.length > 0 && (
            <ScoreFactors factors={snap.score_factors} className="mt-5" />
          )}
        </div>

        {agent.probe_capable && (
          <div className="rounded-lg border bg-card p-6">
            <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted-foreground">
              Recent checks
            </h2>
            <MVSHistoryTimeline probes={historyProbes} />
            {pendingProbes.length > 0 && (
              <div className="mt-4 border-t pt-4">
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Pending ({pendingProbes.length})
                </h3>
                <PendingProbesPanel probes={pendingProbes} />
              </div>
            )}
          </div>
        )}
      </section>

      {/* Share verification still available, but collapsed below the
          attention card so it's not the visual focus.
          UX-5.15.AD: use_case gating removed. */}
      {agent.is_active && (
        <details className="group rounded-lg border bg-card/40 p-4">
          <summary className="cursor-pointer text-sm font-medium">
            Share verification link
          </summary>
          <div className="mt-4">
            <ShareVerification
              agentId={agent.agent_id}
              agentName={agent.name}
              publicSlug={agent.public_slug}
            />
          </div>
        </details>
      )}
    </>
  );
}

// --------------------------------------------------------------------------- //
// Small helper                                                                 //
// --------------------------------------------------------------------------- //

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-md border bg-background/40 p-3">
      <dt className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-1 text-sm font-medium">{value}</dd>
    </div>
  );
}

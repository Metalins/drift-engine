/**
 * deriveIssues — UX-5.15.AG (2026-05-19).
 *
 * Single source of truth for "what's wrong with this agent right now".
 *
 * Background (Jose, UX-5.15.AG): the agent detail page used to treat
 * each kind of problem differently — a severe crypto/revoked problem
 * collapsed the whole page to one card (early-return ActionState); a
 * behavioral warning showed a bespoke amber hero that surfaced only
 * the FIRST score factor and dropped the rest; drift and watcher
 * errors were one-off pedagogical cards bolted on top. Three problem
 * types, three layouts.
 *
 * New model: every problem an agent can have is one homogeneous alert
 * card. They stack (several at once is normal), each carries its own
 * explanation + actions, and the rest of the page renders below
 * unchanged — nothing "collapses". This module computes that list.
 *
 * The page maps each issue to a card:
 *   - kind "card"    → generic <IssueCard> (title + copy + actions)
 *   - kind "drift"   → <DriftAlert>  (interactive: accept / investigate)
 *   - kind "watcher" → <WatcherAlert> (explains a failed bot poll)
 * All three render through the shared <AgentAlert> shell, so they look
 * identical regardless of which problem they describe.
 *
 * D-PROD.18: copy here is customer-facing — no internal mechanism
 * names. The per-mechanism detail comes from `score_factors[].message`
 * / `trust.*.factors[].message`, which the backend already sanitizes
 * via explain_score().
 */
import type {
  AgentDetail,
  CryptographicLayer,
  FactorGuidance,
  ScoreFactor,
} from "./api";
import { displayAttention } from "./display-messages";
import { timeAgo } from "./utils";

export type IssueSeverity = "action" | "attention" | "info";

/**
 * One per-factor bullet in an alert card. gh-81 — `guidance` carries the
 * "what does this mean / is it a problem / next step" expand; absent for
 * factors the backend ships no guidance for.
 */
export interface AttentionBullet {
  text: string;
  guidance?: FactorGuidance;
}

/**
 * "card" issues are pure data rendered by <IssueCard>. "drift" and
 * "watcher" issues carry no data — the page swaps in the dedicated
 * interactive component, which still renders through <AgentAlert> so
 * the chrome stays homogeneous.
 */
export type IssueKind = "card" | "drift" | "watcher" | "profile";

export interface IssueAction {
  label: string;
  href: string;
  primary?: boolean;
}

export interface AgentIssue {
  /** Stable React key + dedupe id. */
  key: string;
  kind: IssueKind;
  severity: IssueSeverity;
  /** Present for kind "card". */
  title?: string;
  paragraphs?: string[];
  /**
   * Per-mechanism detail — one bullet per factor that flagged. This is
   * where "any of the baseline mechanisms shows up here" lands: each
   * warning factor's sanitized message becomes a bullet, plus (gh-81) its
   * learn_more expand.
   */
  bullets?: AttentionBullet[];
  actions?: IssueAction[];
  /**
   * Present for kind "profile" (UX-5.15.AM) — the agent_profile slug the
   * engine suggests. ProfileMismatchAlert turns it into a one-click fix.
   */
  suggestedProfile?: string;
}

function severityRank(s: IssueSeverity): number {
  return s === "action" ? 0 : s === "attention" ? 1 : 2;
}

function warningMessages(factors: ScoreFactor[] | undefined): string[] {
  return (factors ?? [])
    .filter((f) => f.severity === "warning")
    .map((f) => displayAttention(f.code, f.message));
}

function cryptoWarnings(crypto: CryptographicLayer | undefined): string[] {
  return warningMessages(crypto?.factors);
}

/**
 * Behavioral symptoms — UX-5.15.AI.
 *
 * Reads ONLY the behavioral layer's own factors. The earlier version
 * preferred `latest_observables.score_factors`, but that is the FULL
 * union (cryptographic + behavioral) — so a cryptographic factor like
 * "memory checks are failing" leaked into the behavioral card and the
 * same finding rendered twice, in two different cards, making one
 * problem look like two. `trust.behavioral.factors` is the per-layer
 * split the backend already computed (see LAYER_OF_FACTOR server-side).
 */
function behaviorWarnings(agent: AgentDetail): AttentionBullet[] {
  // UX-5.15.AM — profile_mismatch is pulled out into its own
  // ProfileMismatchAlert (it carries an executable action), so exclude
  // it here: otherwise the warning-direction factor would ALSO render
  // as a generic bullet in the "something changed" card.
  return (agent.trust?.behavioral.factors ?? [])
    .filter((f) => f.severity === "warning" && f.code !== "profile_mismatch")
    .map((f) => ({
      text: displayAttention(f.code, f.message),
      guidance: f.learn_more,
    }));
}

/**
 * The profile-mismatch factor (UX-5.15.AM), if the engine emitted one.
 * Severity "warning" = declared stricter than observed (the dangerous
 * direction); "info" = declared looser (an opportunity).
 */
function profileMismatchFactor(agent: AgentDetail): ScoreFactor | undefined {
  return (agent.trust?.behavioral.factors ?? []).find(
    (f) => f.code === "profile_mismatch",
  );
}

/**
 * Compute the agent's current problem list, most-severe first.
 *
 * Dedupe rules baked in:
 *   - A revoked agent returns ONLY the revoked issue — crypto /
 *     behavioral / watcher states are moot once the agent is dead.
 *   - When the behavioral layer reports drift, the interactive
 *     DriftAlert owns the behavioral story; we do NOT also emit the
 *     generic "something changed" card from the same warning factors.
 */
export function deriveIssues(agent: AgentDetail): AgentIssue[] {
  const issues: AgentIssue[] = [];
  const enc = encodeURIComponent(agent.agent_id);
  const crypto = agent.trust?.cryptographic;
  const behavioral = agent.trust?.behavioral;

  // 1 — Revoked / inactive. Terminal: nothing else is worth stacking.
  if (!agent.is_active) {
    const when = agent.revoked_at ? ` ${timeAgo(agent.revoked_at)}` : "";
    const reason = agent.revocation_reason
      ? ` — ${agent.revocation_reason}`
      : "";
    issues.push({
      key: "revoked",
      kind: "card",
      severity: "action",
      title: "This agent is revoked.",
      paragraphs: [
        `Revoked${when}${reason}. It no longer accepts events.`,
        "If you didn't mean to revoke it, register a fresh agent — the new one starts with a clean identity.",
      ],
      actions: [
        { label: "Register a fresh agent", href: "/agents/new", primary: true },
      ],
    });
    return issues;
  }

  // 2 — Cryptographic identity failing. Possible compromise → action.
  //
  // UX-5.15.AI — the card LEADS with the specific finding (the actual
  // factor messages), not a generic "unusual activity" headline. The
  // customer reads WHAT happened first, then what it means and what
  // to do. The vague "its identity signals look very different from
  // before" filler is gone — the factor messages already say,
  // concretely, what changed. The findings are paragraphs (not
  // bullets) because IssueCard renders paragraphs before bullets, and
  // the finding has to come first.
  if (crypto?.state === "action_required") {
    const findings = cryptoWarnings(crypto);
    issues.push({
      key: "crypto-action",
      kind: "card",
      severity: "action",
      title: "This agent's identity check is failing.",
      paragraphs: [
        ...(findings.length > 0
          ? findings
          : ["Its cryptographic identity checks are failing."]),
        "This usually means the agent's credentials were leaked, the model behind it was swapped, or another agent is logging events under its name. Recommended: revoke this agent and register a fresh one — the leaked credentials stop working the moment you revoke.",
      ],
      actions: [
        {
          label: "Open key & revoke options",
          href: `/agents/${enc}/keys`,
          primary: true,
        },
      ],
    });
  } else if (crypto?.state === "caution") {
    const findings = cryptoWarnings(crypto);
    issues.push({
      key: "crypto-caution",
      kind: "card",
      severity: "attention",
      title: "Identity check worth a look.",
      paragraphs: [
        ...(findings.length > 0
          ? findings
          : ["The cryptographic identity check flagged something."]),
        // UX-5.15.AJ — neutral trailer: works whether the caution is a
        // transient crypto blip or an agent that stopped answering its
        // memory checks (probes_unanswered). The finding above carries
        // the specific guidance.
        "Metalins keeps re-checking on every cycle — if it clears on its own there's nothing to do; if it sticks, take a closer look.",
      ],
    });
  }

  // 3 — Behavioral layer. Drift gets the dedicated interactive alert;
  //     otherwise any warning factors collapse into one card that
  //     lists every mechanism that flagged.
  if (behavioral?.state === "drift_detected") {
    issues.push({ key: "drift", kind: "drift", severity: "attention" });
  } else {
    const symptoms = behaviorWarnings(agent);
    if (symptoms.length > 0) {
      issues.push({
        key: "behavior",
        kind: "card",
        severity: "attention",
        title: "Something changed worth a look.",
        paragraphs: [
          "Recent activity doesn't fully line up with the pattern Metalins learned for this agent. What stood out:",
        ],
        bullets: symptoms,
      });
    }
  }

  // 3b — Profile mismatch (UX-5.15.AM). The declared agent_profile
  //      contradicts observed behavior. Distinct from a drift/warning
  //      card: it carries an EXECUTABLE action (one-click profile
  //      change), so the page swaps in <ProfileMismatchAlert>.
  const pmf = profileMismatchFactor(agent);
  if (pmf && pmf.suggested_profile) {
    issues.push({
      key: "profile",
      kind: "profile",
      // warning direction → amber; info direction → calm blue.
      severity: pmf.severity === "warning" ? "attention" : "info",
      paragraphs: [pmf.message],
      suggestedProfile: pmf.suggested_profile,
    });
  }

  // 4 — Watcher poll failing. Dedicated alert (explains + routes to
  //     the Manage bot page for the exact error + retry).
  //
  //     Read the state from `integration.watcher` — that is the field
  //     the detail endpoint populates. The top-level `watcher_state` is
  //     a dashboard-list-row optimization and comes back null on
  //     AgentDetail, so checking it here missed every watcher error on
  //     the detail page — a 0-event bot with a failing connection just
  //     showed the calm "Waiting for first activity" empty state and no
  //     alert at all (Jose, 2026-05-21).
  if (agent.integration.watcher?.state === "error") {
    issues.push({ key: "watcher", kind: "watcher", severity: "attention" });
  }

  return issues.sort(
    (a, b) => severityRank(a.severity) - severityRank(b.severity),
  );
}

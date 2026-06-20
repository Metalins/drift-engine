"use client";

import { useEffect, useRef, useState } from "react";
import type {
  ProtectionItem,
  ProtectionsBlock,
  ProtectionsLiveResponse,
} from "@/lib/api";

/** Client-side fetch via the Next.js proxy route. Cannot import the
 * server-side `getAgentProtections` directly here because lib/api.ts
 * pulls in `next/headers` for the Supabase server client. */
async function fetchProtectionsViaProxy(
  agentId: string,
): Promise<ProtectionsLiveResponse> {
  const res = await fetch(
    `/api/agents/${encodeURIComponent(agentId)}/protections`,
    { cache: "no-store" },
  );
  if (!res.ok) {
    throw new Error(`protections fetch failed: ${res.status}`);
  }
  return (await res.json()) as ProtectionsLiveResponse;
}

/**
 * Renders the customer-facing protections catalog as a progressive
 * checklist. Source: GET /v1/agents/{id} → summary.protections (Sprint
 * UX-5.15.C, per D-PROD.24).
 *
 * Sprint UX-5.15.UX1: auto-polls GET /v1/agents/{id}/protections every
 * 30 seconds when the tab is visible, so the customer sees protections
 * activate in real time without clicking Refresh. Manual refresh button
 * stays as user-initiated override (calls /recompute under the hood —
 * different cooldown).
 *
 * IP boundary: this component receives ONLY the customer-safe surface
 * (opaque slug, name, description, caveat, active/applicable flags,
 * events_to_activation delta). It never sees mechanism names, internal
 * IDs, threshold numbers, or observable math. See lib/api.ts ProtectionItem.
 */

const POLL_INTERVAL_MS = 30_000;

const TIER_LABELS: Record<string, string> = {
  T0: "Registered",
  T1: "Early signals",
  T2: "Standard",
  T3: "Full coverage",
};

const TIER_ORDER = ["T0", "T1", "T2", "T3"] as const;

type Tab = "active" | "pending" | "all";

export default function ProtectionsChecklist({
  protections: initialProtections,
  agentId,
}: {
  protections: ProtectionsBlock;
  agentId: string;
}) {
  const [tab, setTab] = useState<Tab>("active");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Live state — seeded with server-rendered initial, then polled.
  const [protections, setProtections] = useState<ProtectionsBlock>(initialProtections);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  const [tickNow, setTickNow] = useState<Date>(new Date());
  const [isRefreshing, setIsRefreshing] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 1-second ticker just to keep "Updated N seconds ago" honest.
  useEffect(() => {
    const t = setInterval(() => setTickNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  // Polling loop with visibility gating (no traffic on hidden tabs).
  useEffect(() => {
    let cancelled = false;

    async function refresh() {
      if (cancelled) return;
      if (typeof document !== "undefined" && document.visibilityState === "hidden") {
        return;
      }
      setIsRefreshing(true);
      try {
        const fresh = await fetchProtectionsViaProxy(agentId);
        if (cancelled) return;
        setProtections({
          agent_profile: fresh.agent_profile,
          items: fresh.items,
          summary: fresh.summary,
        });
        setLastUpdated(new Date());
      } catch {
        // Swallow — keep showing last successful snapshot. The freshness
        // indicator will reveal staleness.
      } finally {
        if (!cancelled) setIsRefreshing(false);
      }
    }

    pollRef.current = setInterval(refresh, POLL_INTERVAL_MS);
    function onVisibility() {
      if (document.visibilityState === "visible") refresh();
    }
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelled = true;
      if (pollRef.current) clearInterval(pollRef.current);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [agentId]);

  const ageSec = Math.max(0, Math.floor((tickNow.getTime() - lastUpdated.getTime()) / 1000));
  const ageStr =
    ageSec < 5 ? "just now" : ageSec < 60 ? `${ageSec}s ago` : `${Math.floor(ageSec / 60)}m ago`;

  const { items, summary, agent_profile } = protections;

  const active = items.filter((p) => p.active);
  // gh-79 — "Coming" = genuinely on this agent's activation path. Behavior-
  // gated protections (covered by an equivalent variant for this agent's
  // mode) are NOT pending; they only show under "All" with their note.
  const pending = items.filter(
    (p) => p.applicable && !p.active && p.applies_to_behavior !== false,
  );
  const notApplicable = items.filter((p) => !p.applicable);

  // gh-76 — explain the active/available gap. A new agent shows few active
  // protections not because features are missing but because most switch on
  // automatically once we've observed enough of its behavior. The header
  // counts ("3 active · 8 available") don't say that, so Diana read the gap
  // as "this agent is less protected" instead of "still warming up". Surface
  // a one-line banner: how many more will unlock, and how soon the next one
  // does (the smallest events_to_activation among the pending set).
  const pendingUnlockEvents = pending
    .map((p) => p.events_to_activation)
    .filter((n): n is number => n !== null && n > 0);
  const soonestUnlock =
    pendingUnlockEvents.length > 0 ? Math.min(...pendingUnlockEvents) : null;

  const visible =
    tab === "active" ? active : tab === "pending" ? pending : items;

  // Group visible items by tier for display
  const byTier: Record<string, ProtectionItem[]> = {};
  for (const p of visible) {
    (byTier[p.tier] ||= []).push(p);
  }

  return (
    <section className="rounded-lg border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-950">
      <header className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">
            Protections
          </h2>
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            {summary.active_count} active · {summary.applicable_count} available · {summary.total_count} total
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={
              "inline-flex items-center gap-1 text-xs " +
              (isRefreshing
                ? "text-neutral-500 dark:text-neutral-400"
                : "text-neutral-400 dark:text-neutral-500")
            }
            aria-live="polite"
          >
            <span
              className={
                "h-1.5 w-1.5 rounded-full " +
                (isRefreshing
                  ? "animate-pulse bg-sky-500"
                  : "bg-emerald-500/60")
              }
              aria-hidden
            />
            {isRefreshing ? "Updating…" : `Updated ${ageStr}`}
          </span>
          <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-medium text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300">
            profile: {agent_profile}
          </span>
        </div>
      </header>

      {/* gh-76 — unlock explainer. Visible whenever protections are still
          waiting to activate (i.e. low-event agents), so the customer reads
          the active/available gap as "warming up" rather than "less
          protected". Hides itself once everything applicable is active. */}
      {pending.length > 0 && (
        <div
          className="mb-4 rounded-md border border-sky-200 bg-sky-50 px-3 py-2.5 text-xs text-sky-800 dark:border-sky-900/50 dark:bg-sky-950/40 dark:text-sky-300"
          role="status"
        >
          <span className="font-semibold">
            {pending.length} more protection{pending.length === 1 ? "" : "s"} unlock
          </span>{" "}
          as this agent logs more events
          {soonestUnlock !== null && (
            <>
              {" "}— the next activates in {soonestUnlock} more event
              {soonestUnlock === 1 ? "" : "s"}
            </>
          )}
          . They aren&apos;t missing; each switches on automatically once
          we&apos;ve observed enough of your agent&apos;s behavior.
        </div>
      )}

      {/* Tab switcher */}
      <div className="mb-4 flex gap-1 rounded-md bg-neutral-100 p-1 text-xs dark:bg-neutral-900" role="tablist">
        <TabButton current={tab} value="active" onClick={setTab}>
          Active ({active.length})
        </TabButton>
        <TabButton current={tab} value="pending" onClick={setTab}>
          Coming ({pending.length})
        </TabButton>
        <TabButton current={tab} value="all" onClick={setTab}>
          All ({items.length})
        </TabButton>
      </div>

      {/* Empty states */}
      {visible.length === 0 && (
        <p className="rounded-md bg-neutral-50 px-3 py-4 text-sm text-neutral-500 dark:bg-neutral-900 dark:text-neutral-400">
          {tab === "active"
            ? "No protections active yet — start sending events through your integration."
            : tab === "pending"
              ? "Every applicable protection has already activated for this agent."
              : "No protections listed."}
        </p>
      )}

      {/* Render by tier */}
      <div className="space-y-4">
        {TIER_ORDER.filter((t) => byTier[t]?.length).map((t) => (
          <div key={t}>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-500">
              {TIER_LABELS[t]}
            </h3>
            <ul className="divide-y divide-neutral-200 rounded-md border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800">
              {byTier[t].map((p) => (
                <ProtectionRow
                  key={p.id}
                  protection={p}
                  expanded={expandedId === p.id}
                  onToggle={() =>
                    setExpandedId((cur) => (cur === p.id ? null : p.id))
                  }
                />
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* Footer: not-applicable summary */}
      {notApplicable.length > 0 && tab !== "all" && (
        <p className="mt-4 border-t border-neutral-200 pt-3 text-xs text-neutral-500 dark:border-neutral-800 dark:text-neutral-400">
          {notApplicable.length}{" "}
          {notApplicable.length === 1 ? "protection" : "protections"} require
          extra setup (watcher, mesh pairing, etc.). View all to see them.
        </p>
      )}
    </section>
  );
}

function TabButton({
  current,
  value,
  onClick,
  children,
}: {
  current: Tab;
  value: Tab;
  onClick: (v: Tab) => void;
  children: React.ReactNode;
}) {
  const isActive = current === value;
  return (
    <button
      type="button"
      role="tab"
      aria-selected={isActive}
      onClick={() => onClick(value)}
      className={
        "flex-1 rounded-md px-3 py-1.5 font-medium transition " +
        (isActive
          ? "bg-white text-neutral-900 shadow-sm dark:bg-neutral-800 dark:text-neutral-100"
          : "text-neutral-600 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-100")
      }
    >
      {children}
    </button>
  );
}

function ProtectionRow({
  protection,
  expanded,
  onToggle,
}: {
  protection: ProtectionItem;
  expanded: boolean;
  onToggle: () => void;
}) {
  // gh-79 — "behavior_gated" is a distinct state: the protection is in the
  // catalog and visible, but an equivalent variant covers this agent's
  // detected behavior mode instead, so it has no activation countdown.
  const status = protection.active
    ? "active"
    : protection.applies_to_behavior === false
      ? "behavior_gated"
      : protection.applicable
        ? "pending"
        : "not_applicable";

  const icon =
    status === "active"
      ? "✓"
      : status === "pending"
        ? "⏳"
        : status === "behavior_gated"
          ? "≈"
          : "—";
  const iconColor =
    status === "active"
      ? "text-emerald-600 dark:text-emerald-400"
      : status === "pending"
        ? "text-amber-600 dark:text-amber-400"
        : status === "behavior_gated"
          ? "text-sky-600 dark:text-sky-400"
          : "text-neutral-400 dark:text-neutral-600";

  // Native HTML tooltip: customers see the description on hover without
  // having to click the row. UX-5.15.J Fix 3b — Andrea told us protection
  // names alone are too cryptic; the description is what answers "what
  // attack does this catch?" but used to be one click away.
  const hoverTitle =
    protection.description +
    (protection.caveat ? `\n\nNote: ${protection.caveat}` : "") +
    (protection.behavior_note ? `\n\n${protection.behavior_note}` : "");
  return (
    <li>
      <button
        type="button"
        onClick={onToggle}
        title={hoverTitle}
        className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-neutral-50 dark:hover:bg-neutral-900"
        aria-expanded={expanded}
      >
        <span className={"shrink-0 text-lg leading-none " + iconColor}>{icon}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-sm font-medium text-neutral-900 dark:text-neutral-100">
              {protection.name}
            </span>
            {status === "pending" && protection.events_to_activation !== null && (
              <span className="text-xs text-amber-700 dark:text-amber-400">
                {protection.events_to_activation} more event{protection.events_to_activation === 1 ? "" : "s"}
              </span>
            )}
            {status === "behavior_gated" && (
              <span className="text-xs text-sky-700 dark:text-sky-400">
                covered by variant
              </span>
            )}
            {status === "not_applicable" && (
              <span className="text-xs text-neutral-500 dark:text-neutral-500">
                requires setup
              </span>
            )}
          </div>
          {!expanded && protection.behavior_note && (
            <p className="mt-1 text-xs italic text-sky-700 dark:text-sky-400">
              {protection.behavior_note}
            </p>
          )}
          {!expanded && !protection.behavior_note && protection.caveat && (
            <p className="mt-1 text-xs italic text-neutral-500 dark:text-neutral-500">
              {protection.caveat}
            </p>
          )}
          {expanded && (
            <div className="mt-2 space-y-2">
              <p className="text-sm text-neutral-700 dark:text-neutral-300">
                {protection.description}
              </p>
              {protection.behavior_note && (
                <p className="rounded-md bg-sky-50 px-3 py-2 text-xs text-sky-800 dark:bg-sky-950/40 dark:text-sky-300">
                  <strong className="font-semibold">Your agent:</strong>{" "}
                  {protection.behavior_note}
                </p>
              )}
              {protection.caveat && (
                <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
                  <strong className="font-semibold">Note:</strong>{" "}
                  {protection.caveat}
                </p>
              )}
            </div>
          )}
        </div>
        <span
          className={
            "shrink-0 text-xs text-neutral-400 transition-transform " +
            (expanded ? "rotate-180" : "")
          }
          aria-hidden
        >
          ▾
        </span>
      </button>
    </li>
  );
}

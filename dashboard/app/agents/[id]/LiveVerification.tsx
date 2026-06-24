"use client";

/**
 * LiveVerification — Sprint UX-5.5d (#627).
 *
 * The "step 4" of the onboarding wizard from
 * PRODUCT-EXPERIENCE-V2.md §7. Shown on the agent-detail page right
 * after creation while event_count is still 0. Polls the dashboard's
 * own /api/agents/[id] proxy every few seconds. When the first event
 * arrives, the component flips to a success state and refreshes the
 * page so the regular Calma state takes over.
 *
 * Why this exists: in the previous flow the user created an agent,
 * configured an MCP / watcher in another tab, and came back to a
 * silent dashboard with no signal that the integration worked. This
 * removes that ambiguity — the screen tells you live whether the
 * agent is talking to Metalins yet.
 *
 * Polling cadence: 4s for the first 30 seconds, 8s after that. Stops
 * after 5 minutes — if no events arrived by then, we show a "still
 * waiting" message with troubleshooting links instead of polling
 * forever.
 */
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Loader2 } from "lucide-react";
import Link from "next/link";

interface Props {
  agentId: string;
  /** event_count from the server snapshot. If non-zero we hide ourselves. */
  initialEventCount: number;
  /** /watchers, /mcp etc — where the user just came from. */
  surface: "watcher" | "mcp" | "sdk" | "none";
}

const FAST_INTERVAL_MS = 4_000;
const SLOW_INTERVAL_MS = 8_000;
const FAST_PHASE_MS = 30_000;
const GIVE_UP_MS = 5 * 60_000;

export function LiveVerification({
  agentId,
  initialEventCount,
  surface,
}: Props) {
  const router = useRouter();
  const [eventCount, setEventCount] = useState(initialEventCount);
  const [tickStartedAt] = useState(() => Date.now());
  const [givenUp, setGivenUp] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // No point polling if we already have events.
    if (eventCount > 0) return;

    let cancelled = false;

    async function tick() {
      try {
        const res = await fetch(
          `/api/agents/${encodeURIComponent(agentId)}`,
          { cache: "no-store" },
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = await res.json();
        const n = typeof body?.event_count === "number" ? body.event_count : 0;
        if (cancelled) return;
        if (n > 0) {
          setEventCount(n);
          // Give the user a beat to read the success state, then let
          // the server component re-render with full agent context.
          setTimeout(() => {
            if (!cancelled) router.refresh();
          }, 1500);
          return;
        }
      } catch {
        // Swallow transient errors — next tick will retry.
      }

      const elapsed = Date.now() - tickStartedAt;
      if (elapsed > GIVE_UP_MS) {
        if (!cancelled) setGivenUp(true);
        return;
      }
      const interval =
        elapsed < FAST_PHASE_MS ? FAST_INTERVAL_MS : SLOW_INTERVAL_MS;
      timerRef.current = setTimeout(tick, interval);
    }

    timerRef.current = setTimeout(tick, FAST_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    };
  }, [agentId, eventCount, tickStartedAt, router]);

  if (eventCount > 0) {
    return (
      <section
        className="rounded-2xl border border-emerald-500/40 bg-emerald-500/[0.06] p-6"
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
              First activity received.
            </h2>
            <p className="mt-1.5 text-sm text-muted-foreground">
              Your agent is talking to Drift Engine. We&apos;ll start
              verifying its identity now &mdash; refreshing&hellip;
            </p>
          </div>
        </div>
      </section>
    );
  }

  const helpHref =
    surface === "watcher"
      ? `/agents/${encodeURIComponent(agentId)}/watchers`
      : surface === "mcp"
        ? `/agents/${encodeURIComponent(agentId)}/mcp`
        : `/agents/${encodeURIComponent(agentId)}/connect`;
  const helpLabel =
    surface === "watcher"
      ? "Recheck bot setup"
      : surface === "mcp"
        ? "Recheck MCP setup"
        : "Pick an integration";

  return (
    <section
      className="rounded-2xl border bg-card p-6"
      aria-live="polite"
    >
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
              : "Waiting for first activity…"}
          </h2>
          <p className="mt-1.5 text-sm text-muted-foreground">
            {givenUp ? (
              <>
                We haven&apos;t seen any events from this agent yet. The
                integration may not be wired up correctly &mdash; try
                rechecking the setup, or send any message / action from
                your agent so we have something to look at.
              </>
            ) : surface === "mcp" ? (
              <>
                Make a call from your AI editor (Claude Code, Cursor,
                Claude Desktop) and we&apos;ll detect it within seconds.
              </>
            ) : surface === "watcher" ? (
              <>
                Send a message from your bot &mdash; we poll the
                platform every few seconds and will pick it up
                automatically.
              </>
            ) : (
              <>
                Pick how this agent connects &mdash; the HTTP API / SDK,
                MCP, or a public-bot watcher &mdash; then send any event
                from your agent.
              </>
            )}
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link
              href={helpHref}
              className="rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-accent"
            >
              {helpLabel}
            </Link>
            <Link
              href="/drift-engine/docs"
              className="rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-accent"
            >
              How verification works
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

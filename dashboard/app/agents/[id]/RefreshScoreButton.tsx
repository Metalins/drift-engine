"use client";

/**
 * RefreshScoreButton — on-demand Identity Confidence recompute. Sprint 6.
 *
 * The hourly batch job is unreliable on Cloud Run scale-to-zero (and resets
 * every deploy), so a brand-new agent can sit at "no data" for up to 60
 * minutes. This button gives the user instant feedback after their first
 * activity.
 *
 * UX:
 *   - Disabled if event_count === 0 (nothing to compute over).
 *   - On click → POSTs to /api/agents/[id]/recompute.
 *   - Server enforces a 60s cooldown; if 429, we surface "Wait Xs" and
 *     re-enable after that. If 412 ("no events"), we surface a hint.
 *   - On success → router.refresh() to re-render the page with the new
 *     snapshot data.
 */
import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";

interface Props {
  agentId: string;
  eventCount: number;
}

type Status =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "cooldown"; until: number; message: string }
  | { kind: "no-events" }
  | { kind: "error"; message: string };

export function RefreshScoreButton({ agentId, eventCount }: Props) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [cooldownLeft, setCooldownLeft] = useState<number>(0);

  // Tick the visible cooldown countdown every second.
  useEffect(() => {
    if (status.kind !== "cooldown") return;
    const id = setInterval(() => {
      const left = Math.max(0, Math.ceil((status.until - Date.now()) / 1000));
      setCooldownLeft(left);
      if (left === 0) setStatus({ kind: "idle" });
    }, 1000);
    return () => clearInterval(id);
  }, [status]);

  const noEvents = eventCount === 0;
  const busy = pending || status.kind === "running";
  const cooling = status.kind === "cooldown";
  const disabled = busy || cooling || noEvents;

  async function handleClick() {
    if (disabled) return;
    setStatus({ kind: "running" });
    try {
      const res = await fetch(`/api/agents/${encodeURIComponent(agentId)}/recompute`, {
        method: "POST",
      });
      if (res.status === 429) {
        // Pull the retry seconds out of the body; fall back to 60.
        const body = await res.json().catch(() => ({}));
        const match = String(body?.detail ?? "").match(/(\d+)\s*s/);
        const seconds = match ? Number(match[1]) : 60;
        const until = Date.now() + seconds * 1000;
        setCooldownLeft(seconds);
        setStatus({
          kind: "cooldown",
          until,
          message: `Wait ${seconds}s before recomputing again`,
        });
        return;
      }
      if (res.status === 412) {
        setStatus({ kind: "no-events" });
        return;
      }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail ?? `HTTP ${res.status}`);
      }
      // Success — server already wrote the new snapshot. Refresh the page so
      // the server component re-fetches and the gauge updates.
      startTransition(() => {
        router.refresh();
      });
      // Arm a client-side cooldown so the user can't immediately re-click.
      const until = Date.now() + 60_000;
      setCooldownLeft(60);
      setStatus({
        kind: "cooldown",
        until,
        message: "Refreshed. You can refresh again in 60s.",
      });
    } catch (err) {
      setStatus({
        kind: "error",
        message: err instanceof Error ? err.message : "Unknown error",
      });
    }
  }

  let label: string;
  let hint: string | null = null;
  if (noEvents) {
    label = "Refresh score";
    hint = "Send activity to your agent first.";
  } else if (status.kind === "running") {
    label = "Computing...";
  } else if (cooling) {
    label = `Wait ${cooldownLeft}s`;
    hint = status.kind === "cooldown" ? status.message : null;
  } else if (status.kind === "no-events") {
    label = "Refresh score";
    hint = "No events in the current window. Try again later.";
  } else if (status.kind === "error") {
    label = "Refresh score";
    hint = status.message;
  } else {
    label = "Refresh score";
  }

  return (
    <div className="mt-3 flex flex-col items-center gap-1">
      <button
        type="button"
        onClick={handleClick}
        disabled={disabled}
        className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
      >
        <RefreshCw size={14} className={busy ? "animate-spin" : ""} />
        {label}
      </button>
      {hint && (
        <p className="text-center text-[11px] text-muted-foreground">{hint}</p>
      )}
      <p className="text-center text-[10px] text-muted-foreground/70">
        Auto-refreshes every hour
      </p>
    </div>
  );
}

/**
 * TrustStrip — compact two-layer trust indicator for the dashboard list.
 *
 * Sprint UX-5.12 (TWO-LAYER-TRUST-DESIGN.md §7.1). Each agent row gets a
 * single-line strip that summarizes both layers without claiming a
 * combined score:
 *
 *   ● Verified  ◐ Baseline 16%
 *
 * Tiny enough to fit in a list row, honest enough that "verified" never
 * appears when the cryptographic state isn't actually verified.
 */
import type {
  BehavioralState,
  CryptographicState,
  TrustBlock,
} from "@/lib/api";
import { displayCryptoStatus } from "@/lib/display-messages";
import { cn } from "@/lib/utils";

interface Props {
  trust: TrustBlock | undefined;
  className?: string;
}

export function TrustStrip({ trust, className }: Props) {
  const crypto = trust?.cryptographic.state ?? "unverified";
  const behavior = trust?.behavioral.state ?? "not_enough_data";
  const observed = trust?.behavioral.events_observed ?? 0;
  const floor = trust?.behavioral.events_floor ?? 2000;
  const stable = trust?.behavioral.events_stable ?? 5000;
  const target = behavior === "not_enough_data" ? floor : stable;
  const pct = Math.min(100, Math.round((observed / target) * 100));

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-1 text-xs",
        className,
      )}
    >
      <span className="inline-flex items-center gap-1.5">
        <span
          className={cn(
            "inline-block h-2 w-2 shrink-0 rounded-full",
            cryptoDotFor(crypto),
          )}
          aria-hidden="true"
        />
        <span className={cn("font-medium", cryptoTextFor(crypto))}>
          {displayCryptoStatus(crypto)}
        </span>
      </span>
      <span className="inline-flex items-center gap-1.5 text-muted-foreground">
        <span
          className={cn(
            "inline-block h-2 w-2 shrink-0 rounded-full",
            behavioralDotFor(behavior),
          )}
          aria-hidden="true"
        />
        <span className={cn("font-medium", behavioralTextFor(behavior))}>
          {behavioralCompactLabelFor(behavior, pct)}
        </span>
      </span>
    </div>
  );
}

function cryptoDotFor(state: CryptographicState): string {
  switch (state) {
    case "verified":
      return "bg-emerald-500";
    case "unverified":
      return "bg-muted-foreground/60";
    case "caution":
      return "bg-amber-500";
    case "action_required":
      return "bg-destructive";
    case "revoked":
      return "bg-destructive";
  }
}

function cryptoTextFor(state: CryptographicState): string {
  switch (state) {
    case "verified":
      return "text-emerald-700 dark:text-emerald-400";
    case "unverified":
      return "text-muted-foreground";
    case "caution":
      return "text-amber-700 dark:text-amber-400";
    case "action_required":
      return "text-destructive";
    case "revoked":
      return "text-destructive";
  }
}

function behavioralCompactLabelFor(
  state: BehavioralState,
  pct: number,
): string {
  switch (state) {
    case "not_enough_data":
      return `Baseline ${pct}%`;
    case "building":
      return `Baseline ${pct}%`;
    case "stable":
      return "Consistent";
    case "drift_detected":
      return "Drift";
  }
}

function behavioralDotFor(state: BehavioralState): string {
  switch (state) {
    case "not_enough_data":
      return "bg-muted-foreground/40";
    case "building":
      return "bg-sky-500";
    case "stable":
      return "bg-emerald-500";
    case "drift_detected":
      return "bg-amber-500";
  }
}

function behavioralTextFor(state: BehavioralState): string {
  switch (state) {
    case "not_enough_data":
      return "text-muted-foreground";
    case "building":
      return "text-sky-700 dark:text-sky-400";
    case "stable":
      return "text-emerald-700 dark:text-emerald-400";
    case "drift_detected":
      return "text-amber-700 dark:text-amber-400";
  }
}

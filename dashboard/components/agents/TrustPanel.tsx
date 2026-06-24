/**
 * TrustPanel — agent detail two-layer trust view.
 *
 * Sprint UX-5.12 (TWO-LAYER-TRUST-DESIGN.md §7.2): the logged-in customer
 * detail page replaces the old single ConfidenceGauge with two
 * independent blocks that mirror what a third party sees on the public
 * verify page — they never compose into one verdict.
 *
 *   ● Cryptographic identity — binary, immediate. Driven by signed
 *     events + MVS probes. Available from event #1. The headline state.
 *
 *   ◐ Behavioral baseline — gradual, sample-size aware. Refuses to
 *     make claims below `events_floor` events. Surfaces drift only
 *     after stabilizing.
 *
 * Per D-PROD.18 no internal observable names (ICR/TWC/TTM/MVS) appear in
 * the customer copy. Only the layer name + state label + plain-language
 * detail string.
 */
import {
  Activity,
  Hourglass,
  Shield,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  TrendingUp,
} from "lucide-react";
import type {
  BehavioralState,
  CryptographicState,
  TrustBlock,
} from "@/lib/api";
import { displayBehavioralStatus } from "@/lib/display-messages";
import { cn } from "@/lib/utils";

interface Props {
  trust: TrustBlock;
  className?: string;
}

export function TrustPanel({ trust, className }: Props) {
  return (
    <div className={cn("space-y-3", className)}>
      <CryptographicRow layer={trust.cryptographic} />
      <BehavioralRow layer={trust.behavioral} />
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Layer 1                                                                     //
// --------------------------------------------------------------------------- //

function CryptographicRow({ layer }: { layer: TrustBlock["cryptographic"] }) {
  const state = layer?.state ?? "unverified";
  const accent = cryptoAccentFor(state);
  const Icon = cryptoIconFor(state);
  return (
    <div className={`flex items-start gap-3 rounded-lg border p-4 ${accent.bg}`}>
      <div
        className={`mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${accent.iconBg}`}
      >
        <Icon size={18} aria-hidden="true" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Cryptographic identity
        </div>
        <div className="mt-1 text-base">
          <span className={`font-semibold ${accent.text}`}>
            {cryptoLabelFor(state)}
          </span>
          <span className="text-sm text-muted-foreground">
            {" "}
            — {cryptoDetailFor(state, layer?.since ?? null, layer?.last_probe_at ?? null)}
          </span>
        </div>
      </div>
    </div>
  );
}

function cryptoIconFor(state: CryptographicState) {
  switch (state) {
    case "verified":
      return ShieldCheck;
    case "unverified":
      return Shield;
    case "caution":
      return ShieldAlert;
    case "action_required":
      return ShieldAlert;
    case "revoked":
      return ShieldOff;
  }
}

function cryptoLabelFor(state: CryptographicState): string {
  switch (state) {
    case "verified":
      return "Verified";
    case "unverified":
      return "Setting up";
    case "caution":
      return "Verify with care";
    case "action_required":
      return "Not trusted";
    case "revoked":
      return "Revoked";
  }
}

function cryptoDetailFor(
  state: CryptographicState,
  since: string | null,
  lastProbeAt: string | null,
): string {
  const sinceText = since
    ? ` since ${new Date(since).toLocaleDateString(undefined, {
        year: "numeric",
        month: "long",
        day: "numeric",
      })}`
    : "";
  const probeText = lastProbeAt
    ? ` Last probe ${shortDate(lastProbeAt)}.`
    : "";
  switch (state) {
    case "verified":
      return `signed events match this identity${sinceText}.${probeText}`;
    case "unverified":
      return `we're still establishing this agent's identity from its first events.${probeText}`;
    case "caution":
      return `a recent check flagged something.${probeText}`;
    case "action_required":
      return `cryptographic checks are failing — treat as compromised.${probeText}`;
    case "revoked":
      return "the owner revoked this identity.";
  }
}

function cryptoAccentFor(state: CryptographicState) {
  switch (state) {
    case "verified":
      return {
        bg: "border-emerald-500/30 bg-emerald-500/[0.04]",
        iconBg: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
        text: "text-emerald-700 dark:text-emerald-400",
      };
    case "unverified":
      return {
        bg: "bg-card",
        iconBg: "bg-muted text-muted-foreground",
        text: "text-foreground",
      };
    case "caution":
      return {
        bg: "border-amber-500/40 bg-amber-500/[0.05]",
        iconBg: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
        text: "text-amber-700 dark:text-amber-400",
      };
    case "action_required":
      return {
        bg: "border-destructive/30 bg-destructive/[0.06]",
        iconBg: "bg-destructive/15 text-destructive",
        text: "text-destructive",
      };
    case "revoked":
      return {
        bg: "border-destructive/30 bg-destructive/[0.06]",
        iconBg: "bg-destructive/15 text-destructive",
        text: "text-destructive",
      };
  }
}

// --------------------------------------------------------------------------- //
// Layer 2                                                                     //
// --------------------------------------------------------------------------- //

function BehavioralRow({ layer }: { layer: TrustBlock["behavioral"] }) {
  const state: BehavioralState = layer?.state ?? "not_enough_data";
  const observed = layer?.events_observed ?? 0;
  const floor = layer?.events_floor ?? 2000;
  const stable = layer?.events_stable ?? 5000;
  const accent = behavioralAccentFor(state);
  const Icon = behavioralIconFor(state);
  const target = state === "not_enough_data" ? floor : stable;
  const pct = Math.min(100, Math.round((observed / target) * 100));

  return (
    <div className={`flex items-start gap-3 rounded-lg border p-4 ${accent.bg}`}>
      <div
        className={`mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${accent.iconBg}`}
      >
        <Icon size={18} aria-hidden="true" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Behavior pattern
        </div>
        <div className="mt-1 text-base">
          <span className={`font-semibold ${accent.text}`}>
            {behavioralLabelFor(state)}
          </span>
          <span className="text-sm text-muted-foreground">
            {" "}
            — {behavioralDetailFor(state, observed, floor, stable)}
          </span>
        </div>
        <div
          className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted"
          aria-hidden="true"
        >
          <div
            className={`h-full ${accent.bar}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
    </div>
  );
}

function behavioralIconFor(state: BehavioralState) {
  switch (state) {
    case "not_enough_data":
      return Hourglass;
    case "building":
      return Hourglass;
    case "stable":
      return Activity;
    case "drift_detected":
      return TrendingUp;
  }
}

function behavioralLabelFor(state: BehavioralState): string {
  return displayBehavioralStatus(state);
}

function behavioralDetailFor(
  state: BehavioralState,
  observed: number,
  floor: number,
  stable: number,
): string {
  // Sprint UX-5.15.I (task #849) — IP protection: floor + stable
  // thresholds are calibration numbers and stay internal. The bar
  // is still driven by the ratio (rendered visually) but the copy
  // doesn't name the target.
  void floor;
  void stable;
  const obs = observed.toLocaleString();
  switch (state) {
    case "not_enough_data":
      return `${obs} events observed so far. The behavior signal kicks in once we have enough activity.`;
    case "building":
      return `${obs} events observed so far. Behavior is consistent, and the pattern is still settling.`;
    case "stable":
      return `${obs}+ events observed. Behavior is consistent with the pattern we learned.`;
    case "drift_detected":
      return `${obs}+ events observed. Recent activity diverges from the pattern we learned.`;
  }
}

function behavioralAccentFor(state: BehavioralState) {
  switch (state) {
    case "not_enough_data":
      return {
        bg: "bg-card",
        iconBg: "bg-muted text-muted-foreground",
        text: "text-muted-foreground",
        bar: "bg-muted-foreground/50",
      };
    case "building":
      return {
        bg: "border-sky-500/30 bg-sky-500/[0.04]",
        iconBg: "bg-sky-500/15 text-sky-600 dark:text-sky-400",
        text: "text-sky-700 dark:text-sky-400",
        bar: "bg-sky-500/70",
      };
    case "stable":
      return {
        bg: "border-emerald-500/30 bg-emerald-500/[0.04]",
        iconBg: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
        text: "text-emerald-700 dark:text-emerald-400",
        bar: "bg-emerald-500/70",
      };
    case "drift_detected":
      return {
        bg: "border-amber-500/40 bg-amber-500/[0.05]",
        iconBg: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
        text: "text-amber-700 dark:text-amber-400",
        bar: "bg-amber-500/70",
      };
  }
}

// --------------------------------------------------------------------------- //
// Helpers                                                                     //
// --------------------------------------------------------------------------- //

function shortDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

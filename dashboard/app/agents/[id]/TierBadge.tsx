import Link from "next/link";
import type { TierInfo } from "@/lib/api";

/**
 * Sprint UX-5.15.A — TierBadge on the panel header.
 *
 * The tier is derived server-side (verification_state.derive_tier) — a pure
 * event-count derivation against the UX-5.16 calibrated floors. This
 * component just renders the `tier` block the API returns.
 *
 * The earlier client-side derivation (off the protections checklist) was
 * retired: it computed the tier from the cosmetic per-protection `tier`
 * field with an "every protection in the bucket active" rule, which broke
 * as soon as slow protections (e.g. the ~3500-event partial-protocol
 * check) were added to the catalog.
 *
 * Per the doc rector (IDENTITY-TIERS-AND-COMMUNICATION.md §6 Step C) the
 * badge clicks into /docs/concepts/tiers.
 */
const TIER_META: Record<string, { label: string; tint: string }> = {
  T0: {
    label: "T0 — Registered",
    tint: "border-neutral-300 bg-neutral-100 text-neutral-700 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-200",
  },
  T1: {
    label: "T1 — Early signals",
    tint: "border-amber-400/40 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-950/40 dark:text-amber-200",
  },
  T2: {
    label: "T2 — Standard",
    tint: "border-sky-400/40 bg-sky-50 text-sky-800 dark:border-sky-500/30 dark:bg-sky-950/40 dark:text-sky-200",
  },
  T3: {
    label: "T3 — Full coverage",
    tint: "border-emerald-500/40 bg-emerald-50 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-950/40 dark:text-emerald-200",
  },
  T4: {
    label: "T4 — Mesh corroboration",
    tint: "border-violet-500/40 bg-violet-50 text-violet-800 dark:border-violet-500/30 dark:bg-violet-950/40 dark:text-violet-200",
  },
};

export function TierBadge({ tier }: { tier: TierInfo | undefined }) {
  if (!tier) return null;
  const meta = TIER_META[tier.tier];
  if (!meta) return null;
  return (
    <Link
      href="/drift-engine/docs/concepts/tiers"
      title={tier.name}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium transition hover:opacity-80 ${meta.tint}`}
    >
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current opacity-60" />
      {meta.label}
    </Link>
  );
}

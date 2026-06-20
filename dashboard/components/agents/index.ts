/**
 * Barrel for agent-domain components.
 *
 * Sprint 5 (2026-05-14) pivot: ObservableCard + EventsTable were removed
 * from the customer-facing UI because they exposed internal observables
 * (ICR / TWC / TTM / β-Crooks) — the proprietary algorithm. Their files
 * are tombstoned but kept in the tree; the exports below intentionally
 * don't re-expose them.
 *
 * Sprint UX-5.12 — ConfidenceGauge is no longer exported. It rendered
 * the single-number `identity_confidence` which was vulnerable to
 * finite-sample MI bias (Exp-CvD). The two-layer model replaces it:
 *   • TrustPanel — full breakdown on the agent detail page.
 *   • TrustStrip — compact one-liner for the dashboard list row.
 * The file stays in the tree as a tombstone in case we resurrect it
 * for an internal-only view later.
 */
export { CollapsedSection } from "./CollapsedSection";
export { MVSHistoryTimeline } from "./MVSHistoryTimeline";
export { PendingProbesPanel } from "./PendingProbesPanel";
export { ScoreFactors } from "./ScoreFactors";
export { TrustPanel } from "./TrustPanel";
export { TrustStrip } from "./TrustStrip";

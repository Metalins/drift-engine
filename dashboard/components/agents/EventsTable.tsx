/**
 * EventsTable — TOMBSTONED Sprint 5 (2026-05-14).
 *
 * Originally rendered a per-window table of Trinity observables
 * (ICR / TWC / TTM / β-Crooks) alongside Identity Confidence. The pivot
 * to closed algorithm removed it from `/agents/[id]`. The barrel
 * (`./index.ts`) no longer re-exports this module. Kept as a tombstone
 * so the git history points at one canonical removal commit instead of
 * a deleted file.
 *
 * If we ever revisit power-user views (Settings → Advanced metrics),
 * `git log -- components/agents/EventsTable.tsx` shows the full
 * implementation in history.
 */
export {};

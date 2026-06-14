-- Migration: gh-77 — auto-detected agent behavior mode.
--
-- Adds `agents.detected_behavior_mode`. The customer no longer DECLARES a
-- behavior profile at registration (that was a leaky abstraction — see
-- gh-77). The engine observes each agent's first events and decides whether
-- it behaves deterministically (same input → same output) or stochastically
-- (samples freely). This column stores that verdict.
--
-- Values: 'unknown' (default) | 'deterministic' | 'stochastic'.
-- Consumed by app.services.protections_catalog.resolve_agent_profile to gate
-- which protections apply. Detection logic: app.services.behavior_detection.
--
-- Idempotent. Apply on Supabase prod (project ehhxyivzxibinubkzwlb).
-- Dev/SQLite gets the column via Base.metadata.create_all; prod uses this.
--
-- Existing rows: the NOT NULL + DEFAULT 'unknown' backfills every current
-- agent to 'unknown'; their mode is then detected naturally as new events
-- arrive (or stays 'unknown', which resolves to the deterministic default).

ALTER TABLE agents
  ADD COLUMN IF NOT EXISTS detected_behavior_mode TEXT NOT NULL DEFAULT 'unknown';

COMMENT ON COLUMN agents.detected_behavior_mode IS
  'gh-77 server-detected behavior mode: unknown | deterministic | '
  'stochastic. Replaces the removed customer-declared agent_profile. '
  'Detected from event_logs input/output reproducibility + behavioral '
  'features; gates protections via resolve_agent_profile.';

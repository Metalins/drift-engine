-- Migration: Issue #62 — κ-engine V2 behavioral baseline table.
--
-- Adds the `agent_baseline` table that stores each agent's learned
-- behavioral distribution (computed over recent event_logs behavioral
-- metadata from #63). One row per agent; recomputed periodically.
--
-- Idempotent. Apply on Supabase prod (project ehhxyivzxibinubkzwlb).
-- Dev/SQLite gets the table via Base.metadata.create_all; prod uses this.

CREATE TABLE IF NOT EXISTS agent_baseline (
  agent_id      TEXT      PRIMARY KEY REFERENCES agents(id),
  features_json JSONB     NOT NULL DEFAULT '{}'::jsonb,
  n_events      INTEGER   NOT NULL DEFAULT 0,
  computed_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE agent_baseline IS
  'κ-engine V2 (#62) per-agent behavioral baseline: per-feature '
  'distributions (continuous samples + percentiles, categorical '
  'frequencies, tool name/bigram distribution, LSH fingerprint set) '
  'computed from event_logs.metadata_json[''behavioral'']. Compared '
  'against a fresh traffic window to detect drift.';

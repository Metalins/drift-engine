-- Sprint 7 / TLS (paper §8.3, R11-A) — time-locked memory probes.
--
-- Adds two nullable columns to `memory_probes`:
--   history_digest_at_issue: server's recorded digest chain value at the
--     moment the probe was issued. Both server and agent derive the
--     valid response window deterministically from these bytes.
--   response_counter: the agent's `event_count` at the moment of crafting
--     the proof. Must fall inside the window for the TLS check to pass.
--
-- Both are nullable so legacy rows survive. New probes are populated by
-- memory_verifier.issue_probe; new respond_probe payloads are populated
-- when agents include the optional `response_counter` field.
--
-- Safe to re-run (`IF NOT EXISTS`).
ALTER TABLE memory_probes
  ADD COLUMN IF NOT EXISTS history_digest_at_issue TEXT NULL;

ALTER TABLE memory_probes
  ADD COLUMN IF NOT EXISTS response_counter INTEGER NULL;

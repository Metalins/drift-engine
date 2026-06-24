-- Sprint 7 / ADV (paper §8.6, R12) — adversarial probe detection.
--
-- Adds two columns to `memory_probes`:
--   is_malformed: boolean, default false. Set true when the server
--     deliberately mints a probe with a malformed payload (truncated
--     nonce, out-of-range target_event_count) to test whether the
--     agent's protocol implementation detects and refuses.
--   refusal_reason: nullable text. Populated when the agent calls
--     respond_probe with a refusal sentinel (no agent_proof). The
--     specific reason string is a tag like "short_nonce" or
--     "event_count_out_of_range".
--
-- Idempotent. Existing rows default to is_malformed=false; legit probes.
ALTER TABLE memory_probes
  ADD COLUMN IF NOT EXISTS is_malformed BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE memory_probes
  ADD COLUMN IF NOT EXISTS refusal_reason TEXT NULL;

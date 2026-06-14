-- Sprint 7 / PRS (paper §8.1, R10-D) — Predictive Reliability Score.
--
-- Agents pre-commit to a distribution over their next response K events
-- in the future. When the target event happens, the server resolves the
-- prediction by checking whether the realized response bucket landed in
-- the top-K of the predicted distribution. PRS = fraction of resolved
-- predictions that hit.
--
-- Schema notes:
--   submitted_at_event_count: the agent's `event_count` when the
--     prediction was submitted (the "now").
--   target_event_count: submitted_at_event_count + K_OFFSET (default 5).
--   predicted_distribution: JSON array of floats, sums to ~1.0, length
--     = DEFAULT_ALPHABET (32). Stored as JSONB for index-able queries
--     later if needed.
--   realized_response_bucket: filled when the target event arrives.
--   score: 1.0 if hit, 0.0 if miss; nullable until resolved.
--   resolved_at: timestamp of resolution.
--
-- Indexes: (agent_id, status) for fast batch resolution; status derived
-- from resolved_at being null/non-null.
--
-- Idempotent.
CREATE TABLE IF NOT EXISTS prediction_submissions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id),
    submitted_at_event_count INTEGER NOT NULL,
    target_event_count INTEGER NOT NULL,
    predicted_distribution JSONB NOT NULL,
    realized_response_bucket INTEGER NULL,
    score REAL NULL,
    submitted_at TIMESTAMP NOT NULL DEFAULT now(),
    resolved_at TIMESTAMP NULL
);

CREATE INDEX IF NOT EXISTS idx_predictions_agent_target
    ON prediction_submissions (agent_id, target_event_count);

CREATE INDEX IF NOT EXISTS idx_predictions_agent_resolved
    ON prediction_submissions (agent_id, resolved_at);

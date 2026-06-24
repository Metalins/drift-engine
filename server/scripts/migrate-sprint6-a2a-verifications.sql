-- Sprint 6-A2A 6.2 — verification_attempts table.
--
-- Append-only timeline of /v1/verify-proof calls. Distinct from the
-- existing `verifications` table (which records issuances/mints): this
-- table logs every CONSUMPTION of a proof by a relying party.
--
-- Privacy: no IP. Only timestamp + outcome + scope snapshot.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS verification_attempts (
    id TEXT PRIMARY KEY,
    proof_id TEXT NULL,
    agent_id TEXT NULL,
    verified_at TIMESTAMP NOT NULL DEFAULT now(),
    valid BOOLEAN NOT NULL,
    reason TEXT NULL,
    scope TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_verify_attempts_proof
    ON verification_attempts (proof_id);
CREATE INDEX IF NOT EXISTS idx_verify_attempts_agent_ts
    ON verification_attempts (agent_id, verified_at DESC);

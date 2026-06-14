-- Sprint 7 / MCS (paper §8.4, R11-B) — Multi-agent Corroboration Score.
--
-- Two of a customer's agents form a "mesh pair". Every CORROBORATION_INTERVAL
-- events each agent submits a co-signature over (state_self, state_partner):
--     co_sig = HMAC(agent_secret, state_self || state_partner)
-- The server pairs the two submissions for the same corroboration cycle,
-- verifies both signatures, and counts the pair as a valid corroboration
-- point. MCS = fraction of recent corroboration points that verified.
--
-- V1 scope (D-PROD.18): same-customer mesh only. Cross-customer mesh is V2.
--
-- Tables:
--   agent_mesh_pairs: (agent_a_id, agent_b_id) — bidirectional, stored
--     with canonical ordering (a < b lexicographically) so each pair has
--     a unique row regardless of which agent submitted first.
--   corroboration_points: one row per cycle per pair, populated as
--     submissions arrive. status moves pending → complete (both sides
--     arrived) or expired (window closed before both arrived).
--
-- Indexes target the read patterns: list pairs for an agent, lookup the
-- current pending point for a (pair, cycle).
--
-- Idempotent.
CREATE TABLE IF NOT EXISTS agent_mesh_pairs (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    agent_a_id TEXT NOT NULL REFERENCES agents(id),
    agent_b_id TEXT NOT NULL REFERENCES agents(id),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    paused_at TIMESTAMP NULL,
    CONSTRAINT mesh_pair_unique UNIQUE (agent_a_id, agent_b_id),
    CONSTRAINT mesh_pair_canonical CHECK (agent_a_id < agent_b_id),
    CONSTRAINT mesh_pair_distinct CHECK (agent_a_id <> agent_b_id)
);

CREATE INDEX IF NOT EXISTS idx_mesh_pairs_customer
    ON agent_mesh_pairs (customer_id);
CREATE INDEX IF NOT EXISTS idx_mesh_pairs_agent_a
    ON agent_mesh_pairs (agent_a_id);
CREATE INDEX IF NOT EXISTS idx_mesh_pairs_agent_b
    ON agent_mesh_pairs (agent_b_id);

CREATE TABLE IF NOT EXISTS corroboration_points (
    id TEXT PRIMARY KEY,
    mesh_pair_id TEXT NOT NULL REFERENCES agent_mesh_pairs(id),
    cycle INTEGER NOT NULL,
    a_state TEXT NULL,
    a_partner_state TEXT NULL,
    a_co_sig TEXT NULL,
    a_submitted_at TIMESTAMP NULL,
    b_state TEXT NULL,
    b_partner_state TEXT NULL,
    b_co_sig TEXT NULL,
    b_submitted_at TIMESTAMP NULL,
    verified BOOLEAN NULL,  -- NULL = pending, TRUE/FALSE after resolution
    resolved_at TIMESTAMP NULL,
    CONSTRAINT corroboration_unique UNIQUE (mesh_pair_id, cycle)
);

CREATE INDEX IF NOT EXISTS idx_corroboration_pair_resolved
    ON corroboration_points (mesh_pair_id, resolved_at);

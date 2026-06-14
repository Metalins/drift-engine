-- Sprint 7 / ZKH (paper §8.5, R12) — Zero-Knowledge History (Merkle variant).
--
-- The agent commits to a Merkle root over its full local history-digest
-- chain BEFORE the server picks the challenge index. The server, holding
-- its own copy of the chain via EventLog.history_digest values, can
-- verify both (a) the commit matches what the chain should produce and
-- (b) the agent can later open the path at a randomly-selected leaf.
--
-- V1 honest framing: in our threat model the I/O hashes are persisted
-- server-side and the digest chain is fully reconstructible from them,
-- so ZKH coverage overlaps significantly with MVS. The commit-before-
-- challenge framing remains useful: it lets us spot agents that lie
-- about their committed history root before granting the proof
-- opportunity. See docs/research/SECURITY-MECHANISMS-AUDIT.md §7.
--
-- Schema notes:
--   commit_root: agent's claimed Merkle root over (digest_at_1, ...,
--     digest_at_N). Hex sha256.
--   t_star: server-chosen 1-indexed event_count to challenge.
--   nonce: server-issued randomness mixed into the proof to defeat
--     replay (currently unused in the Merkle verifier itself; reserved
--     for future variants).
--   claimed_digest + merkle_path: agent's response. JSON path is a list
--     of {sibling: hex, side: "L"|"R"} entries from leaf to root.
--   server_root_at_issue: snapshot of the server's recomputed root at
--     the moment of issue, so we can audit later if the chain advances
--     during the round-trip.
--
-- Idempotent.
CREATE TABLE IF NOT EXISTS zkh_proofs (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id),
    commit_root TEXT NOT NULL,
    server_root_at_issue TEXT NOT NULL,
    t_star INTEGER NOT NULL,
    nonce TEXT NOT NULL,
    claimed_digest TEXT NULL,
    merkle_path JSONB NULL,
    verified BOOLEAN NULL,
    rejection_reason TEXT NULL,
    issued_at TIMESTAMP NOT NULL DEFAULT now(),
    submitted_at TIMESTAMP NULL,
    resolved_at TIMESTAMP NULL
);

CREATE INDEX IF NOT EXISTS idx_zkh_agent_resolved
    ON zkh_proofs (agent_id, resolved_at);
CREATE INDEX IF NOT EXISTS idx_zkh_agent_issued
    ON zkh_proofs (agent_id, issued_at);

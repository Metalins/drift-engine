-- Sprint UX-5.9-G (#656) — external identity anchors.
--
-- Adds the `agent_anchors` table. Used today for GitHub gist anchors;
-- the schema is forward-compat for "dns", "x", etc. Idempotent.
--
-- Apply on Supabase prod (project ehhxyivzxibinubkzwlb).

CREATE TABLE IF NOT EXISTS agent_anchors (
  id               TEXT      PRIMARY KEY,
  agent_id         TEXT      NOT NULL REFERENCES agents(id),
  type             TEXT      NOT NULL,
  method           TEXT      NOT NULL,
  value            TEXT      NULL,
  challenge_token  TEXT      NOT NULL,
  metadata_json    JSONB     NULL DEFAULT '{}'::jsonb,
  verified_at      TIMESTAMP NULL,
  last_check_at    TIMESTAMP NULL,
  created_at       TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_anchors_agent_type
  ON agent_anchors (agent_id, type);

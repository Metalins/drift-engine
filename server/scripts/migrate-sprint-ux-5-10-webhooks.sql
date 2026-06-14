-- Sprint UX-5.10-6 (#664) — webhook endpoints.
--
-- Adds the `webhook_endpoints` table for Diana's state-change alerts.
-- Idempotent. Apply on Supabase prod (project ehhxyivzxibinubkzwlb).

CREATE TABLE IF NOT EXISTS webhook_endpoints (
  id                    TEXT      PRIMARY KEY,
  agent_id              TEXT      NOT NULL REFERENCES agents(id),
  customer_id           TEXT      NOT NULL REFERENCES customers(id),
  url                   TEXT      NOT NULL,
  secret_hash           TEXT      NOT NULL,
  is_active             BOOLEAN   NOT NULL DEFAULT TRUE,
  last_delivery_at      TIMESTAMP NULL,
  last_delivery_status  INTEGER   NULL,
  last_delivery_error   TEXT      NULL,
  created_at            TIMESTAMP NOT NULL DEFAULT NOW(),
  deleted_at            TIMESTAMP NULL
);

CREATE INDEX IF NOT EXISTS idx_webhooks_agent_active
  ON webhook_endpoints (agent_id, is_active);

-- Full wipe of the testing@metalins.local sandbox tenant.
--
-- Sprint UX-5.14 F1 (2026-05-18). Replaces the pattern-based
-- cleanup-synthetic-tenant.sql. Runs at the START of every E2E
-- suite run to leave the sandbox idempotent + identical from one
-- run to the next.
--
-- Preserved (so the suite doesn't have to re-do account creation):
--   • auth.users row for testing@metalins.local
--   • customers row for the same UUID
--   • email_preferences row (if any) — fast to re-create but easier
--     to wipe explicitly so tests don't inherit weird flags
--
-- Wiped (FK-cascade or explicit):
--   • All agents (cascades to observables, states, probes, watchers,
--     verifications, anchors, agent_mesh_pairs)
--   • All api_keys (the suite mints fresh ones via bypass)
--   • All webhook_endpoints
--   • email_preferences row (toggles back to defaults)
--
-- Usage:
--   psql "$METALINS_DB_URL" -f server/scripts/cleanup-synthetic-tenant-full.sql
--
-- Safety: every WHERE clause scopes to the sandbox customer's id.
-- Production tenants are not touched.

\set ON_ERROR_STOP on

BEGIN;

-- Resolve sandbox once.
WITH sandbox AS (
  SELECT id AS customer_id
  FROM customers
  WHERE email = 'testing@metalins.local'
)
-- Cascade-delete every agent owned by the sandbox.
DELETE FROM agents
USING api_keys k, sandbox s
WHERE agents.api_key_id = k.id
  AND k.customer_id = s.customer_id;

-- Wipe webhook endpoints for the sandbox.
DELETE FROM webhook_endpoints
WHERE customer_id IN (
  SELECT id FROM customers WHERE email = 'testing@metalins.local'
);

-- Wipe email preferences (resets toggles to defaults).
DELETE FROM email_preferences
WHERE customer_id IN (
  SELECT id FROM customers WHERE email = 'testing@metalins.local'
);

-- Wipe all api_keys for the sandbox. The orchestrator mints a fresh
-- one via the bypass HMAC at suite setup, so even the bootstrap key
-- can go — nothing else needs to survive.
DELETE FROM api_keys
WHERE customer_id IN (
  SELECT id FROM customers WHERE email = 'testing@metalins.local'
);

COMMIT;

-- Confirmation (should all be 0).
WITH sandbox AS (
  SELECT id AS customer_id
  FROM customers
  WHERE email = 'testing@metalins.local'
)
SELECT
  (SELECT COUNT(*) FROM agents a
     JOIN api_keys k ON k.id = a.api_key_id
     JOIN sandbox s ON s.customer_id = k.customer_id) AS remaining_agents,
  (SELECT COUNT(*) FROM api_keys
     WHERE customer_id IN (SELECT customer_id FROM sandbox)) AS remaining_keys,
  (SELECT COUNT(*) FROM webhook_endpoints
     WHERE customer_id IN (SELECT customer_id FROM sandbox)) AS remaining_webhooks,
  (SELECT COUNT(*) FROM email_preferences
     WHERE customer_id IN (SELECT customer_id FROM sandbox)) AS remaining_email_prefs;

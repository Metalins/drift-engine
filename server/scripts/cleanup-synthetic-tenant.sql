-- cleanup-synthetic-tenant.sql
--
-- Sprint UX-5.11 / bug-carlos-1 (and confirmed by bug-diana-* and bug-sofia-6).
-- Three personas in a row (Carlos, Diana, Sofía) flagged that the
-- testing@metalins.local sandbox accumulates agents from prior synthetic
-- runs and looks like a shared dev workspace at first login.
--
-- This script soft-deletes (hard-deletes for clean cut) every agent
-- whose name matches the synthetic-run patterns we use across persona
-- specs and Playwright fixtures. Run between Round-N and Round-(N+1)
-- to give the next persona a clean cold-start.
--
-- Usage:
--   psql "$METALINS_DB_URL" -f server/scripts/cleanup-synthetic-tenant.sql
--
-- Or via Supabase SQL editor (UI):
--   1. Paste the body of this file.
--   2. Inspect the SELECT preview first.
--   3. Uncomment the DELETE block and run.
--
-- Safety:
--   * Only matches agents owned by the testing@metalins.local sandbox
--     customer. Production tenants are not touched even if their agents
--     happen to be named e2e-* or carlos-*.
--   * Cascades via the FK relationships defined in the schema.
--   * Idempotent — re-running on a clean tenant is a no-op.

\set ON_ERROR_STOP on

-- 1. Resolve the sandbox customer_id once so we don't need to repeat it.
WITH sandbox AS (
  SELECT id AS customer_id
  FROM customers
  WHERE email = 'testing@metalins.local'
)
-- 2. Preview what would be deleted. Comment this out for non-interactive runs.
SELECT a.id, a.name, a.created_at, a.is_active
FROM agents a
JOIN api_keys k ON k.id = a.api_key_id
JOIN sandbox s ON s.customer_id = k.customer_id
WHERE
  -- Patterns the persona / spec runs use. Extend conservatively when
  -- new test naming conventions land — accidental deletion of a real
  -- customer agent would be bad even on the sandbox.
  a.name ILIKE 'e2e-%'
  OR a.name ILIKE 'andrea-%'
  OR a.name ILIKE 'carlos-%'
  OR a.name ILIKE 'diana-%'
  OR a.name ILIKE 'sofia-%'
  OR a.name ILIKE 'sofía-%'
  OR a.name ILIKE 'sof%-%'
  OR a.name ILIKE 'support-bot-%'
  OR a.name ILIKE '%synthetic%'
  OR a.name ILIKE 'my-claude-code-%'
ORDER BY a.created_at DESC;

-- 3. Hard delete (uncomment after reviewing the SELECT above).
-- IMPORTANT: relies on ON DELETE CASCADE for agent_observables,
-- agent_states, memory_probes, watchers, verifications, etc. If a
-- table is added without cascade, this fails loudly — fix the FK,
-- don't add a manual DELETE here (we want failure to be loud).
--
-- BEGIN;
--   WITH sandbox AS (
--     SELECT id AS customer_id
--     FROM customers
--     WHERE email = 'testing@metalins.local'
--   )
--   DELETE FROM agents
--   USING api_keys k, sandbox s
--   WHERE
--     agents.api_key_id = k.id
--     AND k.customer_id = s.customer_id
--     AND (
--       agents.name ILIKE 'e2e-%'
--       OR agents.name ILIKE 'andrea-%'
--       OR agents.name ILIKE 'carlos-%'
--       OR agents.name ILIKE 'diana-%'
--       OR agents.name ILIKE 'sofia-%'
--       OR agents.name ILIKE 'sofía-%'
--       OR agents.name ILIKE 'sof%-%'
--       OR agents.name ILIKE 'support-bot-%'
--       OR agents.name ILIKE '%synthetic%'
--       OR agents.name ILIKE 'my-claude-code-%'
--     );
-- COMMIT;

-- 4. Confirmation — should be 0 after a successful run.
WITH sandbox AS (
  SELECT id AS customer_id
  FROM customers
  WHERE email = 'testing@metalins.local'
)
SELECT COUNT(*) AS remaining_synthetic_agents
FROM agents a
JOIN api_keys k ON k.id = a.api_key_id
JOIN sandbox s ON s.customer_id = k.customer_id
WHERE
  a.name ILIKE 'e2e-%'
  OR a.name ILIKE 'andrea-%'
  OR a.name ILIKE 'carlos-%'
  OR a.name ILIKE 'diana-%'
  OR a.name ILIKE 'sofia-%'
  OR a.name ILIKE 'sofía-%'
  OR a.name ILIKE 'sof%-%'
  OR a.name ILIKE 'support-bot-%'
  OR a.name ILIKE '%synthetic%'
  OR a.name ILIKE 'my-claude-code-%';

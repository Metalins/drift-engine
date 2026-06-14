-- Metalins schema migration — Sprint 3a-auth.
--
-- This script runs in the Supabase SQL Editor (or via psql $METALINS_DB_URL).
-- It is idempotent: safe to re-run.
--
-- Three things happen:
--   1. api_keys gains user-facing columns (name, description, agent_id, last_used_at, revoked_at)
--   2. A trigger on auth.users INSERT creates a matching customers row
--   3. (Optional, run-once) Backfill: link Jose's pre-existing keys to his customer
--
-- Order matters because the trigger needs the customers table (created in
-- migrate-customers.sql, which must have run first).

-- ----------------------------------------------------------------------------
-- 1. api_keys: new columns for the dashboard's keys-CRUD UI
-- ----------------------------------------------------------------------------
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS agent_id   TEXT      REFERENCES agents(id);
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS name       TEXT;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMP;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS ix_api_keys_agent_id ON api_keys (agent_id);

-- ----------------------------------------------------------------------------
-- 2. Trigger: when Supabase Auth creates a user, materialize a customers row
--    AND a bootstrap api_key for that customer.
--
-- Why customers: our FastAPI backend reads from `customers` (not from
-- auth.users), because (a) cross-schema joins via SQLAlchemy get ugly, and
-- (b) we want a stable "this is a Metalins customer" surface that doesn't
-- leak Supabase's internal columns. The trigger runs in Supabase Postgres
-- (where auth.users lives), so it has direct access — no API roundtrip.
-- `id` is set to auth.users.id so we can validate JWT.sub == customers.id
-- offline in the backend (no Supabase call per request).
--
-- Why bootstrap api_key (added Sprint 5, 2026-05-14):
-- `Agent.api_key_id` is NOT NULL — `_resolve_creator_key` in
-- `server/app/api/agents.py` needs an active api_key with this customer_id
-- to attribute new agents to. Without a key, the first agent-create call
-- from the dashboard returns 412 ("Customer has no active API keys.").
-- The bootstrap key is a *placeholder*: its `key_hash` is random bytes,
-- so no one (including the customer) knows the plaintext. It is NOT usable
-- as a Bearer token. Real keys are minted from /agents/[id]/keys, where the
-- server emits plaintext exactly once.
--
-- ON CONFLICT DO NOTHING keeps the trigger idempotent in both inserts.
-- ----------------------------------------------------------------------------
-- IMPORTANT (2026-05-18 hotfix — bug-signup-broken P0):
-- This function uses ONLY pg_catalog built-ins for crypto. Earlier
-- revisions called `sha256(gen_random_bytes(...))` or
-- `digest(text, 'sha256')` from pgcrypto, which lives in the
-- `extensions` schema in modern Supabase. Triggers run with a
-- restricted search_path that does NOT include `extensions`, so those
-- calls failed with "function digest(...) does not exist" — Supabase
-- Auth surfaced that as the generic "Database error saving new user"
-- on every signup. The fix:
--   • `sha256(bytea)` from `pg_catalog` (Postgres 11+ built-in)
--   • `convert_to(text, 'UTF8')` from `pg_catalog` to bridge text→bytea
--   • Explicit `search_path = public, extensions, pg_catalog` as
--     defense in depth — if a future edit reintroduces a pgcrypto
--     call, it still resolves.
-- Do NOT replace this with pgcrypto-based hashing again unless you
-- also pin the search_path to include `extensions`. Better: keep it
-- on built-ins so this never breaks again.

CREATE OR REPLACE FUNCTION public.handle_new_supabase_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER  -- needed to insert into `public.customers` from auth schema
SET search_path = public, extensions, pg_catalog
AS $$
BEGIN
  INSERT INTO public.customers (id, email, plan, created_at)
  VALUES (NEW.id::text, NEW.email, 'free', COALESCE(NEW.created_at, now()))
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO public.api_keys (
    id, customer_id, key_hash, owner_email, name, is_active, created_at
  )
  VALUES (
    'ak_bootstrap_' || substr(md5(random()::text), 1, 16),
    NEW.id::text,
    -- pg_catalog.sha256(bytea) — no pgcrypto dependency. The hash has
    -- no usable plaintext: the customer must mint real keys from the
    -- dashboard. Random+clock+UUID is enough entropy for the
    -- "never collides" guarantee this row needs.
    encode(
      sha256(
        convert_to(
          random()::text || clock_timestamp()::text || NEW.id::text,
          'UTF8'
        )
      ),
      'hex'
    ),
    NEW.email,
    'bootstrap (placeholder, no usable plaintext)',
    true,
    COALESCE(NEW.created_at, now())
  )
  ON CONFLICT DO NOTHING;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW
  EXECUTE FUNCTION public.handle_new_supabase_user();

-- ----------------------------------------------------------------------------
-- 3. Verification
-- ----------------------------------------------------------------------------
SELECT 'api_keys.agent_id exists' AS check,
       EXISTS (
         SELECT 1 FROM information_schema.columns
         WHERE table_name='api_keys' AND column_name='agent_id'
       ) AS ok
UNION ALL
SELECT 'api_keys.name exists',
       EXISTS (
         SELECT 1 FROM information_schema.columns
         WHERE table_name='api_keys' AND column_name='name'
       )
UNION ALL
SELECT 'trigger on_auth_user_created exists',
       EXISTS (
         SELECT 1 FROM pg_trigger
         WHERE tgname='on_auth_user_created'
       );

-- ----------------------------------------------------------------------------
-- 4. (Run-once, AFTER Jose's first magic-link login) — backfill legacy keys
-- ----------------------------------------------------------------------------
-- After you log in once at http://localhost:3000/login, a customers row is
-- created automatically by the trigger above. THEN run this block (manually,
-- substituting the actual auth.users.id) to link your pre-existing keys + agents
-- to that customer:
--
-- 1. Find your Supabase auth user id:
--    SELECT id, email FROM auth.users WHERE email = 'josemiguelhernandez16@gmail.com';
--
-- 2. With that UUID, run:
--    UPDATE api_keys
--       SET customer_id = '<your-auth-uuid>'
--     WHERE customer_id IS NULL;
--
-- 3. Verify:
--    SELECT id, owner_email, customer_id, name, agent_id FROM api_keys
--     WHERE customer_id = '<your-auth-uuid>';

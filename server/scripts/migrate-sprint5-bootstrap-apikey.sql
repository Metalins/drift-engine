-- Sprint 5 — bootstrap api_key fix (applied 2026-05-14)
--
-- ▸ Context
-- The Supabase region migration sa-east-1 → us-east-1 created a fresh DB
-- with the trigger from `migrate-3a-auth.sql`. That trigger ONLY created
-- `customers.<id>` on new signup; it did NOT create any `api_keys` row.
--
-- ▸ The bug
-- `server/app/api/agents.py` → `_resolve_creator_key()` requires an active
-- api_key with the caller's customer_id (because `Agent.api_key_id` is
-- NOT NULL — cosmetic attribution of "which key originally registered this
-- agent"). New customers with zero keys hit 412:
--   "Customer has no active API keys. Create one first under any existing
--    agent, or contact support to bootstrap a customer-wide key."
-- The dashboard's Server Action wrapped that 412 as a 500, which is what
-- Jose saw when trying to register his first agent post-migration.
--
-- ▸ The fix
-- 1. Patch `handle_new_supabase_user` so future signups auto-bootstrap a
--    placeholder api_key. See `migrate-3a-auth.sql` for the new function
--    body — this file applies the same SQL in standalone form.
-- 2. Backfill any existing customer that doesn't have an active api_key
--    yet (Jose was the only one in this DB at the time, but the query is
--    generic and idempotent — safe to re-run).
--
-- ▸ Why "placeholder" keys are safe
-- `key_hash` is `sha256(gen_random_bytes(32))`. The plaintext was never
-- materialized to disk or returned — it exists only briefly inside Postgres
-- and is discarded. Nobody (including the customer) can present a Bearer
-- token that hashes to this value. So the row passes FK constraints and
-- the `is_active` check in `_resolve_creator_key`, but cannot authenticate
-- any API call. Real customer-issued keys come from /agents/[id]/keys,
-- which generates the plaintext, hashes it, stores the hash, and returns
-- the plaintext ONCE.

-- ----------------------------------------------------------------------------
-- 1. Trigger patch (idempotent — re-applies the function body)
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.handle_new_supabase_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
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
    encode(sha256(gen_random_bytes(32)), 'hex'),
    NEW.email,
    'bootstrap (placeholder, no usable plaintext)',
    true,
    COALESCE(NEW.created_at, now())
  )
  ON CONFLICT DO NOTHING;

  RETURN NEW;
END;
$$;

-- ----------------------------------------------------------------------------
-- 2. Backfill: bootstrap-key any customer that has none
-- ----------------------------------------------------------------------------
INSERT INTO public.api_keys (
  id, customer_id, key_hash, owner_email, name, is_active, created_at
)
SELECT
  'ak_bootstrap_' || substr(md5(random()::text || c.id), 1, 16),
  c.id,
  encode(sha256(gen_random_bytes(32)), 'hex'),
  c.email,
  'bootstrap (placeholder, no usable plaintext)',
  true,
  now()
FROM public.customers c
WHERE NOT EXISTS (
  SELECT 1
  FROM public.api_keys k
  WHERE k.customer_id = c.id
    AND k.is_active IS TRUE
);

-- ----------------------------------------------------------------------------
-- 3. Verification
-- ----------------------------------------------------------------------------
SELECT 'customers without an active key' AS check,
       COUNT(*) AS count
  FROM public.customers c
 WHERE NOT EXISTS (
   SELECT 1 FROM public.api_keys k
   WHERE k.customer_id = c.id AND k.is_active IS TRUE
 );
-- Expected: count = 0.

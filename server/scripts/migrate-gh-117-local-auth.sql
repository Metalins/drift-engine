-- Migration: gh-117 / gh-118 — self-hosted local auth.
--
-- Drift Engine now owns its login (bcrypt password + local HS256 JWT)
-- instead of delegating to Supabase. The admin account lives in `customers`
-- with a password hash. These columns back that:
--
--   password_hash        — bcrypt hash; NULL for legacy Supabase-era rows
--                          (they simply can't use the password login path
--                          until a password is set).
--   is_admin             — marks the bootstrap admin account (gh-118).
--   must_change_password — set when the admin is bootstrapped with the
--                          DEFAULT password so the dashboard forces a change
--                          on first login.
--
-- Idempotent. Dev/SQLite and the docker-compose stack get these columns via
-- Base.metadata.create_all on a fresh DB; an EXISTING Postgres instance
-- (José's api.metalins.ai) needs this one-off ALTER before deploying the
-- gh-117 server build. Run it, then the startup bootstrap (app.main
-- _bootstrap_admin_on_startup) creates the admin from METALINS_ADMIN_*.

ALTER TABLE customers
  ADD COLUMN IF NOT EXISTS password_hash TEXT;

ALTER TABLE customers
  ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE customers
  ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN customers.password_hash IS
  'gh-117 bcrypt password hash for local (self-hosted) login. NULL = no '
  'password set (legacy Supabase-era row); cannot use POST /auth/login.';
COMMENT ON COLUMN customers.is_admin IS
  'gh-118 marks the first-run bootstrap admin account.';
COMMENT ON COLUMN customers.must_change_password IS
  'gh-118 set when bootstrapped with the default password; dashboard forces '
  'a change on first login.';

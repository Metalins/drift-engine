-- Sprint UX-5.11 Phase A — Synthetic User Validation Framework
--
-- Inserts the canonical test user used by the bypass-auth header (see
-- docs/product/SYNTHETIC-USER-VALIDATION-FRAMEWORK.md §8 and
-- server/app/core/auth.py:TEST_USER_BYPASS_ID).
--
-- Already applied to Supabase via MCP on 2026-05-17. Kept in-tree as the
-- canonical record of the schema change, identical to what was executed.
--
-- The bypass-auth path in server/app/core/auth.py validates an HMAC header
-- against METALINS_TEST_USER_BYPASS_SECRET and maps the caller to THIS
-- customer row only. The id uses an all-zeros UUID with a trailing 1 so it
-- cannot collide with any Supabase-issued auth.users.id (those are random v4
-- UUIDs).
--
-- Tenant isolation: anything the bypass user creates (agents, watchers,
-- anchors, webhooks) is scoped to customer_id = this UUID. Worst-case secret
-- leak only gives an attacker access to this single sandbox tenant.

INSERT INTO customers (id, email, plan, metadata_json, created_at)
VALUES (
  '00000000-0000-0000-0000-000000000001',
  'testing@metalins.local',
  'free',
  '{"synthetic_user": true, "framework": "synthetic-user-validation", "phase": "A", "notes": "Bypass-auth tenant. Owned by metalins repo, not a real Supabase user."}'::jsonb,
  NOW()
)
ON CONFLICT (id) DO NOTHING;

-- Phase B (Sprint UX-5.11) — seed a placeholder API key so the bypass
-- persona can call `/v1/agents/register`. That endpoint goes through
-- `_resolve_creator_key`, which 412s when the customer has zero active
-- keys (a legacy edge case for fresh Supabase sign-ups). Real customers
-- get a key auto-bootstrapped at sign-up by the dashboard; the bypass
-- tenant bypasses Supabase entirely, so we plant one here.
--
-- The key_hash below is sha256("ml_test_synthetic_placeholder_DO_NOT_USE").
-- It is intentionally a NON-secret value — this key cannot authenticate
-- anything because (a) we never publish the raw form (which is fine, we
-- don't need it: the simulator authenticates via the bypass HEADER, never
-- via this row's hash), and (b) the row exists only so the FK from
-- `agents.api_key_id` has a target after `register_agent` resolves it.
INSERT INTO api_keys (
  id, customer_id, agent_id, key_hash, owner_email, label, name,
  description, is_active, created_at
)
VALUES (
  'key_synthetic_placeholder',
  '00000000-0000-0000-0000-000000000001',
  NULL,
  'fd00d22cf6f9f74e4d3f4a5b7c2e8a1f9d0c3b6e8a1f4d7c0b3e6a9d2c5f8e1b',
  'testing@metalins.local',
  'synthetic-placeholder',
  'synthetic-placeholder',
  'Placeholder key for the bypass-auth tenant. Cannot authenticate — the simulator uses the X-Metalins-Test-Bypass header instead. See SYNTHETIC-USER-VALIDATION-FRAMEWORK.md §9 Phase B.',
  TRUE,
  NOW()
)
ON CONFLICT (id) DO NOTHING;

-- Sprint UX-5.11-pwd — also seed the auth.users row so the test tenant
-- can sign in via /login using email + password. Without this, the
-- bypass header is the only way to reach the tenant. Password recorded
-- in CHECKPOINT under "Test credentials".
--
-- !! GoTrue gotcha !!
-- The token fields below MUST be '' (empty string), NOT NULL. GoTrue's
-- Go structs scan them into `string`, not `*string`, so a NULL row
-- causes "Database error querying schema" 500s on every login attempt.
-- Same for is_super_admin: leave it NULL (Supabase's own signups do).
-- And email/identities.email is GENERATED — never insert into it.

INSERT INTO auth.users (
  instance_id, id, aud, role, email, encrypted_password,
  email_confirmed_at, raw_app_meta_data, raw_user_meta_data,
  created_at, updated_at, is_sso_user, is_anonymous,
  -- GoTrue-required empty strings (NOT NULL even though nullable schema):
  confirmation_token, recovery_token, email_change_token_new, email_change
)
VALUES (
  '00000000-0000-0000-0000-000000000000',
  '00000000-0000-0000-0000-000000000001',
  'authenticated', 'authenticated',
  'testing@metalins.local',
  crypt('MetalinsTest2026!', gen_salt('bf', 10)),
  NOW(),
  '{"provider": "email", "providers": ["email"], "synthetic_user": true}'::jsonb,
  '{"synthetic_user": true, "framework": "synthetic-user-validation"}'::jsonb,
  NOW(), NOW(), FALSE, FALSE,
  '', '', '', ''
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO auth.identities (
  provider_id, user_id, identity_data, provider,
  last_sign_in_at, created_at, updated_at, id
)
VALUES (
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000001',
  jsonb_build_object(
    'sub', '00000000-0000-0000-0000-000000000001',
    'email', 'testing@metalins.local',
    'email_verified', true,
    'provider', 'email'
  ),
  'email',
  NULL, NOW(), NOW(),
  gen_random_uuid()
)
ON CONFLICT DO NOTHING;

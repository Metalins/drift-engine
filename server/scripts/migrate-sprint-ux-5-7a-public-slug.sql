-- Sprint UX-5.7a (#634) — public_slug for human-readable verify URLs.
--
-- Today Carlos's share-verification link is
--   https://metalins-dashboard.josemiguelhernandez-es.workers.dev/verify/agt_zqyLk_aDW6dW2Gs78A6OVQ
-- which is unusable in a Telegram bio (workers.dev origin + 22-char hex
-- path). With this migration the same agent can be reached at
--   /v/<slug>
-- where <slug> is auto-generated from the watcher display name (e.g.
-- "@SenalesCryptoCarlos" → "senales-crypto-carlos") or from the agent
-- name as fallback. Once we point verify.metalins.ai at the dashboard,
-- the link becomes `verify.metalins.ai/v/senales-crypto-carlos`.
--
-- Constraints:
--   • Globally unique (a slug = a public claim about an identity).
--   • Lowercase ASCII [a-z0-9-]+, no leading/trailing hyphen, 3-64 chars
--     (enforced at the application layer; here we just hold the value).
--   • NULL is allowed: pre-existing agents won't have one until they
--     connect a watcher or the customer triggers an explicit
--     "regenerate slug" action.
--
-- Backfill: handled by the application on next agent touch (lazy). We do
-- NOT bulk-backfill here because watcher info isn't joinable trivially in
-- one statement; the lazy strategy keeps the migration safe to re-run.
--
-- Safe to re-run: `IF NOT EXISTS` guards on both column and index.

ALTER TABLE agents
  ADD COLUMN IF NOT EXISTS public_slug TEXT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS agents_public_slug_unique
  ON agents (public_slug)
  WHERE public_slug IS NOT NULL;

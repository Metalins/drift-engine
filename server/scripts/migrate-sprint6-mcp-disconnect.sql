-- Sprint 6.4 / #575 — MCP integration disconnect.
--
-- One agent = one identity = one integration surface (D-PROD.18). Watcher
-- disconnect already exists via the soft-delete on `watchers.deleted_at`.
-- This migration adds the analogous flag for the MCP surface: when set,
-- POST /v1/log_event returns 403 for that agent and `integration.surface`
-- drops MCP from the active list (re-falling back to watcher or "none").
--
-- The user re-enables MCP by POSTing /v1/agents/{id}/reconnect-mcp, which
-- clears the column back to NULL.
--
-- Safe to re-run: `IF NOT EXISTS` guard. No backfill needed.

ALTER TABLE agents
  ADD COLUMN IF NOT EXISTS mcp_disabled_at TIMESTAMP NULL;

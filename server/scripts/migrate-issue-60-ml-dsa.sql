-- Migration: Issue #60 — Add ML-DSA-65 signature column to event_logs
-- Run once against the production DB. The column is nullable so all
-- existing events remain valid (they predate ML-DSA signing).

ALTER TABLE event_logs
  ADD COLUMN IF NOT EXISTS ml_dsa_signature TEXT;

-- Comment for documentation
COMMENT ON COLUMN event_logs.ml_dsa_signature IS
  'ML-DSA-65 (FIPS 204 / Asqav-compatible) quantum-safe signature '
  'over the canonical event payload. Base64-encoded. NULL for events '
  'created before issue #60 migration.';

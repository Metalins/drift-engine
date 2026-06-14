-- Migration: Issue #64 — behavioral drift alerts pipeline.
--
-- Adds the `drift_events` table that records each DRIFT_DETECTED event
-- emitted by the κ-engine V2 (#62) when an agent's recent traffic window
-- drifts away from its learned behavioral baseline (#62/#63). Each row is
-- the durable carrier of one alert: it surfaces in the dashboard, triggers
-- the customer's drift email (EmailPreferences.drift_detected_enabled), and
-- fires any active webhook with a `behavioral_drift.detected` payload.
--
-- Idempotent. Apply on Supabase prod (project ehhxyivzxibinubkzwlb).
-- Dev/SQLite gets the table via Base.metadata.create_all; prod uses this.

CREATE TABLE IF NOT EXISTS drift_events (
  id                 TEXT      PRIMARY KEY,
  agent_id           TEXT      NOT NULL REFERENCES agents(id),
  customer_id        TEXT      REFERENCES customers(id),
  dominant_feature   TEXT      NOT NULL,
  drift_score        DOUBLE PRECISION NOT NULL,
  magnitude          DOUBLE PRECISION,
  baseline_value     TEXT,
  current_value      TEXT,
  attribution_json   JSONB     NOT NULL DEFAULT '{}'::jsonb,
  window_size        INTEGER,
  baseline_n_events  INTEGER,
  notified_email     BOOLEAN   NOT NULL DEFAULT FALSE,
  notified_webhook   BOOLEAN   NOT NULL DEFAULT FALSE,
  acknowledged_at    TIMESTAMP,
  detected_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_drift_events_agent_ts
  ON drift_events (agent_id, detected_at);
CREATE INDEX IF NOT EXISTS idx_drift_events_customer_ts
  ON drift_events (customer_id, detected_at);

COMMENT ON TABLE drift_events IS
  'κ-engine V2 (#64) behavioral drift alerts: one row per DRIFT_DETECTED '
  'event (agent_id, dominant_feature, baseline_value, current_value, '
  'magnitude). Surfaced in the dashboard, emailed to the customer when '
  'EmailPreferences.drift_detected_enabled, and delivered to active '
  'webhooks as behavioral_drift.detected.';

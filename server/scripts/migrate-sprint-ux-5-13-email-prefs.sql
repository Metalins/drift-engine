-- Sprint UX-5.13 (2026-05-18) — email_preferences table.
--
-- Per-customer outbound email preferences. 1:1 with customers. Row is
-- optional — absent row means "use defaults (alerts on, alert_email =
-- the auth email)". The toggles are additive: an alert fires iff
-- `alerts_enabled AND <per_event>_enabled`.
--
-- Idempotent. Apply on Supabase prod (project ehhxyivzxibinubkzwlb).

CREATE TABLE IF NOT EXISTS email_preferences (
  customer_id                  TEXT      PRIMARY KEY REFERENCES customers(id),
  alert_email                  TEXT      NULL,
  alerts_enabled               BOOLEAN   NOT NULL DEFAULT TRUE,
  threshold_crossed_enabled    BOOLEAN   NOT NULL DEFAULT TRUE,
  drift_detected_enabled       BOOLEAN   NOT NULL DEFAULT TRUE,
  weekly_digest_enabled        BOOLEAN   NOT NULL DEFAULT FALSE,
  created_at                   TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at                   TIMESTAMP NOT NULL DEFAULT NOW()
);

-- updated_at autoupdate trigger (Postgres). Cheap insurance against
-- code paths forgetting to set it.
CREATE OR REPLACE FUNCTION email_preferences_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_email_preferences_updated_at ON email_preferences;
CREATE TRIGGER trg_email_preferences_updated_at
  BEFORE UPDATE ON email_preferences
  FOR EACH ROW EXECUTE FUNCTION email_preferences_set_updated_at();

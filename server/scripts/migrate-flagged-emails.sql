-- Phase-2 anti-abuse — flagged_emails (Jose, 2026-05-21).
--
-- An email address reported as an unsolicited sign-in request, via the
-- "this wasn't me" link in the magic-link email. While cleared_at IS
-- NULL, the dashboard gates that address at login (routes the person
-- to support instead of sending another magic link).
--
-- NOTE: the server also creates this table automatically on startup
-- via SQLAlchemy `Base.metadata.create_all`, so applying this file by
-- hand is optional — it is kept for the record and for anyone who
-- wants the table to exist before the next server deploy.
--
-- To clear a flag (support action):
--   UPDATE flagged_emails SET cleared_at = now() WHERE email = '<addr>';

CREATE TABLE IF NOT EXISTS flagged_emails (
    email        text        PRIMARY KEY,
    flagged_at   timestamptz NOT NULL DEFAULT now(),
    cleared_at   timestamptz,
    report_count integer     NOT NULL DEFAULT 1
);

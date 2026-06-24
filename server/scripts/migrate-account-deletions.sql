-- Account deletion audit — account_deletions (Jose, 2026-05-22).
--
-- The one row kept when a customer deletes their account: which email
-- deleted, when, and the reason they gave (mandatory). Everything else
-- tied to the customer — agents, events, event logs, observables,
-- probes, keys, the customer record — is wiped by POST /v1/me/delete.
--
-- NOTE: the server also creates this table automatically on startup
-- via SQLAlchemy `Base.metadata.create_all`, so applying this file by
-- hand is optional.

CREATE TABLE IF NOT EXISTS account_deletions (
    id         text        PRIMARY KEY,
    email      text        NOT NULL,
    reason     text        NOT NULL,
    deleted_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_account_deletions_email
    ON account_deletions (email);

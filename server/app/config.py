"""Server configuration via env vars."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="METALINS_", extra="ignore")

    env: str = "development"
    db_url: str = "sqlite:///./metalins-dev.sqlite"
    host: str = "0.0.0.0"
    port: int = 8000

    # Two ways to load the keypair:
    # 1) DEV: set *_path to read from disk (default).
    # 2) PROD (Fly.io / Render): set *_pem inline — the PEM contents themselves.
    #    When *_pem is set, it takes precedence over *_path.
    private_key_path: str = "./keys/private_key.pem"
    public_key_path: str = "./keys/public_key.pem"
    private_key_pem: str | None = None
    public_key_pem: str | None = None

    key_id: str = "metalins-key-2026-1"
    proof_ttl_seconds: int = 3600

    api_base_url: str = "http://localhost:8000"
    public_base_url: str = "http://localhost:8000"

    # Master token para endpoints admin (bootstrap, etc.). En prod se setea como
    # Secret Manager secret. Si está vacío, los endpoints admin están deshabilitados.
    master_token: str | None = None

    # gh-95 (research-lab pivot, 2026-06-14) — public registration switch.
    # api.metalins.ai is now José's private instance: no external users sign up.
    # When False (the default), the public registration endpoint returns 403 and
    # the dashboard refuses to provision new accounts via magic-link
    # (shouldCreateUser:false). Existing accounts (the admin) and the API-key
    # surface are unaffected — only NEW-account creation is gated. Flip to True
    # only on a deploy that intentionally accepts public signups.
    registration_enabled: bool = False

    # Supabase Auth (Sprint 3a-auth). Used for magic-link login. The JWT secret
    # validates HS256 tokens that the dashboard exchanges with the API. URL +
    # project_ref are surfaced to clients via /v1/public/config. If missing,
    # JWT validation is disabled and only legacy API key auth works (D-PROD.17
    # dual auth degrades gracefully).
    supabase_url: str | None = None
    supabase_project_ref: str | None = None
    supabase_jwt_secret: str | None = None

    # Supabase service-role key. Used by account deletion to remove the
    # customer's `auth.users` record via the Supabase Admin API. When
    # unset, account deletion still wipes ALL application data + writes
    # the audit row, but the Supabase login record survives and must
    # be cleaned up out of band (logged at WARN).
    supabase_service_role_key: str | None = None

    # Sprint UX-5.11 — Synthetic User Validation framework. When set, the
    # backend accepts an extra auth path: HTTP header `X-Metalins-Test-Bypass:
    # <hmac-sha256(secret, "testing@metalins.local")>` maps the caller to the
    # canonical sandbox customer (00000000-0000-0000-0000-000000000001). The
    # bypass is ONLY active when this env var is set; production deploys can
    # leave it unset to disable the path entirely. See
    # docs/product/SYNTHETIC-USER-VALIDATION-FRAMEWORK.md §8 for the rationale.
    test_user_bypass_secret: str | None = None

    # Sprint UX-5.13 (2026-05-18) — Email delivery via Resend. When
    # METALINS_RESEND_API_KEY is unset, email delivery is a no-op
    # logged at WARN level; the rest of the alert pipeline (webhook,
    # in-dashboard signals) continues to work. This lets local dev +
    # the test bypass tenant run without a real Resend account.
    resend_api_key: str | None = None
    email_from_noreply: str = "noreply@contact.metalins.ai"
    email_from_auth: str = "auth@contact.metalins.ai"

    # Phase-2 anti-abuse (2026-05-21) — Cloudflare Turnstile secret.
    # Verifies the human-check on the magic-link "this wasn't me"
    # report. When unset, the report endpoint fails closed (no flag is
    # recorded without a verified human), so the feature is simply
    # inert until the secret is configured.
    turnstile_secret: str | None = None

    log_level: str = "INFO"


settings = Settings()

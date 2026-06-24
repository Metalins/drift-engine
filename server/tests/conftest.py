"""Session-wide pytest setup.

This file is loaded by pytest BEFORE any `test_*.py` module is
imported, so any environment variable we set here is guaranteed to be
in place before `app.config.settings` is first evaluated. That's the
right place to seed the RSA keypair the signing path needs — doing it
inline in `test_issue_proof.py` was racy because earlier-loaded test
modules could import `app.core.signing` (transitively, via
`app.main`) and cache an empty settings instance before our seed ran.

Sprint UX-5.11 R2 / R2.S2 follow-up (2026-05-18) — surfaced when the
new `test_ids_crockford.py` shifted the module load order and made
`test_issue_proof.py`'s inline seed unreliable.
"""
import os


def _seed_test_keypair() -> None:
    """Provision a throwaway RSA keypair available BOTH via env vars
    AND on disk at the default paths. Belt and suspenders:

    * `METALINS_PRIVATE_KEY_PEM` / `METALINS_PUBLIC_KEY_PEM` — used
      when the app code reads PEMs inline (the preferred prod path).
    * `keys/private_key.pem` / `keys/public_key.pem` on disk — used
      when the app falls back to `settings.public_key_path` /
      `private_key_path` (the dev default).

    Why both: `test_admin.py::_reload_app_with_env` re-instantiates
    `Settings()` with monkeypatch'd env vars. Depending on order, the
    re-instantiated settings can end up with `public_key_pem=None`
    and `public_key_path="/nonexistent"`, which crashes
    `app/api/public.py:verify_proof` with FileNotFoundError. Writing
    real keys at the default path means even a totally bare Settings
    (no env vars, no monkeypatch) finds something.

    Idempotent: a pre-set keypair (real CI secret, dev local) is left
    alone. The disk write is best-effort — if the working dir is
    read-only we still have the env-var path.
    """
    # Short-circuit only if BOTH env vars are already set — they're
    # what `app.config.Settings` reads first via the
    # `METALINS_PRIVATE_KEY_PEM` / `METALINS_PUBLIC_KEY_PEM` prefix.
    # We do NOT short-circuit on disk presence alone, because
    # `test_admin.py::_reload_app_with_env` monkeypatches
    # `METALINS_PRIVATE_KEY_PATH=/nonexistent`, which forces the
    # reloaded `Settings()` to ignore the on-disk file and look
    # exclusively at the PEM env vars. Earlier versions of this
    # function bailed out when disk keys existed from a previous run
    # and left the env vars empty — which is exactly the regression
    # that bit Sprint UX-5.11 R2.S2.
    if os.environ.get("METALINS_PRIVATE_KEY_PEM") and os.environ.get(
        "METALINS_PUBLIC_KEY_PEM"
    ):
        return

    priv_pem: str | None = None
    pub_pem: str | None = None

    # If disk keys already exist from a previous run, reuse them —
    # don't regenerate (a fresh keypair invalidates already-issued
    # tokens that some tests share across modules).
    if os.path.exists("keys/private_key.pem") and os.path.exists(
        "keys/public_key.pem"
    ):
        try:
            with open("keys/private_key.pem", "r") as f:
                priv_pem = f.read()
            with open("keys/public_key.pem", "r") as f:
                pub_pem = f.read()
        except OSError:
            priv_pem = pub_pem = None

    if not priv_pem or not pub_pem:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub = priv.public_key()
        priv_pem = priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")
        pub_pem = pub.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        # Disk fallback path — best-effort. Some sandboxes mount the
        # working dir read-only; in that case we keep going with env
        # vars only.
        try:
            os.makedirs("keys", exist_ok=True)
            with open("keys/private_key.pem", "w") as f:
                f.write(priv_pem)
            with open("keys/public_key.pem", "w") as f:
                f.write(pub_pem)
        except OSError:
            pass

    # ALWAYS set env vars — this is the line that fixes the bug. Even
    # when the disk keys were already there, we need the env vars set
    # so that `Settings()` reloads (triggered by test_admin) see them
    # and don't fall through to the disk-path branch with a
    # monkeypatched-then-undone `/nonexistent` path.
    os.environ["METALINS_PRIVATE_KEY_PEM"] = priv_pem
    os.environ["METALINS_PUBLIC_KEY_PEM"] = pub_pem


# Run at import time so the env var is present BEFORE any test module
# imports `app.config`. pytest discovers and imports conftest.py before
# any test_*.py in the same directory, so this is the right hook.
_seed_test_keypair()


def pytest_configure(config):
    """Belt-and-suspenders: also patch the live `settings` singleton.

    `app.config.settings = Settings()` is evaluated at module import.
    If another path imports `app.config` (transitively) before the env
    vars take effect — pytest plugins, autouse fixtures in nested
    conftests, etc. — the cached `settings.public_key_pem` will be
    None and any code path that reads `settings.public_key_pem`
    directly (e.g. `app/api/public.py:verify_proof`) will fall through
    to the disk-file branch and crash on FileNotFoundError. Here we
    re-import `app.config`, re-read env vars, and overwrite the live
    singleton attributes.
    """
    # Make sure the env vars from `_seed_test_keypair` are present.
    _seed_test_keypair()
    try:
        from app.config import settings as _live_settings
        import os as _os

        priv = _os.environ.get("METALINS_PRIVATE_KEY_PEM")
        pub = _os.environ.get("METALINS_PUBLIC_KEY_PEM")
        if priv:
            _live_settings.private_key_pem = priv
        if pub:
            _live_settings.public_key_pem = pub
    except Exception:
        # If `app.config` can't be imported yet (highly unlikely at
        # pytest_configure time), the per-module seed in
        # test_issue_proof.py's old style would have been the only
        # path. Just skip — tests that need the keypair will still
        # crash with a clear error.
        pass

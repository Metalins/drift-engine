"""Initialize DB schema + create a dev API key for local testing."""
import hashlib
import secrets
import sys
from pathlib import Path

# Add server/ to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import engine, Base, models  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


def main() -> None:
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("✓ Tables created.")

    # gh-118 — bootstrap the first-run admin from METALINS_ADMIN_* env vars so
    # a fresh docker-compose stack is immediately loginnable. Idempotent; runs
    # before the dev-key block (which may early-return).
    from app.services.first_run import bootstrap_admin  # noqa: E402

    db_admin = SessionLocal()
    try:
        admin = bootstrap_admin(db_admin)
        if admin is not None:
            print(f"✓ Admin account ready: {admin.email}")
            if admin.must_change_password:
                print("  ⚠ Using the DEFAULT password — change it on first login.")
        else:
            print("⚠ Admin already exists. Skipping bootstrap.")
        # gh-121 — the dev API key must be linked to the admin's customer_id,
        # otherwise _validate_api_key returns 409 ("not linked to a customer
        # yet") and every /internal/v1/* endpoint is unusable. bootstrap_admin
        # returns None when an admin already existed, so resolve the id from
        # the live admin row in that case.
        admin_id = admin.id if admin is not None else None
        if admin_id is None:
            existing_admin = (
                db_admin.query(models.Customer)
                .filter(models.Customer.is_admin.is_(True))
                .first()
            )
            admin_id = existing_admin.id if existing_admin is not None else None
        if admin_id is None:
            print(
                "  ⚠ No admin account found — dev API key will be created "
                "WITHOUT a customer link (endpoints will 409 until linked)."
            )
    finally:
        db_admin.close()

    db = SessionLocal()
    try:
        existing = db.query(models.APIKey).filter_by(label="dev-default").first()
        if existing:
            # Self-heal: an older init created this key without a customer_id.
            # Link it to the admin now so /internal/v1/* works after upgrade.
            if existing.customer_id is None and admin_id is not None:
                existing.customer_id = admin_id
                db.commit()
                print("✓ Linked existing dev API key to admin customer_id.")
            else:
                print("⚠ Dev API key already exists. Skipping.")
                print("  To get the raw key, regenerate by deleting the row.")
            return

        raw_key = "ml_dev_" + secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        api_key = models.APIKey(
            id="key_dev_default",
            customer_id=admin_id,
            key_hash=key_hash,
            owner_email="dev@metalins.local",
            label="dev-default",
            is_active=True,
        )
        db.add(api_key)
        db.commit()

        print()
        print("=" * 70)
        print(f"✓ Dev API key created. SAVE THIS — it is only shown once:")
        print()
        print(f"   {raw_key}")
        print()
        print("=" * 70)
        print()
        print("Use it as: Authorization: Bearer <api_key>")
    finally:
        db.close()


if __name__ == "__main__":
    main()

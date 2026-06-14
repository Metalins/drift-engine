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

    db = SessionLocal()
    try:
        existing = db.query(models.APIKey).filter_by(label="dev-default").first()
        if existing:
            print("⚠ Dev API key already exists. Skipping.")
            print("  To get the raw key, regenerate by deleting the row.")
            return

        raw_key = "ml_dev_" + secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        api_key = models.APIKey(
            id="key_dev_default",
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

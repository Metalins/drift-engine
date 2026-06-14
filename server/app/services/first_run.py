"""First-run admin bootstrap (gh-118).

A fresh self-hosted Drift Engine has no users. On startup, if no admin
account exists yet, we create one from `METALINS_ADMIN_EMAIL` /
`METALINS_ADMIN_PASSWORD` (defaults: admin@localhost / changeme) so the
operator can log in to the dashboard immediately after `docker-compose up`.

When the account is created with the DEFAULT password, it is flagged
`must_change_password` so the dashboard forces a change on first login.
Supplying a custom `METALINS_ADMIN_PASSWORD` skips that flag.

Idempotent: once an admin exists, this is a no-op. It never touches or
overwrites an existing account's password.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core import local_auth
from app.core.ids import new_id
from app.db.models import Customer

log = logging.getLogger(__name__)

# Sentinel default — matches the config default. Creating the admin with
# this exact password forces a change on first login.
DEFAULT_ADMIN_PASSWORD = "changeme"


def bootstrap_admin(db: Session) -> Customer | None:
    """Ensure an admin account exists. Returns the created admin, or None
    when one already existed (no-op)."""
    # Read settings at call time (not module import) so a deploy / test that
    # reloads app.config picks up the live values rather than a stale ref.
    from app.config import settings

    existing_admin = (
        db.query(Customer).filter(Customer.is_admin.is_(True)).first()
    )
    if existing_admin is not None:
        return None

    email = (settings.admin_email or "admin@localhost").strip().lower()

    # If a customer with that email already exists (e.g. a legacy Supabase
    # row), promote it to admin + set a password rather than colliding on
    # the unique email constraint.
    customer = db.query(Customer).filter(Customer.email == email).first()
    using_default = settings.admin_password == DEFAULT_ADMIN_PASSWORD
    password_hash = local_auth.hash_password(settings.admin_password)

    if customer is not None:
        customer.is_admin = True
        if not customer.password_hash:
            customer.password_hash = password_hash
            customer.must_change_password = using_default
        db.commit()
        log.info("Promoted existing account %s to admin.", email)
        return customer

    customer = Customer(
        id=new_id("cust"),
        email=email,
        is_admin=True,
        password_hash=password_hash,
        must_change_password=using_default,
    )
    db.add(customer)
    db.commit()
    if using_default:
        log.warning(
            "Bootstrapped admin %s with the DEFAULT password — change it on "
            "first login (METALINS_ADMIN_PASSWORD).",
            email,
        )
    else:
        log.info("Bootstrapped admin %s from METALINS_ADMIN_* env vars.", email)
    return customer

"""Regression test for gh-121 — dev API key must be linked to the admin.

`server/scripts/init_db.py` bootstraps the first-run admin and then creates
a `dev-default` API key. Before gh-121 that key was created with
`customer_id=NULL`, so `_validate_api_key` raised 409 ("not linked to a
customer yet") and every `/internal/v1/*` endpoint was unusable on a fresh
docker-compose stack.

Isolation note: every other auth test module forces a shared process-wide
`app.db.session.engine` via a module-level `METALINS_DB_URL`. To avoid
polluting that shared schema, this module never touches the global engine —
it spins up its OWN throwaway SQLite engine and monkeypatches the two names
`init_db` reads (`engine` and `SessionLocal`) onto it for the duration of
each test.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("METALINS_DISABLE_INPROC_SCHEDULER", "1")


@pytest.fixture
def isolated_init_db(tmp_path, monkeypatch):
    """Return the reloaded `scripts.init_db` module wired to a private,
    empty SQLite DB plus a session factory pointing at the same DB."""
    import importlib

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base, models  # noqa: F401  (registers metadata)

    db_path = tmp_path / "init_db_test.sqlite"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    # Pin the admin bootstrap inputs so the run is deterministic.
    monkeypatch.setenv("METALINS_ADMIN_EMAIL", "admin@localhost")
    monkeypatch.setenv("METALINS_ADMIN_PASSWORD", "changeme")

    import scripts.init_db as init_db

    importlib.reload(init_db)
    # init_db.main() uses the module-global `engine` for create_all and
    # `SessionLocal` for every session it opens. Redirect both at our
    # private DB so the shared engine is never touched.
    monkeypatch.setattr(init_db, "engine", engine, raising=True)
    monkeypatch.setattr(init_db, "SessionLocal", Session, raising=True)

    init_db._test_engine = engine
    init_db._test_Session = Session
    return init_db


def _dev_key(init_db):
    from app.db import models

    db = init_db._test_Session()
    try:
        return db.query(models.APIKey).filter_by(label="dev-default").first()
    finally:
        db.close()


def _admin(init_db):
    from app.db import models

    db = init_db._test_Session()
    try:
        return (
            db.query(models.Customer)
            .filter(models.Customer.is_admin.is_(True))
            .first()
        )
    finally:
        db.close()


def test_dev_key_linked_to_admin_on_fresh_db(isolated_init_db):
    isolated_init_db.main()

    admin = _admin(isolated_init_db)
    assert admin is not None, "bootstrap_admin should have created an admin"

    key = _dev_key(isolated_init_db)
    assert key is not None, "dev-default API key should have been created"
    assert key.customer_id == admin.id, (
        "gh-121: dev key must be linked to the admin's customer_id, "
        f"got {key.customer_id!r} vs admin {admin.id!r}"
    )


def test_dev_key_self_heals_when_unlinked(isolated_init_db):
    """An older init left a dev key with customer_id=NULL. Re-running
    init_db should backfill the link rather than silently skip it."""
    from app.db import models

    isolated_init_db.main()
    admin = _admin(isolated_init_db)
    assert admin is not None

    # Simulate the pre-gh-121 broken state: unlink the key.
    db = isolated_init_db._test_Session()
    try:
        key = db.query(models.APIKey).filter_by(label="dev-default").first()
        key.customer_id = None
        db.commit()
    finally:
        db.close()

    isolated_init_db.main()  # re-run should self-heal

    key = _dev_key(isolated_init_db)
    assert key.customer_id == admin.id, "re-run should backfill customer_id"


def test_dev_key_idempotent_second_run(isolated_init_db):
    isolated_init_db.main()
    first = _dev_key(isolated_init_db)
    isolated_init_db.main()
    second = _dev_key(isolated_init_db)
    # Same row (same fixed id), still linked — no duplicate key created.
    assert first.id == second.id
    assert second.customer_id is not None

"""Metalins server entrypoint."""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import agents, verify, public, admin, mcp_endpoints, me, api_keys, watchers, anchors, badge, webhooks, developer, abuse, compliance, auth_registration, auth_local
from app.config import settings
from app.db import engine, Base
from app.services.observable_job import start_scheduler, stop_scheduler
from app.services.watcher_job import start_watcher_scheduler

log = logging.getLogger(__name__)

# Auto-create tables in dev (in prod use Alembic migrations)
Base.metadata.create_all(bind=engine)


def _bootstrap_admin_on_startup() -> None:
    """gh-118 — create the first-run admin if none exists. Best-effort:
    a deploy whose schema predates the gh-117 columns (migration not yet
    applied) shouldn't crash boot — it logs and the legacy auth path keeps
    working until the migration lands."""
    from app.db.session import SessionLocal
    from app.services.first_run import bootstrap_admin

    db = SessionLocal()
    try:
        bootstrap_admin(db)
    except Exception:  # noqa: BLE001 — never block startup on bootstrap
        log.exception("Admin bootstrap skipped (schema migration pending?)")
    finally:
        db.close()


_bootstrap_admin_on_startup()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # On Cloud Run scale-to-zero this scheduler runs only when the container
    # is warm; for guaranteed cadence, use Cloud Scheduler hitting
    # POST /v1/admin/observables/run-batch. Both paths are idempotent.
    if os.environ.get("METALINS_DISABLE_INPROC_SCHEDULER") != "1":
        try:
            start_scheduler(interval_minutes=60)
        except Exception:
            pass
        try:
            start_watcher_scheduler(interval_seconds=60)
        except Exception:
            pass
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(
    title="Metalins API",
    description="Authority for AI agent identity verification (κ-Proofs).",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Relying-party (no-auth), legacy, admin and MCP planes — each keeps its
# own namespace; none collide with the developer API.
app.include_router(public.router)
app.include_router(verify.router)
app.include_router(admin.router)
app.include_router(mcp_endpoints.router)
app.include_router(badge.router)
# Anti-abuse plane (phase-2) — public, no-auth: the magic-link
# "this wasn't me" report + the login-time flag check.
app.include_router(abuse.router)
# Registration gate (gh-95) — public, no-auth: the closed public-signup
# endpoint + the registration-policy probe the dashboard reads.
app.include_router(auth_registration.router)
# Local auth (gh-117) — public plane: POST /auth/login + /auth/change-password.
# Self-hosted login; replaces Supabase magic-link.
app.include_router(auth_local.router)

# Developer API plane (UX-5.17.API1) — the public, API-key-authed surface
# customers and the SDK call. Lives at /v1/; see PUBLIC-API-DESIGN.md.
app.include_router(developer.router)
# Compliance export — GET /v1/agents/{id}/compliance-export.
# Separate module to keep compliance logic isolated; same /v1/ namespace.
app.include_router(compliance.router)

# --- API1b Step 3 cutover (UX-5.17 — PUBLIC-API-DESIGN.md §8).
# The dashboard BFF routers are now mounted ONLY under /internal/. The
# bare /v1/ mount was removed once the dashboard moved onto /internal/
# (Step 2), freeing the /v1/ namespace for the developer API. These
# routers carry JWT/session auth and are an internal contract — never a
# customer-facing surface. The migration window's dual mount is over.
for _bff_router in (
    agents.router,
    me.router,
    api_keys.router,
    anchors.router,
    webhooks.router,
    watchers.router,
):
    app.include_router(_bff_router, prefix="/internal")


@app.get("/")
def root():
    return {
        "service": "metalins",
        "version": __version__,
        "docs": "/docs",
        "jwks": "/.well-known/jwks.json",
        "verify_proof": "/v1/verify-proof",
    }

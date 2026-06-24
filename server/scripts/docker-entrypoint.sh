#!/bin/sh
# Entrypoint for the self-hosting docker-compose stack (gh-89).
#
# This is NOT used by the Cloud Run production deploy — that uses the
# Dockerfile's default CMD with keys injected via Secret Manager and the
# schema managed out of band. docker-compose overrides `command:` to run
# this script so a fresh `docker-compose up` is turnkey:
#
#   1. Generate an RS256 signing keypair on first boot (if none is present
#      and none was supplied via METALINS_PRIVATE_KEY_PEM). Persisted in the
#      `keys` named volume so proofs stay verifiable across restarts.
#   2. Wait for Postgres, then create the schema + a dev API key (idempotent).
#   3. Exec uvicorn so SIGTERM reaches the worker for clean shutdown.
set -e

KEY_PATH="${METALINS_PRIVATE_KEY_PATH:-./keys/private_key.pem}"

if [ -z "$METALINS_PRIVATE_KEY_PEM" ] && [ ! -f "$KEY_PATH" ]; then
  echo "[entrypoint] No signing keypair found — generating an RS256 keypair..."
  python scripts/generate_keypair.py
fi

# Wait for the database to accept connections before touching the schema.
# init_db.py is idempotent (skips the dev key if it already exists), but it
# needs the DB reachable first. Retry for ~30s, then let it fail loudly.
echo "[entrypoint] Waiting for the database..."
i=0
until python scripts/init_db.py; do
  i=$((i + 1))
  if [ "$i" -ge 15 ]; then
    echo "[entrypoint] Database did not become ready in time — giving up." >&2
    exit 1
  fi
  echo "[entrypoint] DB not ready yet (attempt $i/15) — retrying in 2s..."
  sleep 2
done

echo "[entrypoint] Starting Metalins server on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"

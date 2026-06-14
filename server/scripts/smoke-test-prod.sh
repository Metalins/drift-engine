#!/usr/bin/env bash
# smoke-test-prod.sh — corre el smoke test E2E completo contra el deploy de Cloud Run.
#
# Usa los venvs locales de sdk-verify-python (que tiene httpx + jose).
#
# Pre-requisitos:
#   - export METALINS_SERVER="https://metalins-server-....run.app"
#   - export METALINS_DEV_KEY="ml_live_..."  (del bootstrap)
#   - `make install-sdks-py` corrido (necesita sdk-verify-python/.venv)
#
# Uso (desde server/ o desde el root del repo):
#   bash scripts/smoke-test-prod.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SERVER_DIR/.." && pwd)"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { printf "${GREEN}▶${NC} %s\n" "$*"; }
fail() { printf "${RED}✗ %s${NC}\n" "$*" >&2; exit 1; }

[ -n "${METALINS_SERVER:-}" ] || fail "Set METALINS_SERVER first: export METALINS_SERVER='https://...run.app'"
[ -n "${METALINS_DEV_KEY:-}" ] || fail "Set METALINS_DEV_KEY first: export METALINS_DEV_KEY='ml_live_...'"

VENV_PY="$REPO_ROOT/sdk-verify-python/.venv/bin/python"
[ -x "$VENV_PY" ] || fail "No existe sdk-verify-python venv. Corré: make install-sdks-py"

E2E_SCRIPT="$REPO_ROOT/scripts/e2e_smoke_test.py"
[ -f "$E2E_SCRIPT" ] || fail "No encuentro $E2E_SCRIPT"

log "Corriendo smoke test E2E contra $METALINS_SERVER"
log "(server real, no localhost — esto valida deploy + bootstrap key + flow completo)"
echo

"$VENV_PY" "$E2E_SCRIPT"

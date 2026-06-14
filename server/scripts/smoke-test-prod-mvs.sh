#!/usr/bin/env bash
# smoke-test-prod-mvs.sh — E2E MVS smoke contra el deploy de Cloud Run.
#
# Hace TODO en un comando:
#   1. Lee SERVER URL desde Cloud Run.
#   2. Lee master token desde Secret Manager.
#   3. Bootstrap un API key fresco (idempotente — siempre crea uno nuevo).
#   4. Corre scripts/e2e_smoke_test_mvs.py contra prod usando sdk-python/.venv.
#
# Pre-requisitos:
#   - gcloud CLI autenticado, proyecto activo.
#   - El secret metalins-master-token existe en Secret Manager.
#   - El service metalins-server existe en Cloud Run.
#   - sdk-python/.venv existe con httpx instalado (`make install-sdks-py`).
#
# Uso (desde server/ o desde el root):
#   bash server/scripts/smoke-test-prod-mvs.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SERVER_DIR/.." && pwd)"

SERVICE="metalins-server"
REGION="southamerica-east1"
MASTER_TOKEN_SECRET="metalins-master-token"
OWNER_EMAIL="founder@metalins.com"
LABEL="sprint-2.5-e2e-$(date -u +%Y%m%d-%H%M%S)"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { printf "${GREEN}▶${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}⚠${NC} %s\n" "$*"; }
fail() { printf "${RED}✗ %s${NC}\n" "$*" >&2; exit 1; }

# --- pre-flight ---
command -v gcloud >/dev/null || fail "gcloud CLI no encontrado"
PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
[ -n "$PROJECT" ] || fail "No hay proyecto gcloud activo. Corré: gcloud config set project <id>"

VENV_PY="$REPO_ROOT/sdk-python/.venv/bin/python"
[ -x "$VENV_PY" ] || fail "No existe sdk-python/.venv. Corré: cd sdk-python && python3 -m venv .venv && .venv/bin/pip install -e . httpx"

E2E_SCRIPT="$REPO_ROOT/scripts/e2e_smoke_test_mvs.py"
[ -f "$E2E_SCRIPT" ] || fail "No encuentro $E2E_SCRIPT"

# --- step 1: leer URL del server ---
log "Step 1/4: leer SERVER URL de Cloud Run"
SERVER_URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)' 2>/dev/null || true)"
[ -n "$SERVER_URL" ] || fail "No pude leer la URL del servicio '$SERVICE' en '$REGION'."
log "  URL: $SERVER_URL"

# --- step 2: leer master token ---
log "Step 2/4: leer master token de Secret Manager"
MASTER_TOKEN="$(gcloud secrets versions access latest --secret="$MASTER_TOKEN_SECRET" 2>/dev/null || true)"
[ -n "$MASTER_TOKEN" ] || fail "No pude leer el secret '$MASTER_TOKEN_SECRET'."

# --- step 3: bootstrap fresh API key ---
log "Step 3/4: bootstrap API key fresca ($LABEL)"
RESPONSE="$(curl -fsS -X POST \
  -H "Content-Type: application/json" \
  -H "X-Master-Token: $MASTER_TOKEN" \
  -d "{\"owner_email\":\"$OWNER_EMAIL\",\"label\":\"$LABEL\"}" \
  "$SERVER_URL/v1/admin/bootstrap-api-key")"
API_KEY="$(echo "$RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_key"])')"
[ -n "$API_KEY" ] || fail "Bootstrap API key falló. Response: $RESPONSE"
log "  Key creado (label=$LABEL)"

# --- step 4: correr E2E ---
log "Step 4/4: correr E2E MVS smoke"
echo

export METALINS_SERVER="$SERVER_URL"
export METALINS_DEV_KEY="$API_KEY"
export METALINS_MASTER_TOKEN="$MASTER_TOKEN"

"$VENV_PY" "$E2E_SCRIPT"

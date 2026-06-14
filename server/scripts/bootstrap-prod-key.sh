#!/usr/bin/env bash
# bootstrap-prod-key.sh — crea el primer API key en el deploy de Cloud Run.
#
# Uso (desde server/):
#   bash scripts/bootstrap-prod-key.sh                       # owner=founder@metalins.com
#   bash scripts/bootstrap-prod-key.sh founder@metalins.com  # custom owner

set -euo pipefail

SERVICE="metalins-server"
REGION="southamerica-east1"
MASTER_TOKEN_SECRET="metalins-master-token"
OWNER_EMAIL="${1:-founder@metalins.com}"
LABEL="${2:-bootstrap-$(date -u +%Y%m%d-%H%M)}"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { printf "${GREEN}▶${NC} %s\n" "$*"; }
fail() { printf "${RED}✗ %s${NC}\n" "$*" >&2; exit 1; }

log "Leyendo SERVER_URL desde Cloud Run..."
SERVER_URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
[ -n "$SERVER_URL" ] || fail "No pude leer la URL del servicio."
log "Server URL: $SERVER_URL"

log "Leyendo master token desde Secret Manager..."
MASTER_TOKEN="$(gcloud secrets versions access latest --secret="$MASTER_TOKEN_SECRET")"
[ -n "$MASTER_TOKEN" ] || fail "No pude leer el master token."

log "Creando API key para owner=$OWNER_EMAIL, label=$LABEL..."
RESPONSE="$(curl -fsS -X POST \
  -H "Content-Type: application/json" \
  -H "X-Master-Token: $MASTER_TOKEN" \
  -d "{\"owner_email\":\"$OWNER_EMAIL\",\"label\":\"$LABEL\"}" \
  "$SERVER_URL/v1/admin/bootstrap-api-key")"

API_KEY="$(echo "$RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_key"])')"
KEY_ID="$(echo "$RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["key_id"])')"

echo
printf "${GREEN}=======================================================${NC}\n"
printf "${GREEN}✅ API KEY CREADO${NC}\n"
printf "${GREEN}=======================================================${NC}\n"
echo
echo "Server:      $SERVER_URL"
echo "Owner:       $OWNER_EMAIL"
echo "Label:       $LABEL"
echo "Key ID:      $KEY_ID"
echo
printf "${YELLOW}⚠  API KEY (mostrado UNA SOLA VEZ — guardalo en password manager):${NC}\n"
printf "${YELLOW}   ${API_KEY}${NC}\n"
echo
echo "Para usarlo:"
echo "  export METALINS_SERVER=\"$SERVER_URL\""
echo "  export METALINS_DEV_KEY=\"$API_KEY\""
echo "  bash scripts/smoke-test-prod.sh"
echo

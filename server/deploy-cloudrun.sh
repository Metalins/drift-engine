#!/usr/bin/env bash
# deploy-cloudrun.sh — full deploy del server de Metalins a Google Cloud Run.
#
# Idempotente: podés correrlo varias veces. Crea/actualiza secrets, asegura
# que la compute SA tenga permisos, deploya, lee la URL real, actualiza env
# vars, smoke-testea endpoints públicos, y registra el deploy en
# ../deployments.log para tener historial.
#
# Pre-requisitos:
#   - gcloud CLI instalado + autenticado (`gcloud auth login`)
#   - Proyecto activo (`gcloud config set project ...`)
#   - APIs habilitadas (run, cloudbuild, artifactregistry, secretmanager)
#   - Keys generadas localmente (`make generate-keys`)
#
# Uso:
#   cd server
#   bash deploy-cloudrun.sh

set -euo pipefail

SERVICE="metalins-server"
# us-east1 (NOT southamerica-east1): São Paulo no soporta domain mappings de
# Cloud Run (HttpError 501 UNIMPLEMENTED). us-east1 sí, y tiene buena
# latencia para clientes LATAM (~100ms) + USA (~5-20ms).
REGION="us-east1"
PRIVATE_SECRET="metalins-private-key"
PUBLIC_SECRET="metalins-public-key"
MASTER_TOKEN_SECRET="metalins-master-token"
DB_URL_SECRET="metalins-db-url"   # opcional: si existe, se inyecta como METALINS_DB_URL
RESEND_API_KEY_SECRET="metalins-resend-api-key"  # opcional: si existe, se inyecta como METALINS_RESEND_API_KEY
SUPABASE_JWT_SECRET_NAME="metalins-supabase-jwt-secret"  # Sprint 3a-auth
WATCHER_KEK_SECRET="metalins-watcher-kek"                # Sprint 4 (envelope encryption)
TEST_USER_BYPASS_SECRET_NAME="metalins-test-user-bypass" # Sprint UX-5.11 (synthetic users)
TURNSTILE_SECRET_NAME="metalins-turnstile-secret"        # opcional: anti-abuso phase-2 → METALINS_TURNSTILE_SECRET
SUPABASE_SERVICE_ROLE_SECRET="metalins-supabase-service-role-key"  # opcional: borrado de cuenta → METALINS_SUPABASE_SERVICE_ROLE_KEY
# Defaults para los Supabase plain env vars. Pueden ser sobrescritos exportando
# METALINS_SUPABASE_URL / METALINS_SUPABASE_PROJECT_REF antes de correr.
SUPABASE_URL_DEFAULT="https://ehhxyivzxibinubkzwlb.supabase.co"
SUPABASE_PROJECT_REF_DEFAULT="ehhxyivzxibinubkzwlb"
KEY_ID="metalins-key-2026-1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEPLOY_LOG="${REPO_ROOT}/deployments.log"
cd "$SCRIPT_DIR"

# --- color helpers ---
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()   { printf "${GREEN}▶${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}⚠${NC} %s\n" "$*"; }
fail()  { printf "${RED}✗ %s${NC}\n" "$*" >&2; exit 1; }

# --- step 0: pre-checks ---
log "Pre-flight checks..."
command -v gcloud >/dev/null || fail "gcloud CLI no encontrado. Instalá con: brew install --cask google-cloud-sdk"
[ -f keys/private_key.pem ] || fail "No existe keys/private_key.pem. Corré: python3 scripts/generate_keypair.py"
[ -f keys/public_key.pem ]  || fail "No existe keys/public_key.pem.  Corré: python3 scripts/generate_keypair.py"

PROJECT="$(gcloud config get-value project 2>/dev/null)"
[ -n "$PROJECT" ] || fail "No hay proyecto activo. Corré: gcloud config set project <PROJECT_ID>"
ACCOUNT="$(gcloud config get-value account 2>/dev/null)"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

log "Project:        $PROJECT  (number: $PROJECT_NUMBER)"
log "Account:        $ACCOUNT"
log "Region:         $REGION"
log "Service:        $SERVICE"

# --- step 1: IAM bindings para Cloud Build desde source ---
log "Asegurando IAM bindings para Cloud Build (idempotente)..."
for ROLE in \
  "roles/storage.objectViewer" \
  "roles/logging.logWriter" \
  "roles/artifactregistry.writer" \
  "roles/run.builder"; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:${COMPUTE_SA}" \
    --role="$ROLE" \
    --condition=None \
    --quiet >/dev/null
done
log "IAM bindings aplicados al compute SA."

# --- step 2: crear/actualizar secrets ---
log "Verificando secrets en Secret Manager..."
if gcloud secrets describe "$PRIVATE_SECRET" >/dev/null 2>&1; then
  warn "Secret $PRIVATE_SECRET ya existe — agregando nueva versión."
  gcloud secrets versions add "$PRIVATE_SECRET" --data-file=keys/private_key.pem >/dev/null
else
  log "Creando secret $PRIVATE_SECRET..."
  gcloud secrets create "$PRIVATE_SECRET" --data-file=keys/private_key.pem >/dev/null
fi

if gcloud secrets describe "$PUBLIC_SECRET" >/dev/null 2>&1; then
  warn "Secret $PUBLIC_SECRET ya existe — agregando nueva versión."
  gcloud secrets versions add "$PUBLIC_SECRET" --data-file=keys/public_key.pem >/dev/null
else
  log "Creando secret $PUBLIC_SECRET..."
  gcloud secrets create "$PUBLIC_SECRET" --data-file=keys/public_key.pem >/dev/null
fi

# Master token para endpoints admin: si no existe el secret, lo generamos aleatoriamente.
if gcloud secrets describe "$MASTER_TOKEN_SECRET" >/dev/null 2>&1; then
  log "Secret $MASTER_TOKEN_SECRET ya existe (reusando)."
else
  log "Generando master token aleatorio + creando secret $MASTER_TOKEN_SECRET..."
  TOKEN_VALUE="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  printf "%s" "$TOKEN_VALUE" | gcloud secrets create "$MASTER_TOKEN_SECRET" --data-file=- >/dev/null
  echo
  printf "${YELLOW}⚠  MASTER TOKEN generado (UNA SOLA VEZ): ${TOKEN_VALUE}${NC}\n"
  printf "${YELLOW}   Guardalo en password manager. Lo necesitás para llamar a /v1/admin/*.${NC}\n"
  echo
fi

# Supabase JWT secret (Sprint 3a-auth) — requerido para validar magic-link tokens.
# Si el secret no existe, leerlo de la env var METALINS_SUPABASE_JWT_SECRET (que
# Jose exporta UNA VEZ antes de la primera corrida). Después de crearlo en Secret
# Manager, las siguientes corridas no necesitan la env var.
if gcloud secrets describe "$SUPABASE_JWT_SECRET_NAME" >/dev/null 2>&1; then
  log "Secret $SUPABASE_JWT_SECRET_NAME ya existe (reusando)."
else
  if [ -z "${METALINS_SUPABASE_JWT_SECRET:-}" ]; then
    fail "Secret $SUPABASE_JWT_SECRET_NAME no existe en Secret Manager y la env var METALINS_SUPABASE_JWT_SECRET no está seteada.
Para crear el secret la PRIMERA vez, corré:
  export METALINS_SUPABASE_JWT_SECRET='<el JWT secret de Supabase Settings → API>'
  bash deploy-cloudrun.sh
Después la env var ya no hace falta — el secret queda en Secret Manager."
  fi
  log "Creando secret $SUPABASE_JWT_SECRET_NAME desde env var..."
  printf "%s" "$METALINS_SUPABASE_JWT_SECRET" | \
    gcloud secrets create "$SUPABASE_JWT_SECRET_NAME" --data-file=- >/dev/null
fi

# Watcher KEK (Sprint 4). Used to AES-256-GCM encrypt bot tokens stored in
# the `watchers` table. 32 bytes hex (64 chars). Auto-generated on first
# deploy if not present; rotation is manual + re-encrypts existing rows.
if gcloud secrets describe "$WATCHER_KEK_SECRET" >/dev/null 2>&1; then
  log "Secret $WATCHER_KEK_SECRET ya existe (reusando)."
else
  log "Generando watcher KEK aleatorio (32 bytes hex)..."
  KEK_VALUE="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  printf "%s" "$KEK_VALUE" | gcloud secrets create "$WATCHER_KEK_SECRET" --data-file=- >/dev/null
  echo
  printf "${YELLOW}⚠  Watcher KEK creado. Si se pierde, los bot tokens existentes no se pueden desencriptar.${NC}\n"
  echo
fi

# Test-user bypass secret (Sprint UX-5.11 — Synthetic User Validation).
# Optional. When set, the backend accepts an HMAC-signed header that maps
# the caller to the canonical sandbox tenant (testing@metalins.local). If
# the secret is missing from Secret Manager AND no METALINS_TEST_USER_BYPASS
# env var is exported, we skip the bind silently — the bypass path simply
# stays disabled, which is the right default for any prod-like environment
# that doesn't need synthetic personas.
TEST_USER_BYPASS_FLAG=""
if gcloud secrets describe "$TEST_USER_BYPASS_SECRET_NAME" >/dev/null 2>&1; then
  log "Secret $TEST_USER_BYPASS_SECRET_NAME ya existe (reusando)."
  TEST_USER_BYPASS_FLAG=",METALINS_TEST_USER_BYPASS_SECRET=${TEST_USER_BYPASS_SECRET_NAME}:latest"
elif [ -n "${METALINS_TEST_USER_BYPASS:-}" ]; then
  log "Creando secret $TEST_USER_BYPASS_SECRET_NAME desde env var..."
  printf "%s" "$METALINS_TEST_USER_BYPASS" | \
    gcloud secrets create "$TEST_USER_BYPASS_SECRET_NAME" --data-file=- >/dev/null
  TEST_USER_BYPASS_FLAG=",METALINS_TEST_USER_BYPASS_SECRET=${TEST_USER_BYPASS_SECRET_NAME}:latest"
  echo
  printf "${YELLOW}⚠  Test-user bypass secret guardado en Secret Manager (Sprint UX-5.11).${NC}\n"
  printf "${YELLOW}   La próxima corrida de deploy-cloudrun.sh ya no necesita la env var.${NC}\n"
  echo
else
  warn "Secret $TEST_USER_BYPASS_SECRET_NAME NO existe y METALINS_TEST_USER_BYPASS no está exportado."
  warn "El bypass-auth para synthetic users queda DESHABILITADO en este deploy (esperado en prod sin testing)."
  warn "Para habilitarlo: export METALINS_TEST_USER_BYPASS=\"\$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')\" y re-corré este script."
fi

# Resolver URL + project_ref (env var > default hardcodeado)
SUPABASE_URL_VALUE="${METALINS_SUPABASE_URL:-$SUPABASE_URL_DEFAULT}"
SUPABASE_PROJECT_REF_VALUE="${METALINS_SUPABASE_PROJECT_REF:-$SUPABASE_PROJECT_REF_DEFAULT}"
log "Supabase URL:       $SUPABASE_URL_VALUE"
log "Supabase project:   $SUPABASE_PROJECT_REF_VALUE"

# Verificar si existe el secret de DB URL (opcional, para Postgres prod)
DB_URL_FLAG=""
if gcloud secrets describe "$DB_URL_SECRET" >/dev/null 2>&1; then
  log "Secret $DB_URL_SECRET detectado — se inyectará como METALINS_DB_URL (Postgres prod)."
  DB_URL_FLAG=",METALINS_DB_URL=${DB_URL_SECRET}:latest"
else
  warn "Secret $DB_URL_SECRET NO existe — server usará SQLite ephemeral (default)."
  warn "Para Postgres prod (recomendado): gcloud secrets create $DB_URL_SECRET --data-file=-"
fi

# Sprint UX-5.13.E.7 (2026-05-18) — Resend API key para email
# delivery. Opcional: si el secret no existe, email_delivery.send_email
# loguea un warning y no envía. El resto del alert pipeline (webhook,
# dashboard signals) sigue funcionando.
RESEND_API_KEY_FLAG=""
if gcloud secrets describe "$RESEND_API_KEY_SECRET" >/dev/null 2>&1; then
  log "Secret $RESEND_API_KEY_SECRET detectado — emails via Resend habilitados."
  RESEND_API_KEY_FLAG=",METALINS_RESEND_API_KEY=${RESEND_API_KEY_SECRET}:latest"
else
  warn "Secret $RESEND_API_KEY_SECRET NO existe — email delivery deshabilitado."
  warn "Para habilitarlo: printf '%s' 're_xxxx' | gcloud secrets create $RESEND_API_KEY_SECRET --data-file=-"
fi

# Phase-2 anti-abuso — Cloudflare Turnstile secret. Opcional: si no
# existe, el endpoint de reporte falla cerrado (no flaguea sin humano
# verificado), o sea la feature queda inerte hasta configurarlo.
TURNSTILE_SECRET_FLAG=""
if gcloud secrets describe "$TURNSTILE_SECRET_NAME" >/dev/null 2>&1; then
  log "Secret $TURNSTILE_SECRET_NAME detectado — reporte anti-abuso habilitado."
  TURNSTILE_SECRET_FLAG=",METALINS_TURNSTILE_SECRET=${TURNSTILE_SECRET_NAME}:latest"
else
  warn "Secret $TURNSTILE_SECRET_NAME NO existe — reporte anti-abuso inerte."
  warn "Para habilitarlo: printf '%s' '<turnstile-secret>' | gcloud secrets create $TURNSTILE_SECRET_NAME --data-file=-"
fi

# Borrado de cuenta — Supabase service-role key. Opcional: si no
# existe, el borrado de cuenta igual limpia TODOS los datos del
# usuario, pero el registro auth.users de Supabase sobrevive.
SUPABASE_SERVICE_ROLE_FLAG=""
if gcloud secrets describe "$SUPABASE_SERVICE_ROLE_SECRET" >/dev/null 2>&1; then
  log "Secret $SUPABASE_SERVICE_ROLE_SECRET detectado — el borrado de cuenta también remueve auth.users."
  SUPABASE_SERVICE_ROLE_FLAG=",METALINS_SUPABASE_SERVICE_ROLE_KEY=${SUPABASE_SERVICE_ROLE_SECRET}:latest"
else
  warn "Secret $SUPABASE_SERVICE_ROLE_SECRET NO existe — el borrado de cuenta no removerá el registro auth.users."
  warn "Para habilitarlo: printf '%s' '<service-role-key>' | gcloud secrets create $SUPABASE_SERVICE_ROLE_SECRET --data-file=-"
fi

# Permitir que la compute SA lea estos secrets
log "Dando acceso a los secrets al compute SA..."
ACCESSIBLE_SECRETS=("$PRIVATE_SECRET" "$PUBLIC_SECRET" "$MASTER_TOKEN_SECRET" "$SUPABASE_JWT_SECRET_NAME" "$WATCHER_KEK_SECRET")
if [ -n "$DB_URL_FLAG" ]; then
  ACCESSIBLE_SECRETS+=("$DB_URL_SECRET")
fi
if [ -n "$TEST_USER_BYPASS_FLAG" ]; then
  ACCESSIBLE_SECRETS+=("$TEST_USER_BYPASS_SECRET_NAME")
fi
if [ -n "$RESEND_API_KEY_FLAG" ]; then
  ACCESSIBLE_SECRETS+=("$RESEND_API_KEY_SECRET")
fi
if [ -n "$TURNSTILE_SECRET_FLAG" ]; then
  ACCESSIBLE_SECRETS+=("$TURNSTILE_SECRET_NAME")
fi
if [ -n "$SUPABASE_SERVICE_ROLE_FLAG" ]; then
  ACCESSIBLE_SECRETS+=("$SUPABASE_SERVICE_ROLE_SECRET")
fi
for SECRET in "${ACCESSIBLE_SECRETS[@]}"; do
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --member="serviceAccount:${COMPUTE_SA}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet >/dev/null
done

# --- step 3: deploy ---
log "Deployando $SERVICE a Cloud Run en $REGION (esto tarda 1-3 minutos)..."
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 1 \
  --max-instances 3 \
  --concurrency 80 \
  --timeout 60s \
  --set-secrets="METALINS_PRIVATE_KEY_PEM=${PRIVATE_SECRET}:latest,METALINS_PUBLIC_KEY_PEM=${PUBLIC_SECRET}:latest,METALINS_MASTER_TOKEN=${MASTER_TOKEN_SECRET}:latest,METALINS_SUPABASE_JWT_SECRET=${SUPABASE_JWT_SECRET_NAME}:latest,METALINS_WATCHER_KEK=${WATCHER_KEK_SECRET}:latest${DB_URL_FLAG}${TEST_USER_BYPASS_FLAG}${RESEND_API_KEY_FLAG}${TURNSTILE_SECRET_FLAG}${SUPABASE_SERVICE_ROLE_FLAG}" \
  --set-env-vars="METALINS_ENV=production,METALINS_KEY_ID=${KEY_ID},METALINS_SUPABASE_URL=${SUPABASE_URL_VALUE},METALINS_SUPABASE_PROJECT_REF=${SUPABASE_PROJECT_REF_VALUE}" \
  --quiet

# --- step 4: leer URL real y actualizar env vars ---
SERVER_URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
log "URL del deploy: $SERVER_URL"

log "Actualizando env vars con la URL real..."
gcloud run services update "$SERVICE" \
  --region "$REGION" \
  --update-env-vars="METALINS_API_BASE_URL=${SERVER_URL},METALINS_PUBLIC_BASE_URL=${SERVER_URL}" \
  --quiet >/dev/null

# --- step 4b: Cloud Scheduler (ops-2) ---
# El APScheduler en-proceso NO es confiable en Cloud Run: la CPU se
# estrangula a ~0 entre requests (no usamos --no-cpu-throttling) así que el
# thread de background no tickea, y cada deploy resetea el timer del trigger
# `interval`. Resultado histórico: el observable_job dejó de correr después
# de una ráfaga de deploys (ops-2). La fuente de verdad de la cadencia es
# Cloud Scheduler externo, que despierta a Cloud Run vía HTTP — inmune al
# throttling y a los redeploys. El APScheduler queda como warm-backup.
#
# Idempotente: create si no existe, update si existe. Se re-aplica en cada
# deploy, así que el sistema se auto-cura si algún job fue borrado.
log "Configurando Cloud Scheduler (fuente de verdad de la cadencia, ops-2)..."
# NON-FATAL: una falla de IAM/permisos NO debe abortar el deploy entero (si
# no, el backup in-proc tampoco se desplegaría). Desactivamos errexit dentro
# del bloque y registramos el resultado en SCHEDULER_STATUS para el log y la
# QA. Si esto falla, el grep del CI lo delata y la QA en Supabase (rows cada
# hora) lo confirma.
SCHEDULER_STATUS="skipped"
set +e
(
  set -e
  gcloud services enable cloudscheduler.googleapis.com --quiet >/dev/null

  # El run-batch endpoint requiere el master token via header X-Master-Token.
  # Lo leemos de Secret Manager (queda dentro del boundary de GCP).
  MASTER_TOKEN_VALUE="$(gcloud secrets versions access latest --secret="$MASTER_TOKEN_SECRET")"
  [ -n "$MASTER_TOKEN_VALUE" ] || { echo "master token vacío"; exit 1; }

  # upsert_scheduler_job NAME SCHEDULE PATH DESCRIPTION
  upsert_scheduler_job() {
    local name="$1" schedule="$2" path="$3" desc="$4"
    local uri="${SERVER_URL}${path}"
    if gcloud scheduler jobs describe "$name" --location="$REGION" >/dev/null 2>&1; then
      log "Cloud Scheduler job '$name' existe — actualizando."
      gcloud scheduler jobs update http "$name" \
        --location="$REGION" \
        --schedule="$schedule" \
        --time-zone="UTC" \
        --uri="$uri" \
        --http-method=POST \
        --update-headers="X-Master-Token=${MASTER_TOKEN_VALUE}" \
        --attempt-deadline=320s \
        --description="$desc" \
        --quiet >/dev/null
    else
      log "Cloud Scheduler job '$name' no existe — creando."
      gcloud scheduler jobs create http "$name" \
        --location="$REGION" \
        --schedule="$schedule" \
        --time-zone="UTC" \
        --uri="$uri" \
        --http-method=POST \
        --headers="X-Master-Token=${MASTER_TOKEN_VALUE}" \
        --attempt-deadline=320s \
        --description="$desc" \
        --quiet >/dev/null
    fi
    printf "${GREEN}✓${NC} Cloud Scheduler '%s' → %s (%s)\n" "$name" "$uri" "$schedule"
  }

  # Observables: cada hora en punto (coincide con el interval del in-proc).
  upsert_scheduler_job \
    "metalins-observables-hourly" \
    "0 * * * *" \
    "/v1/admin/observables/run-batch" \
    "ops-2: hourly Trinity observables batch over all active agents"

  # Watchers: cada minuto (mismo failure mode que observables en Cloud Run).
  upsert_scheduler_job \
    "metalins-watchers-every-min" \
    "* * * * *" \
    "/v1/admin/watchers/run-batch" \
    "ops-2: per-minute watcher poll over all active watchers"
)
if [ $? -eq 0 ]; then
  SCHEDULER_STATUS="ok"
  printf "${GREEN}✓${NC} Cloud Scheduler configurado (observables hourly + watchers per-min)\n"
else
  SCHEDULER_STATUS="FAILED"
  warn "Cloud Scheduler NO se pudo configurar — el deploy sigue, pero la cadencia"
  warn "depende del backup in-proc (no confiable). Revisá permisos del deployer SA:"
  warn "  roles/cloudscheduler.admin, roles/secretmanager.secretAccessor,"
  warn "  roles/serviceusage.serviceUsageAdmin. Luego re-corré el deploy."
fi
set -e

# --- step 5: smoke tests públicos ---
log "Esperando 5s para que el redeploy se estabilice..."
sleep 5

log "Smoke test — /health"
if curl -fsS "${SERVER_URL}/health" | grep -q '"status":"ok"'; then
  printf "${GREEN}✓${NC} /health OK\n"
else
  fail "/health no respondió correctamente"
fi

log "Smoke test — /.well-known/jwks.json"
JWKS="$(curl -fsS "${SERVER_URL}/.well-known/jwks.json")"
if echo "$JWKS" | grep -q '"kty":"RSA"'; then
  printf "${GREEN}✓${NC} JWKS público OK (RSA key presente)\n"
else
  fail "JWKS no devolvió RSA key. Respuesta: $JWKS"
fi

log "Smoke test — /v1/revocations"
if curl -fsS "${SERVER_URL}/v1/revocations" | grep -q '"revocations"'; then
  printf "${GREEN}✓${NC} /v1/revocations OK\n"
else
  fail "/v1/revocations no respondió correctamente"
fi

log "Smoke test — /v1/admin/bootstrap-api-key (sin token → debe rechazar 401)"
# Sin -f para que curl no aborte en 4xx; queremos el status code, no que falle.
ADMIN_STATUS="$(curl -sS -o /dev/null -w "%{http_code}" -X POST \
    -H "Content-Type: application/json" \
    -d '{"owner_email":"test@test.com"}' \
    "${SERVER_URL}/v1/admin/bootstrap-api-key" || true)"
if [ "$ADMIN_STATUS" = "401" ]; then
  printf "${GREEN}✓${NC} Admin endpoint correctamente rechaza requests sin token (401)\n"
else
  fail "Admin endpoint debería devolver 401 sin token. Devolvió: $ADMIN_STATUS"
fi

# --- step 6: registrar deploy ---
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
GIT_COMMIT="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
GIT_DIRTY=""
if [ -n "$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null)" ]; then
  GIT_DIRTY=" (dirty: uncommitted changes)"
fi
REVISION="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.latestReadyRevisionName)')"

if [ ! -f "$DEPLOY_LOG" ]; then
  cat > "$DEPLOY_LOG" << 'EOF'
# Deployments log

Registro cronológico de todos los deploys a Cloud Run.

---

EOF
fi

cat >> "$DEPLOY_LOG" << EOF

## $TIMESTAMP

- **Service:**     $SERVICE
- **Region:**      $REGION
- **Project:**     $PROJECT
- **URL:**         $SERVER_URL
- **Revision:**    $REVISION
- **Git commit:**  ${GIT_COMMIT}${GIT_DIRTY}
- **Operator:**    $ACCOUNT
- **Cloud Scheduler:** ${SCHEDULER_STATUS} (ops-2: observables hourly + watchers per-min)
- **Result:**      ✅ Success (public + admin smoke tests passed)

EOF

log "Deploy registrado en $DEPLOY_LOG"

# --- success ---
echo
printf "${GREEN}=======================================================${NC}\n"
printf "${GREEN}✅ DEPLOY EXITOSO${NC}\n"
printf "${GREEN}=======================================================${NC}\n"
echo
echo "URL del server:  $SERVER_URL"
echo "Revision:        $REVISION"
echo "Region:          $REGION"
echo "Git commit:      ${GIT_COMMIT}${GIT_DIRTY}"
echo
echo "Próximos pasos:"
echo "  • Para crear el primer API key en prod:"
echo "      bash scripts/bootstrap-prod-key.sh"
echo "  • Para smoke test E2E completo contra prod:"
echo "      bash scripts/smoke-test-prod.sh"
echo
